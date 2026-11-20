# PEDAL v0.5 — GEARBOUND combat RPG and real-time cycling telemetry

**Latest upgrade:** `UPGRADE-v0.5.md`, for existing v0.4 installations. Source is canonical at https://github.com/Nemeth-Tamas/minibike.

## GEARBOUND features

- 20 workshop upgrades covering Torque production, offensive gear, defense, and scavenging.
- 33 skill nodes across 6 visible branches, bought with actual pedaling-earned skill points.
- 5 encounters per sector (4 mechanical enemies + boss), with enemy health, your hull, critical hits, cadence combos, combat log, and tactical stances.
- A second currency, Scrap, is earned by defeating enemies; boss relics buy 4 permanent research traits.
- Prestige carries over cores, relics and permanent research, while resetting only the run economy and enemies. Real exercise data is untouched.
- No click-to-earn or AFK income. Neither the player nor enemy advances without new live sensor pulses.

See `../docs/GAME_DESIGN.md` for detailed formulas and balance assumptions.

---

# PEDAL v0.4 — Forge Incremental Game + 40 Visible Achievements

**Compatible with deployed v0.3:** no ESP32-C6 firmware change, MQTT topic/protocol change, password change, new port, new Docker service or host networking. Your existing event telemetry system is preserved. Use `UPGRADE-v0.4.md` for a copy/paste-safe upgrade on delta2.

## The game

The **PEDAL FORGE** section in the existing dashboard is a real incremental game whose only source of currency is a newly committed revolution from the sensor. Every revolution produces Torque, which can be spent on six upgradable production components. Upgrades affect **future** revolutions. There is no click-to-earn, passive income, or automatically generated resource.

The **skill tree** offers Power, Momentum and Engineering branches, each with three skills, level caps, prerequisites and effects. Ride 150 revolutions per skill point per run. Momentum skills pay extra for valid sustained pedaling; delayed offline events do not build a live combo. Skills are not purchased with Torque, so you must physically pedal to advance both economies.

After 2,000 revolutions in a game run, you may **prestige**. It resets the game wallet, run counters, workshop upgrades and tree progress, awarding one permanent core per 2,000 run revolutions (maximum 20 cores in one prestige). Each permanent core adds +10% of base yield to all future revolutions, with a precise fractional accumulator, so early levels still benefit. Prestige never modifies raw MQTT events, the real bike lifetime, day/session summaries, user preferences or historical achievements.

### Upgrade shop

| Item | Effect per level | Initial Torque price |
|---|---|---:|
| Chain Drive | +1 base Torque/rev | 15 |
| Flywheel | +5 base Torque/rev | 220 |
| Alternator | +35 base Torque/rev | 2,000 |
| Variable Gearbox | +25% yield | 6,000 |
| Flux Capacitor | +160 base Torque/rev | 35,000 |
| Quantum Crank | +750 base Torque/rev | 250,000 |

Each subsequent level costs more. Engineering skills can discount shop prices. Every upgrade/skill has a bounded level cap.

## Achievements

**40 public achievements, zero secrets.** All names and thresholds are visible in the gallery. Tier labels (Bronze, Silver, Gold and Diamond), progress meters, and All/Unlocked/Locked filters help organize them. The original ten IDs are retained, and existing lifetime/day/session/streak metrics backfill new milestones when v0.4 starts. Some new achievements (sustained 60 RPM and moving-time totals) depend on sampled metrics collected after prior migrations; they are not invented retrospectively.

## Implementation and reliability

- `backend/app/game.py`: authoritative SQLite economy, upgrade price curves, skill prerequisites, prestige transaction.
- `backend/app/store.py`: exactly-once game event hook only when the existing `(device_id, seq)` insert succeeds, in the **same transaction** as telemetry and MQTT application ACKs.
- `backend/app/features.py`: new continuous 60+ RPM metric for Cruise Control; existing cadence challenge, goals, records, heatmap, workouts and HA integration remain.
- `backend/static/forge-ui.js`: active game, shop, skill-tree and prestige interface. Authenticated GET/POST only; server validates purchase requests. Game refreshes only a small state object, not lifetime events.
- `backend/static/index.html` and `styles.css`: responsive game panel integrated with the existing v0.3 dashboard.
- `tests/test_forge.py`, `tests/test_forge_api.py`: gameplay, auth and migration tests in addition to existing tests.

### Development verification

```bash
python -m pip install fastapi httpx pytest
pytest -q
node --check backend/static/app.js
node --check backend/static/forge-ui.js
node --check backend/static/feature-ui.js
bash -n scripts/upgrade_from_v03.sh
```

A browser-based screenshot check was attempted but blocked in the build environment, so the visual experience still needs verification in Firefox after deployment. No Docker instance is available here; the first live deployment on delta2 is the integration check.

## Future game modules

The event hook and game tables are separated from telemetric history, allowing later additions such as factories, world maps, multiple production resources, boss encounters or challenge-specific upgrades without touching the ESP32's firmware or MQTT envelope. Only new committed revolutions award resources.
