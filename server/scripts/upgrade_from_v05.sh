#!/usr/bin/env bash
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/pedal/pedal-telemetry}"
FILES=(backend/app/game.py backend/app/main.py backend/static/forge-ui.js backend/static/index.html backend/static/styles.css)
for f in "${FILES[@]}"; do [[ -f "$SRC/$f" ]] || { echo "Missing $f" >&2; exit 1; }; done
[[ -f "$DEST/.env" && -f "$DEST/compose.yaml" && -f "$DEST/backend/app/game.py" ]] || {
 echo 'Existing v0.5 installation not found; install v0.5 first.' >&2; exit 1;
}
grep -q 'forge_combat' "$DEST/backend/app/game.py" || {
 echo 'v0.5 GEARBOUND is required before v0.5.1.' >&2; exit 1;
}
[[ "$SRC" != "$(cd "$DEST" && pwd)" ]] || { echo 'Source and live deployment must be different.' >&2; exit 1; }
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$DEST/upgrade-backups/pre-v051-$STAMP"
mkdir -p "$BACKUP"
cp -a "$DEST/backend" "$BACKUP/backend"
cd "$DEST"
docker compose exec -T backend python - "$STAMP" <<'PY'
import sqlite3,sys
stamp=sys.argv[1]
src=sqlite3.connect('/data/pedals.sqlite3')
dst=sqlite3.connect('/data/pedals-pre-v051-'+stamp+'.sqlite3')
try:
    src.backup(dst)
    print('Live SQLite snapshot created.')
finally:
    dst.close();src.close()
PY
docker compose cp "backend:/data/pedals-pre-v051-$STAMP.sqlite3" "$BACKUP/pedals.sqlite3"
for f in "${FILES[@]}"; do cp -v "$SRC/$f" "$DEST/$f"; done
docker compose up -d --build --no-deps backend
WEB_PORT="$(awk -F= '$1=="WEB_PORT" {print $2}' .env | tail -1 | tr -d '\r')"
[[ "$WEB_PORT" =~ ^[0-9]+$ ]] || { echo 'Cannot parse WEB_PORT' >&2; exit 1; }
curl --retry 15 --retry-connrefused --retry-delay 2 --connect-timeout 3 -fsS "http://127.0.0.1:$WEB_PORT/health"
printf '\nGame-mode/no-death update installed. Backup: %s\n' "$BACKUP"
docker compose ps
