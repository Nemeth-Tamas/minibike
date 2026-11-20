#pragma once
#include <stdint.h>

// Hardware-independent, nonblocking reed-contact filter. A valid revolution
// requires: stable CLOSED for debounceMs; then stable OPEN for debounceMs
// before another CLOSED can count. A minimum interval guards fast repeat taps.
// Timestamp arithmetic intentionally uses unsigned 32-bit differences to
// handle the millis() counter wrapping after ~49 days.
struct ReedUpdate {
  bool accepted = false;
  bool tooFast = false;
  uint32_t atMs = 0; // start of the validated closure, not callback time
};

class ReedDebouncer {
 public:
  ReedDebouncer(uint32_t debounceMs, uint32_t minIntervalMs)
    : debounceMs_(debounceMs), minIntervalMs_(minIntervalMs) {}

  void begin(bool initiallyClosed, uint32_t nowMs) {
    rawClosed_ = stableClosed_ = initiallyClosed;
    armed_ = !initiallyClosed; // do not count a magnet parked on the sensor at boot
    hasAccepted_ = false;
    rawChangedAt_ = lastAcceptedAt_ = nowMs;
    rawTransitions_ = shortGlitches_ = stableClosures_ = 0;
  }

  // Feed GPIO CHANGE interrupts in their original timestamp order. A late
  // consumer can replay buffered transitions without losing time information.
  ReedUpdate observe(bool closed, uint32_t atMs) {
    ReedUpdate result = settle(atMs);
    if (closed != rawClosed_) {
      if (rawClosed_ != stableClosed_ && closed == stableClosed_) {
        ++shortGlitches_; // candidate reverted before reaching 30 ms
      }
      rawClosed_ = closed;
      rawChangedAt_ = atMs;
      ++rawTransitions_;
    }
    return result;
  }

  // Must be called even when no new edges arrive, to confirm stable closures.
  ReedUpdate tick(uint32_t nowMs) { return settle(nowMs); }

  uint32_t rawTransitions() const { return rawTransitions_; }
  uint32_t shortGlitches() const { return shortGlitches_; }
  uint32_t stableClosures() const { return stableClosures_; }
  bool stableClosed() const { return stableClosed_; }

 private:
  ReedUpdate settle(uint32_t nowMs) {
    ReedUpdate out;
    if (rawClosed_ == stableClosed_ ||
        static_cast<uint32_t>(nowMs - rawChangedAt_) < debounceMs_) return out;
    stableClosed_ = rawClosed_;
    if (!stableClosed_) {
      armed_ = true; // requires a confirmed reopening to arm the next event
      return out;
    }
    ++stableClosures_;
    if (!armed_) return out;
    armed_ = false;
    if (!hasAccepted_ ||
        static_cast<uint32_t>(rawChangedAt_ - lastAcceptedAt_) >= minIntervalMs_) {
      hasAccepted_ = true;
      lastAcceptedAt_ = rawChangedAt_;
      out.accepted = true;
      out.atMs = rawChangedAt_;
    } else {
      out.tooFast = true;
    }
    return out;
  }

  uint32_t debounceMs_, minIntervalMs_;
  uint32_t rawChangedAt_ = 0, lastAcceptedAt_ = 0;
  uint32_t rawTransitions_ = 0, shortGlitches_ = 0, stableClosures_ = 0;
  bool rawClosed_ = false, stableClosed_ = false, armed_ = true, hasAccepted_ = false;
};
