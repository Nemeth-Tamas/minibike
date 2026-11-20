# PEDAL. server v0.2 — achievements update

A **drop-in server-only upgrade** to the existing Docker Compose project on `delta2`.

Adds 10 persisted achievements, automatic unlocks during durable MQTT ingestion, a protected achievements API, a new milestone gallery and an on-screen unlock toast. Existing WebSocket, MQTT, session, chart, data-volume and port behavior is unchanged. Also includes the `uvicorn[standard]` WebSocket dependency fix and the non-root Mosquitto initialization fix.

### SAFE upgrade on delta2, keeping all of your .env credentials, published random ports and Docker volumes

1. Extract this zip *outside* your running `~/pedal/pedal-telemetry` directory.
2. From the running project:

```bash
cd ~/pedal/pedal-telemetry
cp -a backend "backend.backup.$(date +%Y%m%d-%H%M%S)"
# Recommended: consistent live SQLite snapshot, then copy the snapshot to the host.
docker compose exec -T backend python -c 'import sqlite3; s=sqlite3.connect("/data/pedals.sqlite3"); t=sqlite3.connect("/data/pre-v02.sqlite3"); s.backup(t); t.close(); s.close()'
docker compose cp backend:/data/pre-v02.sqlite3 ./pedals-pre-v02.sqlite3
```

3. Copy **only** these files from the extracted `pedal-server-v0.2` folder into the corresponding paths in your running project:

```
backend/app/store.py
backend/app/main.py
backend/static/index.html
backend/static/app.js
backend/static/styles.css
backend/requirements.txt
```

4. Rebuild only the backend:

```bash
docker compose up -d --build backend
docker compose logs --tail=30 backend
curl -fsS http://127.0.0.1:30926/health
```

The database migrates by adding `achievements` table automatically; existing users' data is left alone. Existing simulator milestones are backfilled once on startup. CSS/JS may require Ctrl+Shift+R in Firefox if cached.

Check achievements:

`http://192.168.1.21:30926/` (while logged in); scroll to **MILESTONES**.

### When the actual C6 comes: remove ONLY the 40 simulator events

**Stop the simulator first. This deletes the fake `bike-001` data including achievements, so make sure no real pedaling events have been ingested yet.** Do NOT run if the bike is already transmitting.

The reset script deliberately refuses to operate unless it sees **exactly 40 records, seq 1–40**. Run from the *running project's root* after copying `scripts/clear_simulator_40.py` from this zip into its `scripts` folder:

```bash
docker compose cp scripts/clear_simulator_40.py backend:/tmp/clear_simulator_40.py
docker compose exec -T backend python /tmp/clear_simulator_40.py \
  --yes-delete-exactly-40-simulator-events
```

No Docker volumes, .env credentials, simulator state, or ports are removed. If you want to retain the simulated data for reference, choose a **different device ID and matching broker ACL** instead.

### Status

`pytest` tests validate achievements, backfill, existing API and ingestion. The running delta2 Docker environment is not accessible from this generation workspace, so perform and verify the upgrade there.
