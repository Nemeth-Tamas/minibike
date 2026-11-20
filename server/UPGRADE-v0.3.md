# PEDAL v0.3 — delta2 production upgrade

## What's retained

The live ESP32-C6 v0.3 firmware, MQTT topic schema, existing passwords, session cookies, Portainer/Docker volumes, **random host ports 30926 and 45197**, and the Docker **bridge** network are untouched. No `host` networking is introduced. No simulator cleanup or data deletion is performed.

## From Windows PowerShell

Download `pedal-server-v0.3-complete.zip` from ChatGPT to your **Downloads** folder. Upload it to delta2:

```powershell
scp "$HOME\Downloads\pedal-server-v0.3-complete.zip" notmikee@192.168.1.21:~/pedal/
ssh notmikee@192.168.1.21
```

## On Ubuntu delta2

```bash
cd ~/pedal
mkdir -p pedal-v03-staging
unzip -q -o pedal-server-v0.3-complete.zip -d pedal-v03-staging

# Read the release's upgrade script before running it if desired:
less pedal-v03-staging/pedal-server-v0.3/scripts/upgrade_from_v02.sh

# It creates a consistent SQLite snapshot and backs up all backend files.
bash pedal-v03-staging/pedal-server-v0.3/scripts/upgrade_from_v02.sh
```

The script checks that `~/pedal/pedal-telemetry/.env` and `compose.yaml` already exist, snapshots the SQLite DB into `~/pedal/pedal-telemetry/upgrade-backups/pre-v03-TIMESTAMP/pedals.sqlite3`, and preserves a complete copy of the previous `backend` tree in the same folder. Then it copies **only eight** backend, static and requirements files, rebuilds **only** `backend`, checks `/health` on the preexisting `WEB_PORT`, and prints Docker status. It does not touch `.env`, compose networking, ports, volumes, Mosquitto passwords or the bike.

**Manual alternative:** Instead of executing the script, back up SQLite with `sqlite3.Connection.backup()`, copy `backend/app/{main.py,store.py,features.py}`, `backend/static/{index.html,app.js,feature-ui.js,styles.css}` and `backend/requirements.txt`, and run `docker compose up -d --build --no-deps backend`. Remember to take a database backup first.

## Verify

```bash
cd ~/pedal/pedal-telemetry
docker compose ps
docker compose logs --tail=60 backend
curl -fsS http://127.0.0.1:30926/health
```

Open <http://192.168.1.21:30926/>, sign in as before, and press **Ctrl+Shift+R** in Firefox. Check that the v0.3 panels appear, live RPM updates, and the lifetime total did not reset. Configure your desired virtual distance scale in Settings. Start a simple 45 RPM / 15 sec challenge for the first run (no firmware flash required).

## Optional Windows always-on-top overlay

Run this **on Windows**, from the extracted ZIP folder. No VS Code, Python, or third-party GUI toolkit is needed, just Windows PowerShell 5.1 / .NET WinForms:

```powershell
powershell -ExecutionPolicy Bypass -File .\pedal-server-v0.3\overlay\PedalOverlay.ps1 -Server http://192.168.1.21:30926
```

Enter your **existing dashboard username/password** in the credential prompt. The overlay stays topmost, refreshes every 2 seconds and fetches RPG/goal info periodically. It does not store credentials on disk. Important: the dashboard currently serves **HTTP**, so only use this from a trusted LAN, or configure HTTPS.

## Rollback

The additive SQLite migration leaves existing event rows intact. If you need to return to the v0.2 backend, with the bike still connected:

1. Find the latest backup folder: `ls -dt ~/pedal/pedal-telemetry/upgrade-backups/pre-v03-* | head -1`
2. Run from `~/pedal/pedal-telemetry` (substitute your backup folder):

```bash
BACKUP="$(ls -dt ~/pedal/pedal-telemetry/upgrade-backups/pre-v03-* | head -1)"
cp -a "$BACKUP/backend/." ./backend/
docker compose up -d --build --no-deps backend
```

**Do not restore the old SQLite snapshot unless you specifically need a point-in-time disaster recovery.** Restoring it would erase any real revolutions recorded since the upgrade. The v0.2 software can ignore the extra v0.3 tables/columns. You may leave them in place.

## Limitations and honesty

- The new `moving_ms`, cadence distribution and peak RPM measurements begin at v0.3. Prior session totals and achievements are preserved, but past moving-time detail can't be reconstructed from the old aggregates alone.
- The short rolling cadence chart queries only the past five minutes of timestamped pulses; the 365-day activity grid uses daily aggregates. It does **not** download raw lifetime history.
- Distance is a *virtual estimate* based on an adjustable metres-per-revolution multiplier. Calories are opt-in and approximate, not power-based; no accurate cycling distance or wattage can be calculated from the reed switch alone.
- XP is derived from persisted lifetime revolutions, achievement count and challenge completions. It cannot duplicate on MQTT retries.
- Challenge rewards require live, timestamped events; after an outage, archived events remain counted in history but do not win a timed challenge retroactively.
- The Windows overlay is supplied but could not be executed in the Linux build environment. Verify it on Windows.
- The current project uses login cookies over HTTP for the trusted LAN. Do not publish this directly to the internet without HTTPS and access control.

## Optional Home Assistant webhook

If you want an announcement when a **new** achievement unlocks, follow [integrations/README.md](integrations/README.md) after the main upgrade. It adds an outbound-only webhook; no additional published ports are needed. It is disabled by default and does not need to be configured for the rest of v0.3 to work.
