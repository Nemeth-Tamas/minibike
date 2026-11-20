# Upgrade PEDAL on delta2: v0.4 → v0.5 GEARBOUND

This is a **server/UI-only** update. The ESP32-C6, EEPROM journal, MQTT credentials, `.env`, `compose.yaml`, randomized ports (30926 web / 45197 MQTT on the last confirmed machine), and Docker bridge network do **not** change.

**Important:** Last directly verified live server was v0.3; v0.4 deployment has not been confirmed. Check `~/pedal/pedal-telemetry/backend/app/game.py` on delta2. If it doesn't exist, upgrade to v0.4 first using `server/UPGRADE-v0.4.md`. The v0.5 script checks this and refuses to overwrite a v0.3 installation.

## Deploy from the GitHub repository (preferred)

In Windows PowerShell, no files need to be copied by SCP, because GitHub is the source of truth. SSH into delta2:

```powershell
ssh notmikee@192.168.1.21
```

On Ubuntu:

```bash
cd ~/pedal
# Separate SOURCE checkout; do not clone on top of the live installation.
git clone https://github.com/Nemeth-Tamas/minibike.git minibike-source
cd ~/pedal/minibike-source
# Confirm the commit, then run the audited upgrade script.
git log -1 --oneline
bash server/scripts/upgrade_from_v04.sh
```

If the source checkout already exists, use `cd ~/pedal/minibike-source && git pull --ff-only` instead of cloning again. The script's default live deployment destination is `~/pedal/pedal-telemetry`. It copies **five** application/UI files. It backs up the backend directory and takes an online SQLite backup before any code replacement.

## Verify

```bash
cd ~/pedal/pedal-telemetry
docker compose ps
curl -fsS http://127.0.0.1:30926/health
docker compose logs --tail=50 backend
```

Open `http://192.168.1.21:30926` and press **Ctrl+Shift+R** in Firefox to invalidate cached JavaScript. The game should now show `GEARBOUND v0.5`, enemy HP, hero hull, wave/boss progress, Scrap, Relics, combat stances, four workshop tabs, six skill branches, and a permanent research laboratory.

**Live smoke test:** while the game is visible, pedal 25–35 revolutions. The Rust Rat should lose hull and eventually drop Scrap, then the next enemy should appear. If you stop pedaling, the enemy should not attack. Old MQTT retransmits should not alter combat, and any game currency should survive browser refresh and backend restart.

## Rollback (code only; never restore a stale SQLite snapshot over fresh exercise data)

```bash
cd ~/pedal/pedal-telemetry
BACKUP="$(ls -dt upgrade-backups/pre-v05-* | head -1)"
echo "Restoring $BACKUP"
cp -a "$BACKUP/backend/." ./backend/
docker compose up -d --build --no-deps backend
```

The new `forge_combat`, `forge_relic_traits` and `forge_battle_log` SQLite tables are **additive** and can remain dormant if you roll back only the code. No real workout data is deleted by this upgrade.

## Safe network boundaries

The existing public-interface bind `0.0.0.0` is unchanged, but HTTP dashboard credentials and MQTT are transmitted in plaintext unless separately protected. Restrict the published ports to a trusted LAN/VPN with firewall rules. Do not port-forward these services to the public internet.

## What was tested

Python tests cover authenticated new API routes, event deduplication, delayed events, starter combat, boss rewards, relic persistence, skill prerequisites, prestige behavior, and accidental no-op HTTP earn/attack endpoints. HTML and JavaScript were rendered in headless Chromium at 1440px and 390px with mocked server responses, with no page errors or horizontal overflow. **A live production Docker upgrade and real C6→MQTT→fight sequence have not been performed here.**
