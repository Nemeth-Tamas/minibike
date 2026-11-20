# Release history, status and roadmap

## Versions

- **v0.1 server:** FastAPI + Mosquitto + SQLite + WebSockets + simulator; exactly-once (device, sequence) event inserts and ACK after commits. Initial deploy had a chmod bug in `scripts/init.sh` and missing `uvicorn[standard]` WebSocket extras, both subsequently fixed. First simulator test proved 40 accepted and 0 duplicates.
- **v0.2 server:** 10 visible milestones/achievements; existing 40 simulated revolutions originally unlocked First Spin. Test data was later cleared before commissioning the real bike.
- **v0.3 server:** rolling RPM graph, daily/weekly targets, virtual journeys, cadence challenges, analytics, 365-day heatmap, personal records, RPG XP/quests, Windows PowerShell always-on-top overlay and optional HA webhook integration (off unless configured); migration and tests passed. On 2026-11-20 user screenshots confirmed v0.3 dashboard operational, 5,263 lifetime revolutions, 2,981 that day, ~47.8 minutes sampled moving time, 135.1 sampled peak RPM. Earlier sessions correctly lacked new moving-time detail.
- **v0.4 server (source published here):** PEDAL FORGE pedal-only incremental game, Torque production from committed pulses, six workshop upgrades, nine skills across Power/Momentum/Engineering, prestige cores, fractional carry, and 40 visible achievements; tested in development. **Actual delta2 v0.4 deployment not yet verified.**
- **v0.1-v0.3.1 firmware:** ESP32-C6 PlatformIO, interrupt/PCNT diagnostics, 30 ms stable close/open reed debounce, 180 ms plausible interval limit, AT24C256 EEPROM circular journal, MQTT QoS1+application ACK/retry, Wi-Fi reconnect, OTA and 4MB flash config. v0.3.1 fixed the pioarduino USB mode flags. Full firmware verified on real hardware 2026-11-19.

## Event model and limits

- One physical magnet activation maps to a revolution when the reed closes cleanly. Back-and-forth rocking over the magnet is not distinguishable from full revolutions with one sensor.
- Firmware stores sequenced events and counters; MQTT QoS1 is not a substitute for backend ACK after durable commit; replay is safe using unique `(device_id, seq)`.
- EEPROM is **AT24C256 EEPROM, not FRAM**; firmware uses a wear-spread journal. Buffer capacity is finite. At ~60 RPM, reported capacity is around 17 minutes of unsent detailed events before offline overflow; total count can be preserved even when detail is lost. Confirm against current journal implementation.
- The C6 cannot record revolutions while unpowered or rebooting. NTP time may be unavailable during offline recording; timestamps for such events must be marked approximate rather than invented as exact.
- Charts/heatmaps use bounded aggregates rather than downloading every revolution. Differences of a couple of events between live totals and history may reflect refresh/binning delay; verify if persistent.
- No power sensor: distance, calories and virtual travel are **estimates**, not measured physics.
- Prestige resets only fictional game progress, never real pedaling events/history or earned exercise achievements.

## Suggested next steps

1. Confirm v0.4 actually deployed to delta2 and validate gameplay UI, purchases, skills and prestige with small real rides (back up first).
2. Sync any on-machine hotfixes that differ from this repository before overwriting production files.
3. Pin exact pioarduino dependency versions to avoid drifting Arduino-ESP32 changes.
4. Add a continuous integration workflow for pytest/JS syntax/native firmware tests.
5. Run a tested power-loss/EEPROM recovery scenario and a long offline-overflow soak test.
6. Improve physical strain relief for the EEPROM GND solder repair; secure housing and preserve USB recovery access.
7. Optionally connect achievement notifications to Home Assistant/Hermes Terminal, with a secret webhook configured outside Git.
