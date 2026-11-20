#include "ReedDebouncer.h"
#include <cassert>
#include <cstdint>
#include <cstdio>

static void none(ReedUpdate e) { assert(!e.accepted && !e.tooFast); }
static void accept(ReedUpdate e, uint32_t when) { assert(e.accepted && !e.tooFast && e.atMs == when); }
static void tooFast(ReedUpdate e) { assert(!e.accepted && e.tooFast); }

static void normalRevolutions() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0);
  none(r.observe(true, 100));
  none(r.tick(129));
  accept(r.tick(130), 100);
  none(r.tick(140)); // no duplicate while contact remains closed
  none(r.observe(false, 160));
  none(r.tick(189));
  none(r.tick(190)); // stable OPEN re-arms
  none(r.observe(true, 400));
  accept(r.tick(430), 400);
  assert(r.stableClosures() == 2);
}

static void contactBounceBothDirections() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0);
  none(r.observe(true, 100));
  none(r.observe(false, 102)); // 2 ms contact bounce
  none(r.observe(true, 105));
  none(r.observe(false, 109));
  none(r.observe(true, 115));
  none(r.tick(144));
  accept(r.tick(145), 115);
  none(r.observe(false, 180));
  none(r.observe(true, 182)); // brief opening, NOT rearmed
  none(r.observe(false, 187));
  none(r.observe(true, 191));
  none(r.observe(false, 195));
  none(r.tick(224));
  none(r.tick(225)); // reopened stably
  none(r.observe(true, 460));
  accept(r.tick(490), 460);
  assert(r.shortGlitches() >= 4);
  assert(r.stableClosures() == 2);
}

static void intervalGuard() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0);
  none(r.observe(true, 100));
  accept(r.tick(130), 100);
  none(r.observe(false, 150));
  none(r.tick(180));
  none(r.observe(true, 220)); // re-close only 120 ms after first close
  tooFast(r.tick(250));
  none(r.observe(false, 260));
  none(r.tick(290));
  none(r.observe(true, 500));
  accept(r.tick(530), 500);
}

static void initialContactClosed() {
  ReedDebouncer r(30, 180);
  r.begin(true, 0);
  none(r.tick(100)); // cannot count contact held across boot
  none(r.observe(false, 200));
  none(r.tick(230));
  none(r.observe(true, 400));
  accept(r.tick(430), 400);
}

static void delayedEdgeReplay() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0);
  // The main task gets scheduled late and receives a historical edge backlog.
  none(r.observe(true, 100));
  accept(r.observe(false, 150), 100); // closure settled before next queued edge
  none(r.observe(true, 500)); // prior OPEN is now stable; this starts a fresh candidate
  accept(r.tick(530), 500);
}

static void twentyBounceEdgesOneRevolution() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0);
  for (uint32_t i = 0; i < 20; ++i) {
    none(r.observe((i % 2) == 0, 100 + i * 2));
  }
  none(r.observe(true, 140)); // final contact closure
  none(r.tick(169));
  accept(r.tick(170), 140);
  none(r.tick(1000)); // parking over sensor must not repeat
  assert(r.shortGlitches() >= 10);
  assert(r.stableClosures() == 1);
}

static void millisecondClockWrap() {
  ReedDebouncer r(30, 180);
  r.begin(false, 0xFFFFFF00u);
  none(r.observe(true, 0xFFFFFFF0u));
  none(r.tick(0x0000000Du)); // 29 ms elapsed
  accept(r.tick(0x0000000Eu), 0xFFFFFFF0u);
  none(r.observe(false, 0x00000040u));
  none(r.tick(0x0000005Eu));
  none(r.observe(true, 0x00000100u));
  accept(r.tick(0x0000011Eu), 0x00000100u);
}

int main() {
  normalRevolutions();
  contactBounceBothDirections();
  intervalGuard();
  initialContactClosed();
  delayedEdgeReplay();
  twentyBounceEdgesOneRevolution();
  millisecondClockWrap();
  std::puts("reed debouncer: 7 tests passed");
}
