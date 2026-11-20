// PEDAL. ESP32-C6 firmware — MQTT v1 compatible with the running delta2 backend.
// v0.3: external 4.7k pull-up and tested nonblocking 30 ms reed debounce.
// Arduino-ESP32 3.x, ArduinoJson 7.x, MQTT (Joel Gaehwiler / 256dpi) 2.5.x.
// IMPORTANT: do NOT flash/use with bike-001 until simulator data have been reset.
#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <MQTT.h>             // Joel Gaehwiler's MQTT, NOT PubSubClient (QoS1)
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <sys/time.h>
#include <driver/pulse_cnt.h>
#include <esp_err.h>
#include <cstring>
#include "Config.h"
#include "Journal.h"
#include "ReedDebouncer.h"
#include "secrets.h"

RevJournal journal;
WiFiClient network;
MQTTClient mqtt(2048, 2048);
String eventTopic = String("pedal/v1/") + cfg::DEVICE_ID + "/events";
String ackTopic = String("pedal/v1/") + cfg::DEVICE_ID + "/ack";
uint32_t currentBootToken = 0;

// IRQ only takes a timestamp and level. All debouncing, EEPROM and network work
// happens in loop() to avoid dropping events while another operation is running.
struct Edge { uint32_t atMs; uint8_t level; };
constexpr uint16_t EDGE_CAP = 256; // power of two
volatile Edge edgeRing[EDGE_CAP];
volatile uint16_t edgeHead = 0, edgeTail = 0;
volatile uint32_t discardedEdges = 0;
portMUX_TYPE edgeMux = portMUX_INITIALIZER_UNLOCKED;

void ARDUINO_ISR_ATTR sensorChanged() {
  const uint32_t now = millis();
  const uint8_t level = static_cast<uint8_t>(digitalRead(cfg::SENSOR_GPIO));
  portENTER_CRITICAL_ISR(&edgeMux);
  const uint16_t next = (edgeHead + 1) & (EDGE_CAP - 1);
  if (next == edgeTail) ++discardedEdges;
  else { edgeRing[edgeHead].atMs = now; edgeRing[edgeHead].level = level; edgeHead = next; }
  portEXIT_CRITICAL_ISR(&edgeMux);
}

bool popEdge(Edge &edge) {
  portENTER_CRITICAL(&edgeMux);
  const bool ok = edgeTail != edgeHead;
  if (ok) {
    edge.atMs = edgeRing[edgeTail].atMs;
    edge.level = edgeRing[edgeTail].level;
    edgeTail = (edgeTail + 1) & (EDGE_CAP - 1);
  }
  portEXIT_CRITICAL(&edgeMux);
  return ok;
}

struct Pulse { uint32_t uptimeMs; };
constexpr size_t PULSE_CAP = 64;
Pulse pulses[PULSE_CAP];
size_t pulseHead = 0, pulseTail = 0, pulseSize = 0;
uint32_t lostUnjournaled = 0, rejectedTooFast = 0, acceptedSinceBoot = 0;
ReedDebouncer reed(cfg::CONTACT_STABLE_MS, cfg::MIN_REV_INTERVAL_MS);

void queuePulse(uint32_t ms) {
  if (pulseSize == PULSE_CAP) { ++lostUnjournaled; return; }
  pulses[pulseHead] = {ms};
  pulseHead = (pulseHead + 1) % PULSE_CAP;
  ++pulseSize;
  ++acceptedSinceBoot;
}

void processReedUpdate(const ReedUpdate &update) {
  if (update.accepted) queuePulse(update.atMs);
  if (update.tooFast) ++rejectedTooFast;
}

void handleEdges() {
  Edge edge;
  while (popEdge(edge)) {
    // Replaying ordered timestamps allows the 30 ms debounce to work even if
    // the network stalls the main loop. No EEPROM or Wi-Fi calls in an ISR.
    processReedUpdate(reed.observe(edge.level == LOW, edge.atMs));
  }
  const uint32_t now = millis();
  // Recover current state after ring overflow (lost edges cannot be recreated).
  const bool physicalClosed = digitalRead(cfg::SENSOR_GPIO) == LOW;
  processReedUpdate(reed.observe(physicalClosed, now));
  processReedUpdate(reed.tick(now));
}

uint64_t wallClockMs() {
  timeval tv = {};
  if (gettimeofday(&tv, nullptr) != 0 || tv.tv_sec < 1700000000) return 0;
  return static_cast<uint64_t>(tv.tv_sec) * 1000 + static_cast<uint64_t>(tv.tv_usec / 1000);
}

void flushPulses() {
  if (!pulseSize) return;
  // Max one durable EEPROM write per loop, with explicit readback verification.
  const uint32_t uptime = pulses[pulseTail].uptimeMs;
  uint64_t captureTime = wallClockMs();
  if (captureTime) captureTime -= static_cast<uint32_t>(millis() - uptime);
  if (!journal.append(captureTime, uptime, currentBootToken)) {
    static uint32_t lastWarning = 0;
    if (millis() - lastWarning > 2000) { Serial.println("[EEPROM] WRITE FAILED; retrying, sensor queue at risk!"); lastWarning = millis(); }
    return;
  }
  pulseTail = (pulseTail + 1) % PULSE_CAP;
  --pulseSize;
}

struct OutgoingBatch {
  bool active = false;
  bool ackReady = false;
  uint8_t count = 0;
  uint64_t seqs[cfg::MQTT_BATCH_SIZE] = {};
  uint32_t publishedAt = 0;
  String batchId;
  String payload;
} flight;

void receivedMqtt(String &topic, String &payload) {
  if (topic != ackTopic || !flight.active) return;
  JsonDocument doc;
  if (deserializeJson(doc, payload)) return;
  if ((doc["v"] | 0) != 1 || String(doc["batch_id"] | "") != flight.batchId) return;
  JsonArrayConst arr = doc["ack_sequences"].as<JsonArrayConst>();
  if (arr.isNull() || arr.size() != flight.count) return;
  bool covered[cfg::MQTT_BATCH_SIZE] = {};
  for (JsonVariantConst v : arr) {
    if (!v.is<uint64_t>() && !v.is<uint32_t>()) return;
    const uint64_t seq = v.as<uint64_t>();
    bool matched = false;
    for (uint8_t i = 0; i < flight.count; ++i) {
      if (flight.seqs[i] == seq && !covered[i]) { covered[i] = true; matched = true; break; }
    }
    if (!matched) return;
  }
  flight.ackReady = true; // journal writes happen OUTSIDE MQTT callback
}

void commitAcks() {
  if (!flight.active || !flight.ackReady) return;
  uint8_t acked = 0;
  for (uint8_t i = 0; i < flight.count; ++i) {
    if (journal.markAcked(flight.seqs[i])) ++acked;
    else Serial.printf("[ACK] Failed EEPROM ack seq=%llu; will resend\n",
                       static_cast<unsigned long long>(flight.seqs[i]));
  }
  Serial.printf("[ACK] server committed %u records, EEPROM marked %u\n", flight.count, acked);
  flight.active = false; // any unmarked event remains pending and will be resent
  flight.ackReady = false;
  flight.payload = "";
}

bool sendFlight() {
  if (!flight.active || !mqtt.connected()) return false;
  flight.publishedAt = millis();
  return mqtt.publish(eventTopic, flight.payload, false, 1); // QoS 1 + app ACK
}

void makeBatch() {
  if (flight.active || !mqtt.connected()) return;
  RevRecord records[cfg::MQTT_BATCH_SIZE];
  const size_t count = journal.oldestPending(records, cfg::MQTT_BATCH_SIZE);
  if (!count) return;

  char batchId[48];
  snprintf(batchId, sizeof(batchId), "s%llu_n%u", static_cast<unsigned long long>(records[0].seq), static_cast<unsigned>(count));
  char bootId[20];
  snprintf(bootId, sizeof(bootId), "b%08lx", static_cast<unsigned long>(records[0].boot_token));
  JsonDocument doc;
  doc["v"] = 1;
  doc["device_id"] = cfg::DEVICE_ID;
  doc["boot_id"] = bootId;
  doc["batch_id"] = batchId;
  doc["lifetime_revs"] = journal.highestSeq();
  JsonArray events = doc["events"].to<JsonArray>();
  const uint64_t nowEpoch = wallClockMs();
  const uint32_t nowUp = millis();
  for (size_t i = 0; i < count; ++i) {
    JsonObject e = events.add<JsonObject>();
    e["seq"] = records[i].seq;
    e["uptime_ms"] = records[i].uptime_ms;
    uint64_t timestamp = records[i].epoch_ms;
    // If NTP synchronized AFTER this event, reconstruct epoch from same boot.
    if (!timestamp && nowEpoch && records[i].boot_token == currentBootToken) {
      timestamp = nowEpoch - static_cast<uint32_t>(nowUp - records[i].uptime_ms);
    }
    if (timestamp) e["t_ms"] = timestamp;
  }
  flight.payload = "";
  flight.payload.reserve(1600);
  serializeJson(doc, flight.payload);
  flight.batchId = batchId;
  flight.count = static_cast<uint8_t>(count);
  for (size_t i = 0; i < count; ++i) flight.seqs[i] = records[i].seq;
  flight.ackReady = false;
  flight.active = true;
  if (!sendFlight()) Serial.println("[MQTT] publish failed, will retry");
}

void connectServices() {
  static uint32_t lastWifiTry = 0, lastMqttTry = 0;
  static bool wifiWasUp = false, otaStarted = false;
  const uint32_t now = millis();
  const bool wifiUp = WiFi.status() == WL_CONNECTED;
  if (!wifiUp) {
    if (wifiWasUp) { Serial.println("[WiFi] disconnected"); wifiWasUp = false; }
    if (now - lastWifiTry >= cfg::WIFI_RETRY_MS || lastWifiTry == 0) {
      lastWifiTry = now;
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      Serial.println("[WiFi] reconnecting (sensor keeps logging)");
    }
    return;
  }
  if (!wifiWasUp) {
    wifiWasUp = true;
    Serial.print("[WiFi] IP "); Serial.println(WiFi.localIP());
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    if (!otaStarted && strlen(OTA_PASSWORD) >= 12) {
      ArduinoOTA.setHostname("pedal-bike-001");
      ArduinoOTA.setPassword(OTA_PASSWORD);
      ArduinoOTA.onStart([]() { Serial.println("[OTA] Starting firmware update"); });
      ArduinoOTA.onError([](ota_error_t e) { Serial.printf("[OTA] error %u\n", static_cast<unsigned>(e)); });
      ArduinoOTA.begin();
      otaStarted = true;
    }
  }
  if (otaStarted) ArduinoOTA.handle();
  if (mqtt.connected()) { mqtt.loop(); return; }
  if (now - lastMqttTry < cfg::MQTT_RETRY_MS && lastMqttTry != 0) return;
  lastMqttTry = now;
  char clientId[48];
  snprintf(clientId, sizeof(clientId), "pedal-c6-%08lx", static_cast<unsigned long>(currentBootToken));
  if (mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
    if (mqtt.subscribe(ackTopic, 1)) Serial.println("[MQTT] connected and subscribed to ACKs");
    else { Serial.println("[MQTT] ACK subscription FAILED; reconnecting"); mqtt.disconnect(); }
    if (flight.active) flight.publishedAt = 0; // retry unacknowledged batch after connection
  } else {
    Serial.println("[MQTT] connection failed, will retry");
  }
}

pcnt_unit_handle_t pcntUnit = nullptr;
void initPulseCounter() {
  pcnt_unit_config_t unit = {};
  unit.low_limit = -1;
  unit.high_limit = 32767;
  if (pcnt_new_unit(&unit, &pcntUnit) != ESP_OK) { Serial.println("[PCNT] unavailable"); return; }
  pcnt_chan_config_t channel = {};
  channel.edge_gpio_num = cfg::SENSOR_GPIO;
  channel.level_gpio_num = -1;
  pcnt_channel_handle_t handle = nullptr;
  if (pcnt_new_channel(pcntUnit, &channel, &handle) != ESP_OK) return;
  // GPIO active-low: count every raw falling edge. Not a debounced rev count!
  pcnt_channel_set_edge_action(handle, PCNT_CHANNEL_EDGE_ACTION_HOLD, PCNT_CHANNEL_EDGE_ACTION_INCREASE);
  pcnt_channel_set_level_action(handle, PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_KEEP);
  pcnt_glitch_filter_config_t glitch = {};
  glitch.max_glitch_ns = 1000; // microsecond noise, NOT mechanical debounce
  pcnt_unit_set_glitch_filter(pcntUnit, &glitch);
  pcnt_unit_enable(pcntUnit);
  pcnt_unit_start(pcntUnit);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\nPEDAL. firmware v0.3 (C6) - DO NOT connect bike-001 to simulator data");
  currentBootToken = esp_random();
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  // External 4.7 kΩ pull-up: 3V3 -- resistor -- GPIO2 -- reed -- GND.
  // Do not use INPUT_PULLUP; the internal pull-up is deliberately disabled.
  pinMode(cfg::SENSOR_GPIO, INPUT);
  reed.begin(digitalRead(cfg::SENSOR_GPIO) == LOW, millis());

  // Refuse to count if durability hardware is unavailable.
  while (!journal.begin()) {
    Serial.println("[FATAL] AT24C256 absent or unreadable. Check 3.3V, SDA, SCL, address.");
    delay(3000);
  }
  initPulseCounter();
  attachInterrupt(digitalPinToInterrupt(cfg::SENSOR_GPIO), sensorChanged, CHANGE);
  mqtt.begin(MQTT_HOST, MQTT_PORT, network);
  mqtt.setOptions(30, true, 1000);
  mqtt.onMessage(receivedMqtt);
  Serial.printf("[ready] device=%s seq=%llu\n", cfg::DEVICE_ID,
                static_cast<unsigned long long>(journal.highestSeq()));
}

void loop() {
  handleEdges();
  flushPulses();
  connectServices();
  commitAcks();
  if (mqtt.connected()) {
    if (!flight.active) makeBatch();
    else if (millis() - flight.publishedAt >= cfg::ACK_TIMEOUT_MS) {
      // Retry identical batch if application ACK lost (DB deduplicates).
      if (!sendFlight()) Serial.println("[MQTT] retry publish failed");
    }
  }
  static uint32_t lastStats = 0;
  if (millis() - lastStats >= cfg::STATS_INTERVAL_MS) {
    lastStats = millis();
    int rawPulses = -1;
    if (pcntUnit) { pcnt_unit_get_count(pcntUnit, &rawPulses); pcnt_unit_clear_count(pcntUnit); }
    Serial.printf("[status] seq=%llu pending=%lu ram=%u rawPCNT=%d accepted=%lu tooFast=%lu shortGlitches=%lu rawTransitions=%lu edgeDrops=%lu ramDrops=%lu queueOverwrites=%lu wifi=%d mqtt=%d\n",
      static_cast<unsigned long long>(journal.highestSeq()),
      static_cast<unsigned long>(journal.pendingCount()), static_cast<unsigned>(pulseSize), rawPulses,
      static_cast<unsigned long>(acceptedSinceBoot), static_cast<unsigned long>(rejectedTooFast),
      static_cast<unsigned long>(reed.shortGlitches()), static_cast<unsigned long>(reed.rawTransitions()),
      static_cast<unsigned long>(discardedEdges), static_cast<unsigned long>(lostUnjournaled),
      static_cast<unsigned long>(journal.overwrittenUnacked()),
      WiFi.status() == WL_CONNECTED, mqtt.connected());
  }
  delay(1);
}
