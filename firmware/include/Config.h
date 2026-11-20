#pragma once
#include <Arduino.h>

namespace cfg {
constexpr char DEVICE_ID[] = "bike-001";
constexpr uint8_t SENSOR_GPIO = 2; // GPIO number, NOT Arduino D2
constexpr uint8_t I2C_SDA = 0;
constexpr uint8_t I2C_SCL = 1;
constexpr uint8_t EEPROM_ADDR = 0x50; // A0/A1/A2 tied LOW on typical AT24C256 breakout

// A closed reed contact pulls the GPIO to GND.
constexpr uint32_t CONTACT_STABLE_MS = 30; // 30 ms stable in BOTH directions; tune from real reed traces
constexpr uint32_t MIN_REV_INTERVAL_MS = 180; // additional plausibility gate, max 333 RPM
constexpr uint32_t MQTT_RETRY_MS = 1000;
constexpr uint32_t ACK_TIMEOUT_MS = 5000;
constexpr uint32_t WIFI_RETRY_MS = 12000;
constexpr uint32_t STATS_INTERVAL_MS = 30000;
constexpr uint8_t MQTT_BATCH_SIZE = 8;
}
