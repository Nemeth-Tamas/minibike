# PEDAL project handover — 2026-11-20

**Canonical upstream:** https://github.com/Nemeth-Tamas/minibike (`master`). The conversation and earlier generated ZIPs are not the source of truth once this repo is established. Always inspect exact current files before editing. Commit and push changes, update this handover and tests.

## Goal

Replace the under-desk mini-bike's terrible 9,999-revolution-resetting LCD with reliable ESP32-C6 telemetry, lifetime per-revolution history on Ubuntu Docker Compose and a responsive desktop UI. Extend with gamified fitness challenges, a pedal-only incremental combat RPG, a growing skill tree and prestige. No hidden achievements: all milestones visible.

## Physical setup and firmware

ESP32-C6 SuperMini USB-C, AT24C256 32 KiB EEPROM over GPIO0 SDA/GPIO1 SCL, normally-open reed switch GPIO2→GND with **external 4.7 kΩ 3.3 V pull-up**. Internal pull-up OFF. Nonblocking 30 ms stable closed/open software debounce, 180 ms minimum accepted interval. 4MB flash, PlatformIO + pioarduino; firmware has Wifi, MQTT, OTA. Original LCD disconnected. Real hardware/sensor/EEPROM I2C and live MQTT ingestion worked on Nov 19; later a loose ground solder joint was repaired and more hot glue applied. See HARDWARE.md.

## Server

Ubuntu host **delta2**, checkout/runtime path `~/pedal/pedal-telemetry`, Docker Compose **bridge** networking (not host mode), live dashboard `http://192.168.1.21:30926`, MQTT broker port `45197`, intentional `BIND_IP=0.0.0.0` with access restricted outside Compose. Backend FastAPI Python + SQLite persistent volume + Mosquitto MQTT; simulator profile for bench testing; MQTT device `bike-001`. Credentials are in live `.env` (NOT in Git). Server v0.3 last directly demonstrated; v0.4 has been built and tested but is not yet known to be live.

## Gameplay and metrics

v0.3: live RPM waveform, goals, 365d heatmap, analytics, session comparisons, achievements, daily streaks, RPG XP, time-trial challenge (e.g. 45 RPM for 15 s), virtual adventure and PowerShell overlay. v0.4 adds exactly-once Torque per real committed pulse, six upgrades, 9 skill tree nodes (Power/Momentum/Engineering), skill point per 150 rev per game run, prestige unlock after 2,000 run rev, permanent cores (+10% each) with fractional carry, and **40 public achievements** with tiers. No click-to-earn and no idle income. Game starts new economy; existing real riding history remains and can backfill fitness achievements. Prestige never deletes physical history. **v0.5 GEARBOUND** adds 20 shop upgrades, 33 skill nodes, four currencies/resources (Torque, Scrap, Relics, prestige cores), 5-wave sectors with mechanical enemies/bosses, pedal-powered combat, 3 tactical stances and 4 persistent relic-research investments. No idle enemy attacks or click-to-earn. No hidden achievements. Only new live MQTT events advance fights; delayed replay events still earn Torque. New state tables are additive and existing v0.4 saves migrate.

## Last seen real activity

Screenshot from morning Nov 20 showed 5,263 lifetime rev, 2,981 rev that day, 7 sessions, 6/10 original v0.3 achievements, fastest sampled 135.1 RPM, ~47.8 minutes *measured* moving time (older data lacks that metric), best session 2,021 rev, longest session ~30m09s, 2-day streak. These were historical snapshots, **not current live values**.

## Files to use

- `server/`: self-contained v0.5 server source and tests. Upgrade from v0.4 using `server/UPGRADE-v0.5.md` and `server/scripts/upgrade_from_v04.sh`; if v0.4 was not deployed, upgrade through v0.4 first.
- `firmware/`: v0.3.1 PlatformIO sources, `platformio.ini`, secrets template, host tests and sensor probe.
- `docs/OPERATIONS.md`: backup/deploy/validate, exact commands, protective warnings.
- `docs/HARDWARE.md`: schematic/wiring and verified bench details.
- `docs/HISTORY.md`: version history and outstanding work.
- `docs/GAME_DESIGN.md`: GEARBOUND mechanics, progression economy, boss encounters and planned balancing.

## What must never be committed

Real `server/.env`, `firmware/include/secrets.h`, Mosquitto password database, any actual HA webhook URL/ID, runtime SQLite databases or backups. These files are intentionally not in this source repository. A fresh clone requires generating/inserting credentials; don't assume GitHub can reproduce real user activity without an independent SQLite backup.

## Next collaboration

1. `git pull` and inspect current upstream code; compare with any manual edits on delta2 (e.g. earlier Uvicorn hotfix) before deployment.
2. Determine whether delta2 is currently running v0.3 or v0.4; v0.4 deployment has not been independently confirmed. Apply v0.4 first if necessary, then v0.5. Preserve all named volumes and ports.
3. Test GEARBOUND combat, purchasing, relic research and prestige using real new pulses, confirm exactly-once after disconnect/replay.
4. Harden recovery and optional HA integration. Keep docs/tests updated and commit/push to master.

If user asks about the project in a new chat, read this handover **and current GitHub files** first. Never reconstruct source from memory or invent latest edits.

## Last development milestone (2026-11-20)

GEARBOUND v0.5 authored and verified locally: expanded combat loop, enemy sectors and bosses, tactical modes, 20 upgrades, 33 skill nodes, 4 permanent relic traits, new authenticated routes and mobile-responsive HUD. No firmware changes. A browser rendered in headless Chromium at desktop/mobile widths with no JS errors or overflow; 51 tests passed before final packaging (see test suite for latest count). Production deployment on delta2 was **not** performed from ChatGPT. Always check GitHub commit and current server before deployment.
