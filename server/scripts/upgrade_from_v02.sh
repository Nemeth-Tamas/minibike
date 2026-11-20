#!/usr/bin/env bash
# PEDAL v0.3 SAFE UPGRADE — no changes to compose.yaml, .env, ports or volumes.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HOME/pedal/pedal-telemetry}"

if [[ ! -f "$SRC/backend/app/features.py" || ! -f "$SRC/backend/static/feature-ui.js" ]]; then
  echo 'Missing v0.3 files in the extracted release.' >&2; exit 1
fi
if [[ ! -f "$DEST/.env" || ! -f "$DEST/compose.yaml" ]]; then
  echo "Cannot find existing PEDAL installation at: $DEST" >&2; exit 1
fi
if [[ "$SRC" == "$(cd "$DEST" && pwd)" ]]; then
  echo 'Refusing to upgrade in place from the release folder.' >&2; exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DEST/upgrade-backups/pre-v03-$STAMP"
mkdir -p "$BACKUP"
echo "[1/5] Backing up current backend to $BACKUP"
cp -a "$DEST/backend" "$BACKUP/backend"

cd "$DEST"
echo '[2/5] Taking consistent live SQLite snapshot (volumes stay mounted)'
docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3, sys
stamp=sys.argv[1]
src=sqlite3.connect('/data/pedals.sqlite3')
dst=sqlite3.connect(f'/data/pedals-pre-v03-{stamp}.sqlite3')
src.backup(dst)
dst.close();src.close()
print('SQLite backup created.')
PY
docker compose cp "backend:/data/pedals-pre-v03-$STAMP.sqlite3" "$BACKUP/pedals.sqlite3"

# Explicit whitelist. Do not copy the release's compose.yaml, .env or Mosquitto config.
echo '[3/5] Installing v0.3 code only'
for file in backend/app/main.py backend/app/store.py backend/app/features.py \
            backend/static/index.html backend/static/app.js backend/static/styles.css \
            backend/static/feature-ui.js backend/requirements.txt; do
  cp -v "$SRC/$file" "$DEST/$file"
done

echo '[4/5] Rebuilding only PEDAL backend'
docker compose up -d --build --no-deps backend

echo '[5/5] Testing health endpoint'
WEB_PORT="$(grep '^WEB_PORT=' .env | tail -1 | cut -d= -f2)"
if [[ -z "$WEB_PORT" ]]; then echo 'WEB_PORT missing from .env; check docker compose ps.' >&2; exit 1; fi
curl --retry 12 --retry-connrefused --retry-delay 2 --connect-timeout 3 \
     -fsS "http://127.0.0.1:$WEB_PORT/health"
printf '\n'
docker compose ps
printf '\nUpgrade completed. Backup: %s\n' "$BACKUP"
printf 'Dashboard: http://<delta2-LAN-IP>:%s/\n' "$WEB_PORT"
