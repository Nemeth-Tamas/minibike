#!/usr/bin/env bash
# PEDAL GEARBOUND v0.5: safe in-place upgrade from deployed v0.4.
# Only the backend code and UI are overwritten. No Docker volumes/ports/firmware.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/pedal/pedal-telemetry}"
FILES=(backend/app/game.py backend/app/main.py backend/static/forge-ui.js
       backend/static/index.html backend/static/styles.css)

for file in "${FILES[@]}"; do
  [[ -f "$SRC/$file" ]] || { echo "Missing update file: $SRC/$file" >&2; exit 1; }
done
[[ -f "$DEST/.env" && -f "$DEST/compose.yaml" && -f "$DEST/backend/app/game.py" ]] || {
  echo "Expected an existing v0.4 installation at $DEST (including app/game.py)." >&2
  echo "If you have v0.3, install v0.4 first. No files were modified." >&2
  exit 1
}
[[ "$SRC" != "$(cd "$DEST" && pwd)" ]] || {
  echo 'The source and destination directories cannot be identical.' >&2; exit 1;
}

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DEST/upgrade-backups/pre-v05-$STAMP"
mkdir -p "$BACKUP"
cp -a "$DEST/backend" "$BACKUP/backend"

cd "$DEST"
echo '[1/4] Creating a transactionally consistent SQLite snapshot...'
docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3, sys
stamp = sys.argv[1]
src = sqlite3.connect('/data/pedals.sqlite3')
dst = sqlite3.connect('/data/pedals-pre-v05-'+stamp+'.sqlite3')
try:
    src.backup(dst)
    print('SQLite backup complete.')
finally:
    dst.close()
    src.close()
PY
docker compose cp "backend:/data/pedals-pre-v05-$STAMP.sqlite3" "$BACKUP/pedals.sqlite3"

echo '[2/4] Installing five additive app/UI files...'
for file in "${FILES[@]}"; do cp -v "$SRC/$file" "$DEST/$file"; done

echo '[3/4] Rebuilding backend only (MQTT broker unaffected)...'
docker compose up -d --build --no-deps backend

echo '[4/4] Checking the original HTTP port...'
WEB_PORT="$(awk -F= '$1=="WEB_PORT" {print $2}' .env | tail -1 | tr -d '\r')"
[[ "$WEB_PORT" =~ ^[0-9]+$ ]] || { echo 'Cannot parse WEB_PORT from .env' >&2; exit 1; }
curl --retry 15 --retry-connrefused --retry-delay 2 --connect-timeout 3 \
  -fsS "http://127.0.0.1:$WEB_PORT/health"
printf '\n'
docker compose ps
printf '\nGEARBOUND v0.5 installed. Backup: %s\n' "$BACKUP"
printf 'Dashboard: http://<delta2-LAN-IP>:%s/\n' "$WEB_PORT"
printf 'Existing Docker bridge, published ports, volumes, MQTT and firmware preserved.\n'
