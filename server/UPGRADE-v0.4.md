# Upgrade PEDAL on delta2: v0.3 → v0.4 (Forge)

This is a **server-only** update. Your ESP32-C6 firmware, external EEPROM, MQTT schema, existing `.env`, passwords, Docker Compose project/network, published ports and named volumes remain unchanged. The installation script copies only eight application/UI files and rebuilds `backend`.

## 1. Windows PowerShell (upload)

Download `pedal-server-v0.4-forge.zip` to your Downloads directory, then:

```powershell
scp "$HOME\Downloads\pedal-server-v0.4-forge.zip" notmikee@192.168.1.21:~/pedal/
ssh notmikee@192.168.1.21
```

## 2. Ubuntu delta2 (backup + upgrade)

```bash
cd ~/pedal
mkdir -p pedal-v04-staging
unzip -q -o pedal-server-v0.4-forge.zip -d pedal-v04-staging
bash ~/pedal/pedal-v04-staging/pedal-server-v0.4/scripts/upgrade_from_v03.sh
```

The script first creates `~/pedal/pedal-telemetry/upgrade-backups/pre-v04-DATE-TIME/`, copies the existing backend there and uses `sqlite3.Connection.backup()` to take an online SQLite snapshot. If the backup fails, the script will **not** overwrite application files. Then it copies the v0.4 backend/UI code, recreates the backend container and checks its existing HTTP health port.

## 3. Verify

```bash
cd ~/pedal/pedal-telemetry
docker compose ps
curl -fsS http://127.0.0.1:30926/health
docker compose logs --tail=60 backend
```

Open <http://192.168.1.21:30926/> in Firefox, sign in as before, and press **Ctrl+Shift+R**. The **PEDAL FORGE** section should appear after the live cockpit cards; the achievement gallery should show **40** public achievements, with All/Unlocked/Locked filters. Ride a few real revolutions and verify the Forge wallet starts increasing. This DOES NOT alter the workout lifetime count, which is separate from Forge credits.

If the game panel initially shows zero Torque but your lifetime revolutions are already 5,000+, that's **correct**: it starts accounting for game currency from the time of the v0.4 deployment rather than retroactively giving thousands of upgrade purchases. Existing lifetime achievements **are** backfilled.

## How to play

- Pedal: earn Torque every new committed revolution (not by clicking).
- Upgrade: buy six workshop components with Torque; they increase future yield.
- Skill tree: earn one point every 150 revolutions **this run** and spend it in three branches. Skill nodes have visible prerequisites.
- Cadence combo: maintain >=45 RPM (roughly <=1,333 ms between pulses) for bonus Torque once you have the corresponding skill; historical/offline pulses never build a live combo.
- Prestige: after 2,000 game revolutions in a run, reset your Torque balance, upgrades and skills to earn permanent cores. Each core adds 10% to future yields; fractional credits accumulate accurately between revolutions. Prestige **never resets raw events, sessions, lifetime counts, day totals, regular PEDAL RPG XP or achievement unlocks**.
- All upgrades, skills, prestige levels and currencies live in new SQLite tables; no polling of lifetime raw events is necessary.

## Rollback to the previously working v0.3 code

The new tables are additive. If you dislike the upgrade, restore only the backed-up backend application files; **do not restore the old database snapshot** because that would lose real revolutions recorded after the upgrade.

```bash
cd ~/pedal/pedal-telemetry
BACKUP="$(ls -dt ~/pedal/pedal-telemetry/upgrade-backups/pre-v04-* | head -1)"
echo "Restoring code from $BACKUP"
cp -a "$BACKUP/backend/." ./backend/
# Remove only the two new v0.4 files if they were absent in v0.3:
rm -f backend/app/game.py backend/static/forge-ui.js
docker compose up -d --build --no-deps backend
```

**Caution:** If you have edited the v0.3 server code manually after it was deployed, preserve those edits before applying v0.4. The code backup lets you recover them.

## Security and limitations

- HTTP logins and MQTT are suitable only for a **trusted LAN or private VPN**. Although `0.0.0.0` host binding is left alone, do not publish these plaintext ports on the public internet.
- Game currency is only produced inside the authoritative backend's SQLite ingest transaction, after a new `(device_id, seq)` row is committed. The normal MQTT credentials are still the trust boundary; this is not anti-cheat against a person who can forge device data.
- MQTT events that arrive much later still earn normal per-revolution Torque when first committed, but cannot create live cadence combos. Upgrades purchased before their arrival affect their reward; this is a game rule, not an attempt to rewrite the recorded physical time.
- The 60-RPM endurance achievement requires new v0.4 sampled intervals; historic v0.3 timestamps are not retrospectively scanned.
- No Docker launch on delta2 was possible while building this ZIP. Run the verification commands above after upgrading.
