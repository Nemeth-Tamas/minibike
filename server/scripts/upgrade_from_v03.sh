#!/usr/bin/env bash
# PEDAL v0.4 upgrade. Existing Docker Compose, .env, Mosquitto and volumes untouched.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/pedal/pedal-telemetry}"

for file in backend/app/game.py backend/app/features.py backend/app/store.py backend/app/main.py \
            backend/static/forge-ui.js backend/static/app.js backend/static/index.html \
            backend/static/styles.css; do
  if [[ ! -f "$SRC/$file" ]]; then
    echo "Release is missing $file" >&2; exit 1
  fi
done
if [[ ! -f "$DEST/.env" || ! -f "$DEST/compose.yaml" || ! -d "$DEST/backend" ]]; then
  echo "Existing PEDAL installation not found at $DEST" >&2; exit 1
fi
if [[ "$SRC" == "$(cd "$DEST" && pwd)" ]]; then
  echo 'Source and destination may not be identical.' >&2; exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DEST/upgrade-backups/pre-v04-$STAMP"
mkdir -p "$BACKUP"
echo "[1/5] Backing up the current backend into $BACKUP"
cp -a "$DEST/backend" "$BACKUP/backend"

cd "$DEST"
echo '[2/5] Creating an online, consistent SQLite backup from the live container'
docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3, sys
stamp = sys.argv[1]
source = sqlite3.connect('/data/pedals.sqlite3')
backup = sqlite3.connect(f'/data/pedals-pre-v04-{stamp}.sqlite3')
source.backup(backup)
backup.close()
source.close()
print('SQLite snapshot completed.')
PY
docker compose cp "backend:/data/pedals-pre-v04-$STAMP.sqlite3" "$BACKUP/pedals.sqlite3"

echo '[3/5] Copying v0.4 application and UI files only'
for file in backend/app/game.py backend/app/features.py backend/app/store.py backend/app/main.py \
            backend/static/forge-ui.js backend/static/app.js backend/static/index.html \
            backend/static/styles.css; do
  cp -v "$SRC/$file" "$DEST/$file"
done

echo '[4/5] Rebuilding and recreating only the backend container'
docker compose up -d --build --no-deps backend

echo '[5/5] Waiting for HTTP health and showing service status'
WEB_PORT="$(awk -F= '$1=="WEB_PORT" {print $2}' .env | tail -1 | tr -d '\r')"
if [[ ! "$WEB_PORT" =~ ^[0-9]+$ ]]; then
  echo 'Could not read numeric WEB_PORT from existing .env' >&2; exit 1
fi
curl --retry 15 --retry-connrefused --retry-delay 2 --connect-timeout 3 \
  -fsS "http://127.0.0.1:$WEB_PORT/health"
printf '\n'
docker compose ps
printf '\nPEDAL v0.4 files installed; backup at: %s\n' "$BACKUP"
printf 'Dashboard: http://<delta2-LAN-IP>:%s/\n' "$WEB_PORT"
printf 'No Docker networks, credentials, ESP32 firmware, or volumes were modified.\n'
