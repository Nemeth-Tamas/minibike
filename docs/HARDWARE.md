# Hardware wiring and verified bench behavior

## Components

- Hestore ESP32-C6 SuperMini USB-C board (4 MB flash; C6 Wi-Fi 6). Board configuration uses `esp32-c6-devkitc-1` with explicit 4 MB override.
- Hestore AT24C256 I²C EEPROM module, 256 kbit = **32 KiB** (NOT 256 KB). Two scan replies observed at `0x50` and `0x58`; the firmware accesses **only `0x50`**. Check actual jumper silkscreen/schematic, never assume all jumper header pins are GND.
- Stock mini-bike magnetic **normally-open dry-contact reed switch**; confirmed OPEN → ~0Ω → OPEN per magnet pass. Old LCD disconnected and removed from the sensor circuit.
- A separate **external 4.7 kΩ pull-up**; internal MCU pull-up **disabled**.

| C6 | Connection |
|---|---|
| 3V3 | AT24C256 VCC and one end of the 4.7 kΩ resistor |
| GND | AT24C256 GND and one reed-switch wire |
| GPIO0 | AT24C256 SDA |
| GPIO1 | AT24C256 SCL |
| GPIO2 | Other reed wire and other end of 4.7 kΩ resistor |
| USB-C | 5 V phone charger for normal operation / Windows PC for USB programming |

A0, A1, A2 LOW for memory address `0x50`; WP LOW to allow writes. Verify jumper orientation with continuity mode when unpowered. Do not short 3V3 to GND. ESP32 IO is 3.3 V only.

## Debounce and sanity gates

`firmware/include/ReedDebouncer.h`: nonblocking **30 ms stable CLOSED**, **30 ms stable OPEN** before rearm, and **180 ms minimum** between accepted closures. `INPUT` rather than `INPUT_PULLUP`. The PCNT hardware count is used for raw transition diagnostics; the accepted events come from software validation. Single sensor cannot unambiguously distinguish a short reverse-rocking motion from a full revolution.

## Verified on 2026-11-19

- PlatformIO/pioarduino compiled and USB flashed after setting **both** `ARDUINO_USB_MODE=1` and `ARDUINO_USB_CDC_ON_BOOT=1` in `platformio.ini`.
- ESP32-C6 serial COM5 sometimes failed enumeration after pressing RESET; unplugging/replugging and opening monitor with `--rts 0 --dtr 0` worked. USB Serial/JTAG issue, not confirmed hardware failure.
- Wired reed switch test: 15 consecutive accepted revolutions with 2 transitions/rev and 0 bounce rejected after proper external pull-up was installed. Prior hundreds of transitions were from intentionally **floating** GPIO2 before wiring.
- I²C scan detected `0x50` and `0x58` consistently. A 16-byte marker at EEPROM 0x7FF0 was written and immediately read back successfully; **power-off retention of that marker was not independently confirmed in the chat**.
- Full production firmware sent real events to delta2; MQTT ACK logs showed `server committed 1 records, EEPROM marked 1` repeatedly, and dashboard displayed 84 RPM and unlocked First Spin.
- Mechanical installation used hot glue; a ground wire solder joint failed and was repaired. Monitor for loose connections and strain; do not let boards or wires touch the crank mechanism or conductive frame. Keep antenna and USB-C opening unobstructed.

**Safety:** Do not solder while USB power is attached. Secure wires far from rotating pedal/crank and resistance mechanism. Hot glue is strain relief, not a substitute for robust electrical insulation or mechanically sound solder joints.
