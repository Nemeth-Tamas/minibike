# Operations, development and recovery

## Deployed instance (last reported)

- Host: delta2, Ubuntu, LAN IP reported as `192.168.1.21`.
- Compose root: `~/pedal/pedal-telemetry`
- Dashboard: `http://192.168.1.21:30926/`; broker externally published at `192.168.1.21:45197`.
- `BIND_IP=0.0.0.0` was intentionally selected; **not** host networking. Restrict with firewall/VPN, particularly unencrypted MQTT.
- ESP32 device id: `bike-001`. Broker has separate device (`bike`) and backend credentials in local `.env`/password file.
- SQLite is in a persistent Docker named volume, not in this git repository.

## Safe backend checks

```bash
cd ~/pedal/pedal-telemetry
docker compose ps
curl -fsS http://127.0.0.1:30926/health
docker compose logs --tail=50 backend
```

Immediately after `docker compose restart`, the container may report started before the health endpoint is ready; retry once backend is healthy. `uvicorn[standard]` is needed for WebSocket support (plain uvicorn previously caused reconnect loops).

## Database backup (does not stop ingestion)

These commands use the SQLite live backup API. Confirm the database path matches the running version of `compose.yaml` if modified.

```bash
cd ~/pedal/pedal-telemetry
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T backend python -c 'import sqlite3; a=sqlite3.connect("/data/pedals.sqlite3"); b=sqlite3.connect("/data/manual-backup.sqlite3"); a.backup(b); b.close(); a.close()'
docker compose cp backend:/data/manual-backup.sqlite3 "./pedals-${STAMP}.sqlite3"
chmod 600 "./pedals-${STAMP}.sqlite3"
```

Store private database snapshots outside GitHub. Never `docker compose down -v` during an upgrade; that deletes the named volumes.

## Upgrading v0.3 → v0.4 on delta2

The **packaged v0.4 upgrade script** is in `server/scripts/upgrade_from_v03.sh` and expects the source directory named `pedal-server-v0.4` beneath its normal staging location. For GitHub checkouts, consult `server/UPGRADE-v0.4.md` and verify the script's `SRC` path **before running it**. Prefer a staged directory with that exact source layout:

```bash
cd ~/pedal
# Clone only if the repository is not already present on delta2
git clone https://github.com/Nemeth-Tamas/minibike.git minibike-source
mkdir -p pedal-v04-staging
cp -a minibike-source/server pedal-v04-staging/pedal-server-v0.4
# Inspect first. The script takes its own backup and preserves your .env and volumes.
sed -n '1,180p' pedal-v04-staging/pedal-server-v0.4/scripts/upgrade_from_v03.sh
bash pedal-v04-staging/pedal-server-v0.4/scripts/upgrade_from_v03.sh
```

**Do not run a v0.3→v0.4 upgrade if v0.4 is already installed**; inspect the dashboard and server files first. Do not overwrite your local `.env`, broker credentials or Docker data. The v0.4 package has not yet been confirmed as deployed on delta2 in the conversation.

## Firmware build and USB flash (Windows, VS Code + PlatformIO)

```powershell
cd firmware
Copy-Item include/secrets.h.example include/secrets.h
# Edit secrets.h with your local Wi-Fi/MQTT/OTA settings; never git-add it.
pio run -e sensor_probe
pio run -e pedal_c6
pio run -e pedal_c6 -t upload
pio device monitor -p COM5 -b 115200 --rts 0 --dtr 0 --filter time
```

Use `pio device list` to get the current COM port; COM5 is the port that was observed during commissioning, not guaranteed. For native journal/debounce tests, run `bash firmware/tests/run.sh` in an environment with a C++ compiler (see firmware README). Keep USB accessible even with OTA working; wireless update failure could otherwise lock out recovery.

### OTA

The firmware uses `ArduinoOTA` with a password from `include/secrets.h` on the trusted Wi-Fi network; PlatformIO `espota` can upload the same firmware. `upload_port` should be the C6's Wi-Fi IP, **not delta2's IP**; keep OTA closed to untrusted networks. Avoid pedaling during update/reboot since unpowered or rebooting MCU cannot count pulses.

## Tests

```bash
cd server
python -m pip install -r backend/requirements.txt pytest httpx
pytest -q
node --check backend/static/app.js
node --check backend/static/feature-ui.js
node --check backend/static/forge-ui.js
```

Latest v0.4 package was reported passing **40 server tests** during its development; retest after source modifications. The frontend had syntax checks but no verified browser screenshot test in the build environment.

## Security essentials

- `.env` contains dashboard and MQTT passwords/session secret; never commit or share it.
- `firmware/include/secrets.h` contains Wi-Fi, MQTT and OTA passwords; never commit or share it.
- Mosquitto password file, HA webhook secret URLs, SQLite activity database, logs and backups remain out of Git.
- If credentials have ever been committed, rotate them and remove sensitive history; a later deletion does not unpublish them automatically.
