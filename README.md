# PEDAL — DIY exercise-bike telemetry and pedal-powered incremental game

An ESP32-C6 SuperMini counts a real normally-open reed switch, preserves events in AT24C256 EEPROM, and sends them via authenticated MQTT to a Docker Compose server on Ubuntu. SQLite stores individual revolutions and bounded aggregates; a live web dashboard supplies cadence, sessions, goals, achievements, fitness analytics and the **GEARBOUND** combat-incremental RPG with a persisted GAME ON/OFF switch and no involuntary deaths/resets (pedal instead of clicking).

## Source layout

- [`firmware/`](firmware/) — ESP32-C6 PlatformIO project v0.3.1, sensor probe, journal, software debounce, MQTT ACK/retry, OTA, and tests.
- [`server/`](server/) — Complete v0.5 GEARBOUND Docker Compose project: FastAPI + Mosquitto + SQLite, dashboard, gameplay engine, Windows overlay, tests, upgrade scripts.
- [`docs/HANDOVER.md`](docs/HANDOVER.md) — Canonical project context for continuing in a new conversation.
- [`docs/HARDWARE.md`](docs/HARDWARE.md) — Wiring, electronics, field-test results and commissioning notes.
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — Ubuntu deployment, backup, verification, safe updates, and developer commands.
- [`docs/HISTORY.md`](docs/HISTORY.md) — Changes, known limitations, and roadmap.

## Running system and release status

- Ubuntu host: **delta2**, Compose directory `~/pedal/pedal-telemetry`, using Docker **bridge** networking, never `network_mode: host`.
- At last report: web dashboard on port **30926**, MQTT on **45197** (these are instance-specific, set via `.env`); both Docker published to `0.0.0.0` on the host, so use firewall controls.
- **Server v0.3** was last *visibly verified live* on 2026-11-20; **server v0.5 GEARBOUND** is source-complete and locally tested; neither v0.4 nor v0.5 deployment on delta2 is independently confirmed. Do not assume it is already deployed.
- ESP32-C6 firmware is active and reporting real sensor revolutions. The firmware package here reflects the PlatformIO USB configuration fix and 30 ms dry-contact debounce.

## Source control safety

This is a **public** repository. Never add `server/.env`, the Mosquitto password database, `firmware/include/secrets.h`, HA webhook URLs/IDs, Wi-Fi passwords, OTA passwords, or SQLite activity files. Example files intentionally contain placeholders only. This repo preserves **source code and handover documents**, not delta2's live Docker volumes or personal ride history. Back up the SQLite volume separately; see [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

See the component READMEs, `server/UPGRADE-v0.4.md`, and `server/UPGRADE-v0.5.md` for the complete instructions. Future changes should read current GitHub files before editing, update handover docs/tests, and push commits to `master`.
