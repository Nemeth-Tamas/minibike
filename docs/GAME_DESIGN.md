# GEARBOUND v0.5: Game design, formulas, balance & safe expansion

## Core fantasy

The bike powers a mechanical fighter exploring the Cranklands. Every accepted **fresh, newly inserted** reed-switch revolution is an attack. This game has no clickable or idle resource generation. Clicking changes decisions (buy, learn, research, stance, prestige), not the physical source of progress. **Stopping the pedals pauses combat completely**, including enemy retaliation. This avoids punishing rests and prevents the game from pressuring unsafe speeds.

## Three meaningful economies

1. **Torque**: earned on every new committed revolution, even if transmitted after an outage (because it's a real recorded event). Spend on production/combat/defense/scavenging gear.
2. **Scrap**: earned on defeating enemies using fresh real-time revolutions. Early kills yield ~18–33 Scrap, bosses substantially more. Some upgrades cost both Torque and Scrap.
3. **Relics**: earned from sector bosses only. Permanent upgrades cost Relics and survive prestige. The base relic for defeating a boss is 1; higher sectors give additional relics.

Neither Scrap nor Relics can be minted by a REST endpoint. The device is protected by the existing MQTT credentials; a person who controls those credentials can still forge device data. This is a fitness game, not a certified anti-cheat platform.

## Combat loop

- **Sector**: five waves, four normal enemies plus one named boss. A victory automatically moves to the next wave; a boss victory unlocks the next sector. Bosses grant permanent Relics.
- **Every live sensor revolution**: award Torque, perform an automatic attack. New events older than 15 seconds still earn Torque but **do not fight**, keeping offline replays from racing through bosses.
- **Attack**: base 2 damage; armor on enemies reduces damage by at most to 1. Increasing steady cadence (starting from five consecutive ~45+ RPM sensor intervals) adds modest combo damage. Critical hits occur at predictable intervals (base every 13 attacks) to make progress readable. Fast pedaling is not required to win: slower riders can upgrade their weapons.
- **Enemy retaliation**: after every eight live attacks, the enemy retaliates if alive. It never attacks on a wall-clock timer; simply stepping away from the bike cannot hurt your character.
- **Hull loss**: v0.5 originally used an automatic workshop retreat. v0.5.1 replaced it with the emergency shield described below.
- **Victory**: earn Scrap, recover hull, keep the fight moving. The lightweight battle log retains the newest twenty events per device.
- **Stances**: Balanced = base damage/counterdamage; Assault = +50% outgoing and incoming; Guard = -20% outgoing and -35% incoming. Changing stance is allowed at any time and costs no currency.

## Upgrade economy and skill tree

- **20 workshop upgrades** in PRODUCTION / ARMORY / DEFENSE / SCAVENGING categories, with finite level caps, growing prices and explicit sector unlock requirements. The first six IDs and original costs from v0.4 remain compatible with saved progress.
- **33 visible skill nodes** across POWER, MOMENTUM, ENGINEERING, COMBAT, FORTITUDE, SALVAGE. Each earned skill point requires 150 game revolutions during the current run. Prerequisites and max levels are visible. The player cannot max all branches in one normal 2,000-revolution run (13 points).
- Four **permanent Relic Laboratory** traits: Reactor Core (Torque), War Engine (attack), Hardened Frame (hull), Relic Hunter (Scrap). They survive prestige and have growing costs.

## Example early-game pacing

At roughly 60 RPM, the first Rust Rat (55 hull, base 2 damage) needs about 27 accepted strikes, with deterministic crits speeding it up slightly. That is less than a minute at easy cadence. The rest of Sector 1 includes progressively stronger foes and a boss at 260 hull. A completely unupgraded starter can clear minions but should find the boss difficult, motivating a few early weapon/armor purchases. As you acquire damage and armor, sectors scale health ~42% per region (capped growth after Sector 25).

**Important:** This is a first-pass economy balance, not a proven multi-month progression model. Benchmarking and actual user play feedback are needed before treating the costs as final. We intentionally didn't backfill old exercise events as combat victories.

## Prestige safety

After 2,000 run revolutions, prestige awards 1 core per 2,000 revolutions (capped at 20 per prestige), adding +10% Torque yield per core with fractional carry. It resets: Torque, Scrap, the current sector, hero hull, enemy HP, shop levels, skill levels, and run counters. It **keeps**: Relic balance, permanent Relic Laboratory research, lifetime monster and boss defeats, permanent cores, and the complete independent exercise history, workout statistics and 40 visible achievements.

## Code layout / maintenance

- `server/backend/app/game.py`: game economy, combat and persistence; new tables created on startup through `store.initialize()`. All game updates happen inside SQLite write transactions.
- `server/backend/app/store.py`: the unchanged original device-event insert path is still the only pulse source of game currency and combat.
- `server/backend/app/main.py`: two new JSON-only authenticated endpoints for stance and permanent research, alongside existing game shop/skill/prestige endpoints.
- `server/backend/static/forge-ui.js`, `index.html`, `styles.css`: arena, battle feed, branch/category tabs, gear, relic lab and prestige.
- `server/tests/test_gearbound*.py`: balance, dedup, API and migration coverage.

## Future priorities

Add **world maps and enemy art**, encounter choices (without minting resources by clicking), drops/rarities, boss mechanics telegraphed over multiple safe pedal strokes, challenges that reward technique rather than speed, build presets and analytics for how enjoyable each boss feels. None should incentivize unsafe RPM or punish breaks. Simulate progression beyond 100K revolutions before further major economic changes.


## v0.5.1 — Player-controlled participation and no involuntary resets

- The server-persisted **GAME ON / GAME OFF** control is in the GEARBOUND header. Switching OFF is immediate for newly ingested events: real revolutions still populate SQLite, sessions, goals, achievement unlocks and fitness charts, but **no new Torque, skill progress, damage, Scrap, Relics or enemies** are generated. Missed game rewards are not backfilled when switching ON.
- Existing resources, equipment, enemy HP and sector are frozen while OFF. All game purchases and prestige are disabled until switching ON. A cadence combo is cleared when switching modes.
- **No death or forced retreats.** The emergency shield prevents hull falling below 1 HP. The enemy keeps its current damaged HP, and the sector, resources and inventory remain unchanged. Previously recorded retreat totals are retained only as historical statistics.
- **Prestige is the only run reset.** It requires an explicit confirmation and never touches exercise records. Game OFF persists across browser closure, backend restart and Docker redeployment.
- Fitness monitoring is never controlled by the RPG switch, even while the game is paused.

## v0.6 preview — Boss openings and ride contracts

- **Boss tells:** Six boss identities have distinct windups and stance responses. The arena shows a tell for five hits before the move resolves. Use the indicated stance on the resolving hit to open the boss's armor for the next six hits. The opening adds at least 3 damage per hit. Missing the response leaves the normal fight running.
- **Flywheel Burst:** Learn this Combat skill for one point. Every twelfth live hit adds at least 6 damage, with a larger bonus on powerful hits. The arena meter shows when the next burst will fire.
- **Ride contracts:** Start Steady Work for 60 live hits, Scrap Run for three wins, or Boss Bounty for a boss win. You can pause or switch contracts and keep progress. Rewards deposit on the qualifying event, and a finished contract can be selected again. Contract progress and completion history survive Prestige.
- **Save behavior:** The update adds two SQLite tables and leaves existing rows in place. An existing boss keeps its current hull and starts its first tell cycle on the next live hit. GAME OFF freezes tells, openings, bursts and contracts. Delayed or duplicate pulses cannot advance them. There are no wall-clock deadlines.
