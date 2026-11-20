#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
  echo '.env already exists; refusing to rotate credentials or ports.'
  exit 1
fi
command -v docker >/dev/null || { echo 'Docker is required to initialize Mosquitto credentials.'; exit 1; }
python3 - <<'PY'
import secrets, socket
from pathlib import Path

def available_port():
    for _ in range(1000):
        n = secrets.randbelow(40000) + 20000
        with socket.socket() as s:
            try: s.bind(('0.0.0.0', n))
            except OSError: continue
            return n
    raise RuntimeError('Cannot find an unused port')

mqtt = available_port()
web = available_port()
while mqtt == web: web = available_port()
with Path('.env').open('w') as f:
    for k,v in {
       'BIND_IP':'0.0.0.0',
       'MQTT_PORT':str(mqtt), 'WEB_PORT':str(web),
       'DEVICE_ID':'bike-001', 'DASHBOARD_USER':'admin',
       'DASHBOARD_PASSWORD':secrets.token_urlsafe(24),
       'SESSION_SECRET':secrets.token_hex(32),
       'MQTT_BACKEND_PASSWORD':secrets.token_urlsafe(24),
       'MQTT_DEVICE_PASSWORD':secrets.token_urlsafe(24),
       'COOKIE_SECURE':'false',
    }.items(): f.write(f'{k}={v}\n')
Path('.env').chmod(0o600)
PY
set -a
# shellcheck disable=SC1091
source .env
set +a
mkdir -p mosquitto/config
# One-off utility container, not host networking. Hashed password file only.
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/mosquitto/config:/work" eclipse-mosquitto:2 \
  mosquitto_passwd -b -c /work/passwords bike "$MQTT_DEVICE_PASSWORD"
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/mosquitto/config:/work" eclipse-mosquitto:2 \
  mosquitto_passwd -b /work/passwords backend "$MQTT_BACKEND_PASSWORD"
chmod 644 mosquitto/config/passwords
printf '\nReady! Web port: %s; MQTT port: %s\n' "$WEB_PORT" "$MQTT_PORT"
echo 'Recommended: edit BIND_IP in .env to the server LAN/VPN IP before starting.'
echo 'Run: docker compose up -d --build'
echo 'Credentials: inspect .env (chmod 600). Never commit it.'
