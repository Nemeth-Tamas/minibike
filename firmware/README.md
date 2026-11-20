# PEDAL. ESP32-C6 — PlatformIO edition (v0.3.1)

**VS Code + PlatformIO, no Arduino IDE required.** This version builds on v0.2 and changes sensor input handling only. MQTT payload and ACKs, EEPROM journal format, device ID, pins, and the existing delta2 backend protocol remain compatible.

### Changes from v0.3

- Fix ESP32-C6 serial compilation against newer pioarduino/Arduino-ESP32 4.0.0: set both `ARDUINO_USB_MODE=1` and `ARDUINO_USB_CDC_ON_BOOT=1` to select the hardware USB Serial/JTAG interface (`HWCDCSerial`), not unavailable native USB OTG (`USBSerial`). This is a build-only fix; no sensor wiring, MQTT protocol, or journal changes.

### Changes from v0.2

- **External 4.7 kΩ resistor required** between **3V3 and GPIO2**, with the dry reed switch wired from **GPIO2 to GND**. Both firmware environments now configure GPIO2 as `INPUT`, **not** `INPUT_PULLUP`.
- **30 ms software debounce** on *both* the CLOSED and OPEN states. Only a stable closure counts, and only a stable reopening re-arms the next count. Keeping the magnet parked on the sensor cannot create repeated revolutions.
- **180 ms minimum interval between accepted closures** remains a separate sanity gate (333 RPM theoretical upper bound).
- New reusable `include/ReedDebouncer.h`, used by main firmware *and* the standalone sensor probe. Live stats include raw input transitions, short glitch candidates, accepted revolutions and rejected too-fast closures.
- Host-side tests cover mechanical bounce, a 20-transition chatter burst, delayed event replay, minimum cadence interval, booting with the sensor closed, and `millis()` rollover. These tests are software simulations; **actual timing must be verified with the real sensor**.

> **Status:** Host-side EEPROM tests pass. The actual ESP32-C6 firmware has not been compiled/flashed or hardware-tested in this environment. Verify against the Hestore board on arrival and report compiler/upload errors before embedding it in the bike.

## Quick start on Windows (VS Code)

1. Install the **PlatformIO IDE** extension for VS Code (if not already installed).
2. Extract this ZIP; open the *root folder containing `platformio.ini`* using **File → Open Folder**.
3. Duplicate `include/secrets.h.example` as `include/secrets.h`. Fill in the Wi-Fi and MQTT/OTA credentials; **do not share or commit** this file.
4. Plug in the C6 SuperMini using a USB-C data cable. **Install the external 4.7 kΩ pull-up before testing the GPIO**; the input will float without it. In the PlatformIO sidebar, open **Project Tasks → sensor_probe → General → Upload**, and **Monitor** at 115200 baud.
5. With the original LCD **fully disconnected**, connect the confirmed passive dry-contact switch between GPIO2 and GND, and test the `sensor_probe` environment. Watch for **one `[REV]` per magnet pass** rather than raw bounce transitions. `bounceFiltered` and `rawTransitions` are printed every 5 seconds. No EEPROM or Wi-Fi needed for this step.
6. Wire the AT24C256, choose **Project Tasks → pedal_c6 → General → Upload**, then **Monitor**. The main firmware refuses to count until EEPROM is present.

**Important:** The `sensor_probe` and `pedal_c6` are separate upload targets. You can switch between them without moving files. PlatformIO downloads platform dependencies and libraries on first build.

### Build and upload from the terminal

Open a terminal where `pio` is available (VS Code's PlatformIO terminal or an activated PlatformIO environment):

```powershell
pio run -e sensor_probe
pio run -e sensor_probe -t upload
pio device monitor -b 115200

# After testing the switch and wiring EEPROM:
pio run -e pedal_c6
pio run -e pedal_c6 -t upload
pio device monitor -b 115200
```

If there are multiple serial devices, identify the port with `pio device list` and set an explicit upload port, e.g.:

```powershell
pio run -e pedal_c6 -t upload --upload-port COM7
```

If USB flashing doesn't start, hold **BOOT**, tap **RESET**, release BOOT and retry. On some USB-C boards you may need to disconnect/reconnect and reselect the COM port. Do not assume the serial monitor's old port remains valid after an ESP reboot.

## `platformio.ini` choices

- **pioarduino** `platform-espressif32` stable supports Espressif Arduino-ESP32 3.x on ESP32-C6. The ordinary `platform = espressif32` may offer only Arduino 2.x for this chip.
- `board = esp32-c6-devkitc-1` supplies the C6 toolchain; **override its 8 MB default to the SuperMini's 4 MB** via `board_build.flash_size` and `board_upload.flash_size`.
- `board_build.partitions = default.csv` selects a 4 MB Arduino layout with OTA partitions; don't use `huge_app.csv` if you want OTA slots.
- C6 hardware USB Serial/JTAG is selected with `ARDUINO_USB_MODE=1`, and USB CDC on boot is enabled with `ARDUINO_USB_CDC_ON_BOOT=1`; monitor at 115200 baud.
- ArduinoJson 7 and Joel Gaehwiler/256dpi MQTT 2.5.x are automatically resolved only for `pedal_c6` (the MQTT library supports QoS 1 publishing). Do not replace with PubSubClient without changing delivery semantics.
- This project uses the moving pioarduino `stable` release; after a successful first build, pin a specific release URL for reproducibility.

## Wiring — only after checking the sensor

**The original LCD's 1.6 V across the two wires did not prove a dry-contact reed switch.** Disconnect the LCD; confirm the sensor is voltage-free and switches between open and closed with a multimeter before hooking it up. Don't apply 3.3 V to an unidentified powered sensor.

| Component | ESP32-C6 SuperMini | Note |
|---|---|---|
| Reed switch | GPIO2 ↔ GND | Dry-contact reed (no polarity). One stable closure per pass |
| **External pull-up** | **3V3 — 4.7 kΩ — GPIO2** | **Required**; internal pull-up disabled (`INPUT`) |
| EEPROM VCC | 3V3 | The C6's IO isn't 5V tolerant |
| EEPROM GND | GND | Common ground |
| EEPROM SDA | GPIO0 | I²C 0x50, address pins LOW |
| EEPROM SCL | GPIO1 | 100 kHz |
| EEPROM WP | GND if exposed | Disable write protection |
| Power/programming | USB-C | PC or 5 V phone charger |

Wiring sketch (not to scale):

```text
ESP32-C6 3V3 ──[ 4.7 kΩ ]──┬── GPIO2 (INPUT)
                             │
                           [ reed ]
                             │
ESP32-C6 GND ────────────────┘
```

**Don't connect 3V3 straight to the switch**: the resistor is in series with the supply to the GPIO input node. No internal pull-up is enabled. Never leave the input floating when running the test. Keep the USB connector accessible and antenna away from metal. Check the particular C6 SuperMini pinout before installing it; do not use the boot or USB pins as arbitrary sensor GPIOs.

## Secrets

Edit `include/secrets.h`:

```cpp
#define WIFI_SSID "YOUR_2_4_GHZ_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define MQTT_HOST "192.168.1.21"  // delta2 LAN address
#define MQTT_PORT 45197          // current published MQTT port; see .env
#define MQTT_USERNAME "bike"
#define MQTT_PASSWORD "FROM_DELTA2_ENV"
#define OTA_PASSWORD "A_DISTINCT_LONG_PASSWORD"
```

On delta2 retrieve **only the relevant names/values locally**; don't paste credentials into chat:

```bash
cd ~/pedal/pedal-telemetry
grep -E '^(MQTT_PORT|MQTT_DEVICE_PASSWORD)=' .env
```

The ESP connects from Wi-Fi via delta2's **published MQTT port 45197**, *not* the private broker port 1883 or dashboard port 30926.

## Prevent mixing simulator and actual revolutions

The backend already has **40 simulator events** for `bike-001`, with sequence numbers 1–40 and the `First Spin` achievement. The real C6's blank EEPROM will start at sequence 1; if you publish without cleanup, events could be deduplicated or falsely merged. Keep the real ESP offline/MQTT disabled until you follow the v0.2 server's guarded fake-data cleanup instructions. Don't delete Docker volumes or `.env`.

## Reliability considerations (unchanged from v0.1)

- `src/main.cpp` + `include/ReedDebouncer.h`: GPIO CHANGE-edge capture and **30 ms software closure/reopen debounce**, C6 PCNT as **raw edge diagnostic only**, Wi-Fi, NTP, MQTT QoS 1, application ACK/retry, ArduinoOTA.
- `src/Journal.cpp`: AT24C256 EEPROM journal, 1024 × 32-byte records, CRC, readback verification, stable 64-bit sequence, recovery after restart. No EEPROM → main firmware doesn't start counting.
- At 60 RPM, approximately **17 minutes** of full unacknowledged event detail fit in 32 KB. After overflow, the highest sequence continues but old unsent raw events are lost.
- Uncommitted RAM pulses can be lost on a sudden power cut; MQTT is plaintext on a LAN port; and a single reed sensor can't distinguish partial back-and-forth rocking from a full revolution. 30 ms + 180 ms filters bounce and implausible cadence, **not intentional slow back-and-forth rocking**.
- Do not hot-glue the device shut until it passes cold reboot, Wi-Fi outage, EEPROM retry, USB recovery and OTA tests.

### OTA (later, after USB is verified)

The original firmware still starts password-protected ArduinoOTA (`OTA_PASSWORD` ≥ 12 characters). USB upload is the supported first-flash route. To add one-click PlatformIO network upload later, configure a *private* `espota` environment with the board's reachable IP and the password kept out of Git. Do not expose ArduinoOTA outside your trusted LAN.

## Test locally without a C6

On Linux/macOS, or Windows with g++ in WSL:

```bash
./tests/run.sh
```

These tests run an EEPROM simulator and a pure C++ sensor-filter simulator. They validate journal scanning, sequence continuity, ACKs, restart recovery, ring wraparound, overflow, rapid reed contact bounce, and debounce timing. The ESP32-C6 application still requires a real PlatformIO build and bench flash.
