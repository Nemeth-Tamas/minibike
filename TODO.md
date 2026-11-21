# PEDAL development TODO (as of v0.5 GEARBOUND)

## Deployment
- [ ] Verify whether delta2 runs v0.3 or v0.4. Upgrade to v0.4 first if needed.
- [ ] Deploy v0.5 safely, preserving .env, compose.yaml, MQTT/SQLite volumes, and the existing published ports.
- [ ] Perform a real-bike 30–50 revolution fight, reconnect test, boss/Relic test and gameplay persistence check.
- [ ] Test native Windows overlay still works alongside the new dashboard.

## Game tuning
- [ ] Get real play feedback from 1K, 5K and 20K run revolutions. Rebalance health/loot and prices accordingly.
- [ ] Add visible multi-target world map, enemy archetype artwork and telegraphed safe boss patterns.
- [ ] Consider new equipment and actual loot rarity; keep physical pedaling as the sole attack source.
- [ ] Add persistent history/chart of enemy victories and fastest boss defeats.

## Engineering
- [ ] Confirm Docker build and migration against live v0.4 database snapshot on delta2.
- [ ] Add cross-version upgrade integration test using exported (sanitized) production SQLite data.
- [ ] Revisit plaintext MQTT/HTTP access controls before exposing outside trusted LAN/VPN.


## v0.5.1 safety rules (implemented in source; deployment pending)
- [x] Server-persisted GAME ON/OFF control; OFF is fitness-only and never interferes with raw event recording, sessions, achievements or goals.
- [x] No involuntary combat resets: emergency shield floors hull at 1 HP and preserves damage already dealt to the enemy.
- [x] No game mutations while OFF; gameplay resumes only on explicit toggle and missed game progress isn't backfilled.
- [x] Preserve manual-only Prestige and separate real lifetime telemetry.
- [ ] Run the complete Python and browser integration test suite on v0.5.1 and confirm against delta2.
- [ ] Deploy v0.5.1 with consistent live SQLite backup.

## v0.6 game expansion
- [ ] Dedicated game view with live combat event streaming, telegraphed bosses, satisfying impacts and optional sounds.
- [ ] Loot equipment, rarity tiers, synergistic builds, visual world map and branching encounters.
- [ ] Every new mechanic must obey the OFF/freeze + no-death/no-involuntary-reset contracts.
- [ ] Tune at 5K/25K/100K/1M game revolutions, without requiring unsafe cadence.
