#include <Arduino.h>
#include "Config.h"
#include "ReedDebouncer.h"

// v0.3 diagnostic. Connect the EXTERNAL 4.7 kΩ resistor BEFORE running this.
// 3V3 -- 4.7k -- GPIO2 -- dry reed -- GND. Original LCD disconnected.
ReedDebouncer reed(cfg::CONTACT_STABLE_MS, cfg::MIN_REV_INTERVAL_MS);
uint32_t accepted = 0, rejectedFast = 0;
uint32_t previousStats = 0;

void report(const ReedUpdate &update) {
  if (update.accepted) {
    Serial.printf("[REV] #%lu, contact closed at %lu ms\n", ++accepted, update.atMs);
  }
  if (update.tooFast) {
    Serial.printf("[REJECT] too-fast stable closure, total=%lu\n", ++rejectedFast);
  }
}

void setup() {
  Serial.begin(115200);
  delay(250);
  pinMode(cfg::SENSOR_GPIO, INPUT); // no internal pull-up; external 4.7k required
  reed.begin(digitalRead(cfg::SENSOR_GPIO) == LOW, millis());
  Serial.printf("PEDAL sensor probe v0.3: GPIO%u, external 4.7k pull-up required\n", cfg::SENSOR_GPIO);
  Serial.printf("Closed/open debounce=%lu ms; minimum revolution interval=%lu ms\n",
    static_cast<unsigned long>(cfg::CONTACT_STABLE_MS),
    static_cast<unsigned long>(cfg::MIN_REV_INTERVAL_MS));
  Serial.println("Rotate slowly: expect one [REV] per full magnet pass. Contact bounce is ignored.");
}

void loop() {
  const uint32_t now = millis();
  report(reed.observe(digitalRead(cfg::SENSOR_GPIO) == LOW, now));
  report(reed.tick(now));
  if (static_cast<uint32_t>(now - previousStats) >= 5000) {
    previousStats = now;
    Serial.printf("[STATS] accepted=%lu rejectedFast=%lu rawTransitions=%lu bounceFiltered=%lu stableContact=%s\n",
      static_cast<unsigned long>(accepted), static_cast<unsigned long>(rejectedFast),
      static_cast<unsigned long>(reed.rawTransitions()),
      static_cast<unsigned long>(reed.shortGlitches()),
      reed.stableClosed() ? "CLOSED" : "OPEN");
  }
  delay(1); // only in standalone probe; main firmware uses GPIO CHANGE ISR ring
}
