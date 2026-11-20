# PEDAL. ESP32-C6 SuperMini firmware · v0.1 (hardware validation pending)

**The firmware is written and its EEPROM journal has passed host-based C++ tests. The firmware has NOT yet been compiled against an ESP32-C6 toolchain, flashed onto the actual board, or validated with the bike's sensor.** Treat pin assignments and debounce timings as provisional until the hardware arrives.

## What is included

- `PedalC6/PedalC6.ino`: ESP32-C6 firmware, Wi-Fi, NTP, password-protected Arduino OTA, MQTT QoS 1, application ACK/retry, raw hardware PCNT diagnostics, and an interrupt-driven sensor edge queue
- `PedalC6/Journal.h` and `Journal.cpp`: verified-readback EEPROM circular journal, monotonically increasing sequence IDs, reboot recovery, ACK byte update, CRC32, and recovery of unsent events
- `PedalC6/Config.h`: wiring GPIOs, debounce and cadence settings
- `PedalC6/secrets.h.example`: local Wi-Fi/MQTT/OTA settings template (**create `secrets.h` locally**)
- `tools/sensor_probe/sensor_probe.ino`: separate first-day sensor wiring diagnostic
- `tests/run.sh`: C++ host tests with simulated 32 KB EEPROM; no Arduino installation needed

## The hardware and the pin assignments

**ONLY wire it as below after verifying the bike's two wires are an unpowered dry-contact reed switch.** The old display supplying 1.6 V across its sensor pins does not prove the sensor type. Disconnect the old display, use continuity mode while turning the pedals, and ensure there is no voltage present on the sensor lines before connecting the C6.

| Part | Connection | Notes |
|---|---|---|
| Reed switch lead A | `GPIO2` on C6 SuperMini | GPIO number, not a D2 label |
| Reed switch lead B | C6 `GND` | Dry contact ONLY; polarity doesn't matter |
| Optional pull-up resistor | `GPIO2` to C6 `3V3` | 4.7 kΩ recommended for noisy/long wiring; firmware also enables weak internal pull-up |
| AT24C256 `VCC` | C6 `3V3` | Not 5 V: ESP GPIO and I²C are 3.3 V |
| AT24C256 `GND` | C6 `GND` | Shared ground |
| AT24C256 `SDA` | C6 `GPIO0` | I²C address defaults to 0x50 if address pins low |
| AT24C256 `SCL` | C6 `GPIO1` | Conservative I²C at 100 kHz initially |
| AT24C256 `WP` | GND (if exposed) | Write-protect must be disabled |
| ESP32-C6 USB-C | 5 V phone charger or PC | Board regulator powers the 3.3 V components |

Avoid the C6's USB pins GPIO12/13 and boot-strapping pins. **Verify the exact Hestore SuperMini board's pin silkscreen before soldering.** Secure cables so moving pedal parts cannot snag them. Mount the ESP's antenna away from metal/hot-glue blobs. Do **not** route any mains AC wiring inside the bike.

### Why both PCNT and software filtering?

PCNT counts *raw electrical falling edges* in the background, useful as a check while Wi-Fi is busy. But its glitch filter operates on extremely short pulses; it **does not debounce a mechanical reed switch**. The authoritative revolution stream uses GPIO CHANGE interrupts with timestamps, 8 ms stable-low/high qualification, one event per close/open cycle, and a 180 ms physical plausibility window. A magnet held stationary in front of the switch counts only once. **A single switch cannot distinguish complete rotations from deliberate backward-and-forward rocking over the magnet.** That would require another position sensor.

## First flash / test sequence

1. Get the [Arduino IDE](https://www.arduino.cc/en/software). Add this Espressif Boards Manager URL: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`. Install **esp32 by Espressif Systems**, version 3.x (not Arduino-ESP32 v2).
2. Select **ESP32C6 Dev Module**. Board variants differ; choose 4 MB flash for a 4 MB module if applicable. Use a partition option with OTA slots if you plan to update wirelessly.
3. Install libraries in Arduino Library Manager: **ArduinoJson** (7.x, Benoît Blanchon) and **MQTT** (Joel Gaehwiler / 256dpi, 2.5.x). Do *not* substitute `PubSubClient`; that library doesn't publish at QoS 1.
4. Start with `tools/sensor_probe/sensor_probe.ino` *only after* proving the bike's sensor is a dry contact. With serial monitor at 115200, turn pedals slowly and look for one CLOSED, then OPEN per magnet pass. If the signal is noisy, investigate wiring before installing the main sketch.
5. Copy `PedalC6/secrets.h.example` to `PedalC6/secrets.h`; change Wi-Fi SSID/password, `MQTT_HOST` (delta2's reachable LAN IP), `MQTT_PORT` (from delta2 `.env`), `MQTT_PASSWORD` (the `.env` **`MQTT_DEVICE_PASSWORD`**), and `OTA_PASSWORD` (12+ chars, distinct from MQTT credentials). **Never publish or commit the resulting `secrets.h`.**
6. Wire the EEPROM. Open `PedalC6/PedalC6.ino` and flash over USB-C. Initial serial output should show `[journal] recovered seq=0` and then a Wi-Fi connection. Verify MQTT ACKs when pedals spin.
7. Before the real ESP starts publishing as `bike-001`, **remove the previous simulator data**, described below. Do not run the simulator and real ESP as `bike-001` together.

Why no `platformio.ini`? Official PlatformIO's Arduino framework for ESP32-C6 has historically lagged; Arduino IDE's upstream Espressif core 3.x directly supports it. We can add a pioarduino configuration after first hardware compilation if you prefer VS Code.

## Server-side prerequisites

Your delta2 Compose stack is already using the v1 protocol. Firmware publishes to
`pedal/v1/bike-001/events` with `v`, `device_id`, `boot_id`, `batch_id`, `lifetime_revs`, and `events`; each event has a permanent `seq`, `uptime_ms`, and `t_ms` if wall clock is known. It listens on `pedal/v1/bike-001/ack` and marks EEPROM records acknowledged **only after the server's application ACK**. A broker-level QoS 1 PUBACK is not sufficient.

**IMPORTANT — fake simulator's existing 40 revolutions:** those 40 records occupy sequence IDs 1–40 under `bike-001`, so the real device starting at seq=1 would appear to be sending duplicates. Once done simulating and **before** real-device use, delete only the fake device's records using the optional server v0.2 cleanup procedure, or provision a new device ID and Mosquitto ACL. Keep `.env` and Docker volumes intact. Never use `docker compose down -v` for this.

## Reliability, intentionally honest version

- EEPROM has **1024 record slots × 32 bytes**. At 60 RPM, that provides approximately **17 minutes of unsent raw event storage**, not hours. When full during a long network outage, the oldest unacknowledged slot is overwritten to keep the **lifetime sequence** moving. That lost raw history cannot be recovered. Network-connected operation drains the queue continuously; next upgrade can add flash spillover/FRAM for longer outages.
- An EEPROM record has a CRC-32, boot token, permanent 64-bit sequence, uptime, optional epoch timestamp, and a separate mutable ACK byte. New writes are verified by reading back. An interrupted write is ignored on reboot; the previous valid sequence survives. ACK writes do not modify the CRC-covered record data. This protects against most torn writes, not arbitrary hardware corruption.
- Captures are journaled in the main loop, **not inside the interrupt**. There is an additional 64-pulse RAM queue for temporary I²C stalls. A power cut before an accepted pulse is committed to EEPROM can still lose that pulse. There is no backup power or supercapacitor yet.
- An event recorded before NTP sync is reconstructed from uptime **only if still in the same boot** when sent. An offline event recovered after reboot without an epoch gets server receipt time flagged as approximate. We do not invent historical timestamps.
- Sensor capture pauses during the brief cold-boot EEPROM scan. Very long blocking Wi-Fi/OTA operations could fill the 256-edge interrupt queue; the serial diagnostics report dropped edges and RAM overflow explicitly.
- Password-protected ArduinoOTA is for a trusted LAN, not an internet-accessible firmware-update service. MQTT here is plaintext because the existing broker is configured on port 1883 inside Docker and published on an unusual host port; protect that port at the network firewall and keep credentials private.

## Testing the journal without the board

From the firmware directory (Linux/macOS host with g++):

```sh
./tests/run.sh
```

The tests check EEPROM scanning, persisted sequence continuity, ACKing, restart recovery, 1024-slot circular wraparound, and offline overflow.

## Useful serial output

Every 30 seconds a status line prints:

- `seq`: lifetime validated revolutions safely written to EEPROM
- `pending`: journal events awaiting backend ACK
- `rawPCNT`: **raw** falling edges since the last status print, includes possible switch bounce
- `accepted`: debounced events since boot
- `tooFast`: rejected events with implausibly short periods
- `edgeDrops`: interrupt queue overflows
- `ramDrops`: accepted events dropped before EEPROM (should ALWAYS remain zero)
- `queueOverwrites`: unacknowledged records lost because the 32 KB queue filled

**Do not seal the housing with hot glue until sensor, I²C, MQTT and USB recovery all pass bench tests.** 😄
