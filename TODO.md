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
