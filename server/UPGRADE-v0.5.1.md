# PEDAL v0.5.1 — GAME ON/OFF + invulnerable safety shield

This is a **server-only**, additive upgrade from v0.5. Existing ESP32-C6 firmware, EEPROM, MQTT schema, `.env`, Docker Compose, ports and volumes remain unchanged.

## Install on delta2

```bash
cd ~/pedal/minibike-source
git pull --ff-only
bash server/scripts/upgrade_from_v05.sh
```

The script requires v0.5 code at `~/pedal/pedal-telemetry`, backs up the whole backend and a consistent online SQLite snapshot, then copies only application/UI files and restarts only the backend. Nothing is dropped from SQLite. No `docker compose down -v`.

## Expected behavior

- The GEARBOUND header shows **GAME ON** and **Pause game · OFF**. Clicking persists to SQLite. **GAME OFF · FITNESS ONLY** means real revolutions and health/fitness achievements continue while the whole game economy and combat are frozen.
- Game OFF is not a browser-only hide; closing the tab, logging out, or restarting Docker will not resume it.
- The shield prevents hull falling below 1; it never resets the enemy or imposes a forced retreat. No permadeath, no forced wipe. The only run reset is clicking and confirming Prestige.
- The mode switch does not back-pay game rewards for revolutions logged while OFF.

## Verify

```bash
cd ~/pedal/pedal-telemetry
docker compose ps
curl -fsS http://127.0.0.1:30926/health
docker compose logs --tail=40 backend
```

Hard-refresh Firefox with Ctrl+Shift+R. Use the GAME OFF toggle, pedal a few revolutions, and confirm the lifetime revolution count advances while Torque and enemy HP remain frozen. Resume game for a few pedal strokes and confirm they move again.

## Rollback

```bash
cd ~/pedal/pedal-telemetry
BACKUP="$(ls -dt upgrade-backups/pre-v051-* | head -1)"
cp -a "$BACKUP/backend/." ./backend/
docker compose up -d --build --no-deps backend
```

The additive forge_preferences table may remain in SQLite if older code is restored. **Never replace the live DB with an old snapshot** after recording new workouts.
