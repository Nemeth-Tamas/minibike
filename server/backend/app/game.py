"""PEDAL FORGE v0.5 — cadence-powered incremental RPG.

Security/integrity invariants:
* Only a newly inserted, committed physical sensor event may mint Torque or advance combat.
* Offline/delayed sensor events earn Torque but never retroactively fight enemies.
* Purchases, tactics and prestige are transactional and cannot mint rewards.
* The real exercise journal, achievements and daily totals are independent of this game.
"""
from __future__ import annotations

import sqlite3
import time
from . import store

MAX_BALANCE = 2**62
PRESTIGE_MIN_REVS = 2_000
POINT_EVERY_REVS = 150
WAVES_PER_SECTOR = 5
MAX_SECTOR = 99

# id, name, description, base price, geometric growth numerator/denominator,
# maximum level, additive Torque per revolution, yield bonus percent per level.
# The first six entries are the original v0.4 upgrades; IDs and their costs
# stay unchanged so a running game and its existing saves migrate in place.
UPGRADES = (
    ('chain', 'Chain Drive', '+1 Torque per revolution', 15, 18, 10, 20, 1, 0),
    ('flywheel', 'Flywheel', '+5 Torque per revolution', 220, 19, 10, 15, 5, 0),
    ('alternator', 'Alternator', '+35 Torque per revolution', 2000, 2, 1, 12, 35, 0),
    ('gearbox', 'Variable Gearbox', '+25% Torque yield per level', 6000, 2, 1, 10, 0, 25),
    ('capacitor', 'Flux Capacitor', '+160 Torque per revolution', 35000, 22, 10, 8, 160, 0),
    ('quantum', 'Quantum Crank', '+750 Torque per revolution', 250000, 25, 10, 6, 750, 0),
    ('microcoil', 'Micro Coil', '+3 Torque per revolution', 80, 18, 10, 15, 3, 0),
    ('capacitive', 'Torque Converter', '+8% Torque yield per level', 450, 19, 10, 12, 0, 8),
    ('fusion', 'Fusion Coupler', '+60 Torque per revolution', 12500, 2, 1, 10, 60, 0),
    ('stabilizer', 'Rhythm Stabilizer', '+6% Torque yield per level', 900, 18, 10, 10, 0, 6),
    ('sprocket', 'Spiked Sprocket', '+2 attack per pedal', 35, 17, 10, 20, 0, 0),
    ('piston', 'Piston Hammer', '+6 attack per pedal', 200, 19, 10, 14, 0, 0),
    ('railgun', 'Rail Crank', '+22 attack per pedal', 1850, 2, 1, 12, 0, 0),
    ('reactor', 'Reactor Cannon', '+80 attack per pedal', 18000, 22, 10, 10, 0, 0),
    ('plating', 'Frame Plating', '+1 armor per level', 110, 18, 10, 16, 0, 0),
    ('battery', 'Backup Battery', '+20 max hull per level', 175, 19, 10, 15, 0, 0),
    ('repair', 'Self-Repair Unit', '+5 hull recovered after each victory', 320, 18, 10, 12, 0, 0),
    ('scavenger', 'Scrap Magnet', '+15% Scrap dropped per level', 280, 18, 10, 12, 0, 0),
    ('critcoil', 'Critical Coil', 'More frequent critical hits', 650, 21, 10, 8, 0, 0),
    ('shield', 'Reactive Shield', 'Reduce damage from enemy counterattacks', 420, 18, 10, 12, 0, 0),
)

# category, additional Scrap per level, first sector where item is available.
UPGRADE_META = {
    'chain': ('PRODUCTION', 0, 1), 'flywheel': ('PRODUCTION', 0, 1),
    'alternator': ('PRODUCTION', 0, 2), 'gearbox': ('PRODUCTION', 0, 3),
    'capacitor': ('PRODUCTION', 0, 5), 'quantum': ('PRODUCTION', 0, 8),
    'microcoil': ('PRODUCTION', 0, 1), 'capacitive': ('PRODUCTION', 0, 2),
    'fusion': ('PRODUCTION', 0, 4), 'stabilizer': ('PRODUCTION', 0, 2),
    'sprocket': ('ARMORY', 0, 1), 'piston': ('ARMORY', 4, 1),
    'railgun': ('ARMORY', 16, 2), 'reactor': ('ARMORY', 60, 4),
    'plating': ('DEFENSE', 2, 1), 'battery': ('DEFENSE', 4, 1),
    'repair': ('DEFENSE', 7, 2), 'shield': ('DEFENSE', 8, 2),
    'scavenger': ('SCAVENGING', 6, 1), 'critcoil': ('SCAVENGING', 9, 2),
}

# id, branch, name, description, maximum level, prerequisite,
# additive Torque/rev, Torque percentage/level, purchase discount percentage/level.
SKILLS = (
    ('steel', 'POWER', 'Steel Pedals', '+2 Torque per revolution', 3, None, 2, 0, 0),
    ('transmission', 'POWER', 'Transmission', '+25% Torque per level', 3, ('steel', 2), 0, 25, 0),
    ('overdrive', 'POWER', 'Overdrive', '+100% Torque', 1, ('transmission', 3), 0, 100, 0),
    ('steady', 'MOMENTUM', 'Steady Rider', '+10% Torque per level', 3, None, 0, 10, 0),
    ('cadence', 'MOMENTUM', 'Cadence Engine', '+10% Torque per level during a cadence combo', 3, ('steady', 2), 0, 0, 0),
    ('surge', 'MOMENTUM', 'Surge Mode', '+100% Torque during a 10-pulse combo', 1, ('cadence', 2), 0, 0, 0),
    ('blueprint', 'ENGINEERING', 'Blueprints', 'Reduce upgrade Torque prices by 5% per level', 3, None, 0, 0, 5),
    ('salvage', 'ENGINEERING', 'Scrap Savant', '+15 Torque per revolution', 3, ('blueprint', 2), 15, 0, 0),
    ('legacy', 'ENGINEERING', 'Legacy Circuitry', 'Double prestige core yield bonus', 1, ('salvage', 3), 0, 0, 0),
    ('voltage', 'POWER', 'Voltage Tap', '+12 Torque per revolution', 3, ('steel', 2), 12, 0, 0),
    ('synthesis', 'POWER', 'Synthesis', '+18% Torque per level', 3, ('voltage', 2), 0, 18, 0),
    ('dynasty', 'POWER', 'Dynasty Dynamo', '+45% Torque per level', 2, ('overdrive', 1), 0, 45, 0),
    ('flow', 'MOMENTUM', 'Flow State', '+8% Torque during cadence combos per level', 3, ('steady', 2), 0, 0, 0),
    ('second_wind', 'MOMENTUM', 'Second Wind', '+4 hull healed after each victory per level', 3, ('flow', 2), 0, 0, 0),
    ('rhythm_strike', 'MOMENTUM', 'Rhythm Strike', '+2 attack per combo tier', 3, ('cadence', 2), 0, 0, 0),
    ('artisan', 'ENGINEERING', 'Artisan', '-3% Scrap upgrade costs per level', 3, ('blueprint', 2), 0, 0, 0),
    ('stockpile', 'ENGINEERING', 'Stockpile', '+10% Scrap per level', 3, ('artisan', 2), 0, 0, 0),
    ('optimizer', 'ENGINEERING', 'Optimizer', '+10% Torque and +2 attack per level', 3, ('salvage', 2), 0, 10, 0),
    ('blade', 'COMBAT', 'Jagged Teeth', '+3 attack per level', 3, None, 0, 0, 0),
    ('precision', 'COMBAT', 'Precision Bearings', 'Increase critical hit frequency', 3, ('blade', 2), 0, 0, 0),
    ('berserker', 'COMBAT', 'Berserker', '+15% attack per level', 3, ('blade', 2), 0, 0, 0),
    ('boss_breaker', 'COMBAT', 'Boss Breaker', '+35% damage against bosses', 1, ('berserker', 2), 0, 0, 0),
    ('titan', 'COMBAT', 'Titan Driver', '+15 attack per level', 3, ('precision', 2), 0, 0, 0),
    ('ironhide', 'FORTITUDE', 'Ironhide', '+2 armor per level', 3, None, 0, 0, 0),
    ('bulkhead', 'FORTITUDE', 'Bulkhead', '+25 maximum hull per level', 3, ('ironhide', 2), 0, 0, 0),
    ('recovery', 'FORTITUDE', 'Field Medic', '+8 hull after victory per level', 3, ('bulkhead', 2), 0, 0, 0),
    ('deflection', 'FORTITUDE', 'Deflection', '-10% enemy damage per level', 3, ('ironhide', 2), 0, 0, 0),
    ('last_stand', 'FORTITUDE', 'Last Stand', '+35% attack while below half hull', 1, ('deflection', 2), 0, 0, 0),
    ('prospector', 'SALVAGE', 'Prospector', '+15% Scrap per level', 3, None, 0, 0, 0),
    ('bounty', 'SALVAGE', 'Bounty Hunter', '+5 Scrap on wins per level', 3, ('prospector', 2), 0, 0, 0),
    ('collector', 'SALVAGE', 'Collector', '+10% Torque from victories per level', 3, ('bounty', 2), 0, 0, 0),
    ('trophy', 'SALVAGE', 'Trophy Hunter', '+1 extra relic from every third boss', 1, ('collector', 2), 0, 0, 0),
    ('salvage_armor', 'SALVAGE', 'Makeshift Shields', '+1 armor and +5% Scrap per level', 3, ('prospector', 2), 0, 0, 0),
)

UPGRADE_BY_ID = {r[0]: r for r in UPGRADES}
SKILL_BY_ID = {r[0]: r for r in SKILLS}

# Permanent investments can be bought using relics from boss kills.
RELIC_TRAITS = (
    ('reactor_core', 'Reactor Core', '+3% Torque yield per level', 8, 1),
    ('war_engine', 'War Engine', '+3 attack per level', 8, 1),
    ('hardened_frame', 'Hardened Frame', '+12 hull per level', 8, 1),
    ('relic_hunter', 'Relic Hunter', '+7% Scrap per level', 8, 2),
)
RELIC_BY_ID = {r[0]: r for r in RELIC_TRAITS}
TACTICS = ('balanced', 'assault', 'guard')

ENEMIES = (
    ('Rust Rat', '🐀', 'Ravages loose wiring', 55, 2, 0),
    ('Loose Bearing', '🛞', 'A hardened rolling menace', 78, 3, 1),
    ('Scrap Drone', '🤖', 'Fast, jittering blades', 100, 3, 0),
    ('Hydraulic Gnawer', '🦾', 'Armor-piercing machinery', 130, 4, 2),
    ('The Bent Crank', '👹', 'SECTOR BOSS · Guardian of the scrap', 260, 6, 2),
)
BOSS_NAMES = ('The Bent Crank', 'The Static Widow', 'The Iron Cyclops',
              'The Oil Tyrant', 'The Reactor Warden', 'The Endless Gear')
SECTOR_NAMES = ('Scrapyard Outskirts', 'Copper Tunnels', 'Corroded Foundry',
                'Storm Dynamo', 'Reactor Core', 'The Clockwork Frontier')

SCHEMA = """
CREATE TABLE IF NOT EXISTS forge_state (
    device_id TEXT PRIMARY KEY, torque INTEGER NOT NULL DEFAULT 0,
    run_revs INTEGER NOT NULL DEFAULT 0, total_game_revs INTEGER NOT NULL DEFAULT 0,
    run_earned INTEGER NOT NULL DEFAULT 0, total_earned INTEGER NOT NULL DEFAULT 0,
    prestiges INTEGER NOT NULL DEFAULT 0, cores INTEGER NOT NULL DEFAULT 0,
    skill_spent INTEGER NOT NULL DEFAULT 0, last_live_pulse_ms INTEGER,
    combo INTEGER NOT NULL DEFAULT 0, torque_fraction INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS forge_upgrades (
    device_id TEXT NOT NULL, item_id TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id,item_id)
);
CREATE TABLE IF NOT EXISTS forge_skills (
    device_id TEXT NOT NULL, skill_id TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id,skill_id)
);
CREATE TABLE IF NOT EXISTS forge_prestiges (
    device_id TEXT NOT NULL, number INTEGER NOT NULL, earned_cores INTEGER NOT NULL,
    previous_run_revs INTEGER NOT NULL, previous_run_earned INTEGER NOT NULL,
    at_ms INTEGER NOT NULL, PRIMARY KEY(device_id,number)
);
CREATE TABLE IF NOT EXISTS forge_combat (
    device_id TEXT PRIMARY KEY, sector INTEGER NOT NULL DEFAULT 1,
    wave INTEGER NOT NULL DEFAULT 1,
    enemy_hp INTEGER NOT NULL DEFAULT 55, hero_hp INTEGER NOT NULL DEFAULT 100,
    scrap INTEGER NOT NULL DEFAULT 0, relics INTEGER NOT NULL DEFAULT 0,
    kills_run INTEGER NOT NULL DEFAULT 0, kills_total INTEGER NOT NULL DEFAULT 0,
    bosses_run INTEGER NOT NULL DEFAULT 0, bosses_total INTEGER NOT NULL DEFAULT 0,
    attacks INTEGER NOT NULL DEFAULT 0, retreats INTEGER NOT NULL DEFAULT 0,
    defeats_this_wave INTEGER NOT NULL DEFAULT 0,
    last_hit INTEGER NOT NULL DEFAULT 0, last_counter INTEGER NOT NULL DEFAULT 0,
    last_crit INTEGER NOT NULL DEFAULT 0, last_loot INTEGER NOT NULL DEFAULT 0,
    tactic TEXT NOT NULL DEFAULT 'balanced', last_activity_ms INTEGER
);
CREATE TABLE IF NOT EXISTS forge_preferences (
    device_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS forge_relic_traits (
    device_id TEXT NOT NULL, trait_id TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id,trait_id)
);
CREATE TABLE IF NOT EXISTS forge_battle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
    at_ms INTEGER NOT NULL, description TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS forge_battle_log_recent
    ON forge_battle_log(device_id,id DESC);
"""


def initialize() -> None:
    with store.db() as con:
        con.executescript(SCHEMA)


def _enemy(sector: int, wave: int) -> dict:
    idx = max(1, min(WAVES_PER_SECTOR, wave)) - 1
    name, emoji, subtitle, hp, attack, armor = ENEMIES[idx]
    if idx == WAVES_PER_SECTOR-1:
        name = BOSS_NAMES[(sector-1) % len(BOSS_NAMES)]
        subtitle = 'SECTOR BOSS · Defeat to advance to the next region'
    # Growth per sector is ~42%, while upgrades scale in steps and bring
    # their own Scrap costs. Avoid exponential runaway after sector 25.
    factor = 1.42 ** min(24, sector-1)
    factor *= 1 + max(0, sector-25) * .15
    return dict(name=name, emoji=emoji, subtitle=subtitle, boss=idx == 4,
                hp=max(1, min(1_000_000_000, round(hp * factor))),
                attack=min(1_000_000, attack + (sector-1)*2),
                armor=min(1_000_000, armor + max(0, sector-2)),
                sector=sector, wave=wave)


def _ensure(con: sqlite3.Connection, device: str) -> None:
    con.execute('INSERT OR IGNORE INTO forge_state(device_id) VALUES(?)', (device,))
    con.execute('INSERT OR IGNORE INTO forge_combat(device_id) VALUES(?)', (device,))
    con.execute('INSERT OR IGNORE INTO forge_preferences(device_id) VALUES(?)', (device,))


def _require_enabled(con: sqlite3.Connection, device: str) -> None:
    if not con.execute(
            'SELECT enabled FROM forge_preferences WHERE device_id=?', (device,)
    ).fetchone()[0]:
        raise ValueError('Game is OFF. Turn it on to change your build.')


def set_enabled(device: str, enabled: bool) -> dict:
    """Pause/resume only the fictional game. Telemetry is never disabled."""
    store._id(device, 'device_id')
    if type(enabled) is not bool:
        raise ValueError('enabled must be a boolean')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con, device)
        con.execute('UPDATE forge_preferences SET enabled=? WHERE device_id=?',
                    (int(enabled), device))
        # Never carry a cadence combo across a pause, even if very short.
        con.execute('''UPDATE forge_state SET last_live_pulse_ms=NULL,combo=0
                       WHERE device_id=?''', (device,))
    return state(device)


def _levels(con: sqlite3.Connection, device: str, table: str, key: str) -> dict[str, int]:
    # Callers use hardcoded internal table and column names only.
    return {r[0]: r[1] for r in con.execute(
        f'SELECT {key},level FROM {table} WHERE device_id=?', (device,))}


def _yield_scaled(upgrades: dict, skills: dict, cores: int, combo: int,
                  relics: dict | None = None) -> int:
    base = 1
    bonus_pct = 100 + min(cores, 1000)*10
    for key, _, _, _, _, _, _, add, pct in UPGRADES:
        level = upgrades.get(key, 0)
        base += add * level
        bonus_pct += pct * level
    for key, _, _, _, _, _, add, pct, _ in SKILLS:
        level = skills.get(key, 0)
        base += add * level
        bonus_pct += pct * level
    if skills.get('legacy', 0):
        bonus_pct += 10 * min(cores, 1000)
    if combo >= 3:
        bonus_pct += 10 * skills.get('cadence', 0) + 8 * skills.get('flow', 0)
    if combo >= 10 and skills.get('surge', 0):
        bonus_pct += 100
    bonus_pct += 3 * (relics or {}).get('reactor_core', 0)
    return max(100, min(100_000_000_000, base * bonus_pct))


def _cost(upgrade: tuple, level: int, discount: int) -> int:
    base, n, d = upgrade[3], upgrade[4], upgrade[5]
    raw = base * n**level // d**level
    return max(1, raw * max(50, 100-discount) // 100)


def _scrap_cost(key: str, level: int, skills: dict) -> int:
    base = UPGRADE_META[key][1]
    if not base:
        return 0
    price = max(1, base * 17**level // 10**level)
    return max(1, price * max(50, 100-3*skills.get('artisan', 0)) // 100)


def _hero_stats(u: dict, s: dict, t: dict) -> dict:
    max_hull = 100 + 20*u.get('battery', 0) + 25*s.get('bulkhead', 0) + 12*t.get('hardened_frame', 0)
    armor = (u.get('plating', 0) + u.get('shield', 0) +
             2*s.get('ironhide', 0) + s.get('salvage_armor', 0))
    attack = (2 + 2*u.get('sprocket', 0) + 6*u.get('piston', 0) +
              22*u.get('railgun', 0) + 80*u.get('reactor', 0) +
              3*s.get('blade', 0) + 15*s.get('titan', 0) +
              2*s.get('optimizer', 0) + 3*t.get('war_engine', 0))
    heal = 16 + 5*u.get('repair', 0) + 4*s.get('second_wind', 0) + 8*s.get('recovery', 0)
    crit_period = max(5, 13 - u.get('critcoil', 0) - 2*s.get('precision', 0))
    scrap_pct = (100 + 15*u.get('scavenger', 0) +
                 15*s.get('prospector', 0) + 10*s.get('stockpile', 0) +
                 5*s.get('salvage_armor', 0) + 7*t.get('relic_hunter', 0))
    return dict(hull=max_hull, armor=armor, attack=attack, heal=heal,
                crit_every=crit_period, scrap_pct=scrap_pct)


def _log(con: sqlite3.Connection, device: str, at_ms: int, message: str) -> None:
    con.execute('INSERT INTO forge_battle_log(device_id,at_ms,description) VALUES(?,?,?)',
                (device, at_ms, message[:220]))
    # Keep the journal small over years of sessions.
    con.execute('''DELETE FROM forge_battle_log WHERE device_id=? AND id NOT IN
        (SELECT id FROM forge_battle_log WHERE device_id=? ORDER BY id DESC LIMIT 20)''',
                (device, device))


def _combat_step(con: sqlite3.Connection, device: str, pulse_ms: int, combo: int,
                 u: dict, s: dict, t: dict) -> None:
    c = con.execute('SELECT * FROM forge_combat WHERE device_id=?', (device,)).fetchone()
    enemy = _enemy(c['sector'], c['wave'])
    hero = _hero_stats(u, s, t)
    hp = max(0, min(c['enemy_hp'], enemy['hp']))
    hull = max(0, min(c['hero_hp'], hero['hull']))
    attacks = c['attacks'] + 1
    critical = int(attacks % hero['crit_every'] == 0)
    damage = hero['attack']
    if combo >= 5:
        damage = damage * (125 + 5*s.get('rhythm_strike', 0)) // 100
    if combo >= 15:
        damage = damage * 130 // 100
    damage = damage * (100 + 15*s.get('berserker', 0)) // 100
    if enemy['boss']:
        damage = damage * (135 if s.get('boss_breaker') else 100) // 100
    if hull * 2 < hero['hull'] and s.get('last_stand'):
        damage = damage * 135 // 100
    if c['tactic'] == 'assault':
        damage = (damage * 150 + 99) // 100
    elif c['tactic'] == 'guard':
        damage = damage * 80 // 100
    if critical:
        damage *= 2
    damage = max(1, damage - enemy['armor'])
    hp -= damage
    counter = 0
    if hp > 0 and attacks % 8 == 0:
        raw = enemy['attack']
        raw = raw * {'assault': 150, 'balanced': 100, 'guard': 65}[c['tactic']] // 100
        raw = raw * (100 - min(60, s.get('deflection', 0)*10)) // 100
        # Pity mechanic after defeats avoids an unavoidable boss wall.
        raw = raw * (100 - min(50, c['defeats_this_wave']*10)) // 100
        counter = max(1, raw - hero['armor'])
        hull -= counter

    if hp <= 0:
        scrap_base = 9 + 4*c['sector'] + 5*c['wave'] + (60 if enemy['boss'] else 0)
        scrap_gain = scrap_base * hero['scrap_pct'] // 100 + 5*s.get('bounty', 0)
        new_scrap = min(MAX_BALANCE, c['scrap'] + scrap_gain)
        new_relics = c['relics']
        bosses = c['bosses_run'] + int(enemy['boss'])
        total_bosses = c['bosses_total'] + int(enemy['boss'])
        if enemy['boss']:
            new_relics = min(MAX_BALANCE, new_relics + 1 + c['sector']//3 +
                             int(bool(s.get('trophy')) and total_bosses % 3 == 0))
        next_sector = min(MAX_SECTOR, c['sector'] + 1) if enemy['boss'] else c['sector']
        next_wave = 1 if enemy['boss'] else c['wave'] + 1
        next_enemy = _enemy(next_sector, next_wave)
        _log(con, device, pulse_ms,
             f"{enemy['emoji']} Defeated {enemy['name']} · +{scrap_gain} Scrap" +
             (f" · relics awarded" if enemy['boss'] else ''))
        con.execute('''UPDATE forge_combat SET sector=?,wave=?,enemy_hp=?,
            hero_hp=?,scrap=?,relics=?,kills_run=kills_run+1,kills_total=kills_total+1,
            bosses_run=?,bosses_total=?,attacks=?,defeats_this_wave=0,
            last_hit=?,last_counter=?,last_crit=?,last_loot=?,last_activity_ms=?
            WHERE device_id=?''',
            (next_sector, next_wave, next_enemy['hp'],
             min(hero['hull'], max(1,hull) + hero['heal']),
             new_scrap, new_relics, bosses, total_bosses, attacks, damage, 0,
             critical, scrap_gain, pulse_ms, device))
        # Victory Torque is earned from a real pedal event, never from clicking.
        extra = min(500_000, (10 + c['sector']*3) * s.get('collector', 0) // 10)
        if extra:
            con.execute('''UPDATE forge_state SET torque=MIN(?,torque+?),
                run_earned=MIN(?,run_earned+?),total_earned=MIN(?,total_earned+?)
                WHERE device_id=?''',
                (MAX_BALANCE, extra, MAX_BALANCE, extra, MAX_BALANCE, extra, device))
        return

    if hull <= 0:
        # No deaths, retreats, lost loot, or enemy resets. Only player-chosen
        # prestige can reset the campaign. Armor still protects the hull.
        if c['hero_hp'] > 1:
            _log(con, device, pulse_ms,
                 '🛡️ Emergency shield engaged! Hull held at 1; fight progress preserved.')
        hull = 1

    con.execute('''UPDATE forge_combat SET enemy_hp=?,hero_hp=?,attacks=?,
        last_hit=?,last_counter=?,last_crit=?,last_loot=0,last_activity_ms=?
        WHERE device_id=?''',
        (hp, hull, attacks, damage, counter, critical, pulse_ms, device))


def on_event(con: sqlite3.Connection, device: str, pulse_ms: int, received_ms: int) -> None:
    """Only called within the original ingest transaction after INSERT succeeded."""
    _ensure(con, device)
    # OFF freezes ALL game progression, while the enclosing ingest transaction
    # continues to journal the real pulse, session, goals and achievements.
    if not con.execute('SELECT enabled FROM forge_preferences WHERE device_id=?',
                       (device,)).fetchone()[0]:
        return
    state = con.execute('SELECT * FROM forge_state WHERE device_id=?', (device,)).fetchone()
    u = _levels(con, device, 'forge_upgrades', 'item_id')
    s = _levels(con, device, 'forge_skills', 'skill_id')
    t = _levels(con, device, 'forge_relic_traits', 'trait_id')
    previous = state['last_live_pulse_ms']
    live = 0 <= received_ms-pulse_ms <= 15_000
    gap = pulse_ms-previous if previous is not None else None
    combo = (min(999,state['combo']+1) if live and gap is not None and
             300 <= gap <= 1333 else 0)
    scaled = _yield_scaled(u,s,state['cores'],combo,t)
    reward, fraction = divmod(scaled+state['torque_fraction'],100)
    con.execute('''UPDATE forge_state SET
       torque=MIN(?,torque+?),run_revs=run_revs+1,
       total_game_revs=total_game_revs+1,
       run_earned=MIN(?,run_earned+?),total_earned=MIN(?,total_earned+?),
       last_live_pulse_ms=?,combo=?,torque_fraction=? WHERE device_id=?''',
       (MAX_BALANCE,reward,MAX_BALANCE,reward,MAX_BALANCE,reward,
        pulse_ms if live else None,combo,fraction,device))
    # No combat progress on stale events, historical backfill, or MQTT duplicates.
    if live:
        _combat_step(con,device,pulse_ms,combo,u,s,t)


def _view(con: sqlite3.Connection, device: str) -> dict:
    _ensure(con,device)
    row=dict(con.execute('SELECT * FROM forge_state WHERE device_id=?',(device,)).fetchone())
    c=dict(con.execute('SELECT * FROM forge_combat WHERE device_id=?',(device,)).fetchone())
    enabled=bool(con.execute('SELECT enabled FROM forge_preferences WHERE device_id=?',
                             (device,)).fetchone()[0])
    u=_levels(con,device,'forge_upgrades','item_id')
    s=_levels(con,device,'forge_skills','skill_id')
    traits=_levels(con,device,'forge_relic_traits','trait_id')
    available=row['run_revs']//POINT_EVERY_REVS-row['skill_spent']
    discount=5*s.get('blueprint',0)
    upgrades=[]
    for meta in UPGRADES:
        key,name,desc,_,_,_,cap,_,_=meta
        level=u.get(key,0)
        category,_,sector_gate=UPGRADE_META[key]
        torque_cost=_cost(meta,level,discount) if level<cap else None
        scrap_cost=_scrap_cost(key,level,s) if level<cap else None
        unlocked=c['sector']>=sector_gate
        upgrades.append(dict(id=key,name=name,description=desc,category=category,
                             level=level,max_level=cap,cost=torque_cost,
                             scrap_cost=scrap_cost,requires_sector=sector_gate,
                             unlocked=unlocked,can_buy=bool(unlocked and level<cap and
                             row['torque']>=torque_cost and c['scrap']>=scrap_cost)))
    skills=[]
    for key,branch,name,desc,cap,req,*_ in SKILLS:
        level=s.get(key,0)
        meets=not req or s.get(req[0],0)>=req[1]
        skills.append(dict(id=key,branch=branch,name=name,description=desc,
                           level=level,max_level=cap,
                           prerequisite=None if not req else f'{SKILL_BY_ID[req[0]][2]} Lv {req[1]}',
                           unlocked=bool(meets),can_learn=bool(meets and level<cap and available>=1)))
    permanent=[]
    for key,name,desc,cap,base in RELIC_TRAITS:
        level=traits.get(key,0)
        cost=base+level*(level+1)//2 if level<cap else None
        permanent.append(dict(id=key,name=name,description=desc,level=level,
                              max_level=cap,cost=cost,can_buy=bool(cost is not None and c['relics']>=cost)))
    hero=_hero_stats(u,s,traits)
    enemy=_enemy(c['sector'],c['wave'])
    log=[dict(at_ms=r[0],description=r[1]) for r in con.execute(
        'SELECT at_ms,description FROM forge_battle_log WHERE device_id=? ORDER BY id DESC LIMIT 6',
        (device,))]
    row.update(dict(
        enabled=enabled,
        torque_per_rev=round(_yield_scaled(u,s,row['cores'],row['combo'],traits)/100,2),
        skill_points_available=available,skill_points_earned=row['run_revs']//POINT_EVERY_REVS,
        skill_points_every_revs=POINT_EVERY_REVS,
        next_skill_point_at=(row['run_revs']//POINT_EVERY_REVS+1)*POINT_EVERY_REVS,
        upgrades=upgrades,skills=skills,
        prestige_available=row['run_revs']>=PRESTIGE_MIN_REVS,
        prestige_min_revs=PRESTIGE_MIN_REVS,
        next_prestige_cores=max(1,min(20,row['run_revs']//PRESTIGE_MIN_REVS)),
        no_idle_earnings=True,
        prestige_history_count=con.execute('SELECT COUNT(*) FROM forge_prestiges WHERE device_id=?',
                                           (device,)).fetchone()[0],
        combat=dict(sector=c['sector'],sector_name=SECTOR_NAMES[(c['sector']-1)%len(SECTOR_NAMES)],
                    wave=c['wave'],waves_per_sector=WAVES_PER_SECTOR,
                    kills_run=c['kills_run'],kills_total=c['kills_total'],
                    bosses_run=c['bosses_run'],bosses_total=c['bosses_total'],
                    scrap=c['scrap'],relics=c['relics'],tactic=c['tactic'],
                    tactics=list(TACTICS),enemy=enemy,enemy_hp=c['enemy_hp'],
                    enemy_max_hp=enemy['hp'],hero_hp=min(c['hero_hp'],hero['hull']),
                    hero_max_hp=hero['hull'],hero_attack=hero['attack'],armor=hero['armor'],
                    crit_every=hero['crit_every'],attacks=c['attacks'],retreats=c['retreats'],
                    last_hit=c['last_hit'],last_counter=c['last_counter'],
                    last_crit=bool(c['last_crit']),last_loot=c['last_loot'],
                    log=log,permanent=permanent,
                    last_activity_ms=c['last_activity_ms'],
                    rule='Game OFF freezes combat. Game ON: enemies counter only on pedal hits. Shield prevents death or forced resets.'),
    ))
    return row


def state(device: str) -> dict:
    store._id(device,'device_id')
    with store.db() as con:
        return _view(con,device)


def purchase(device: str, item: str) -> dict:
    store._id(device,'device_id')
    if item not in UPGRADE_BY_ID:
        raise ValueError('Unknown upgrade')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con,device)
        _require_enabled(con,device)
        u=con.execute('SELECT level FROM forge_upgrades WHERE device_id=? AND item_id=?',
                      (device,item)).fetchone()
        level=u['level'] if u else 0
        meta=UPGRADE_BY_ID[item]
        if level>=meta[6]:
            raise ValueError('Upgrade already at maximum level')
        combat=con.execute('SELECT sector,scrap FROM forge_combat WHERE device_id=?',
                           (device,)).fetchone()
        if combat['sector']<UPGRADE_META[item][2]:
            raise ValueError(f'Reach sector {UPGRADE_META[item][2]} to unlock this upgrade')
        skills=_levels(con,device,'forge_skills','skill_id')
        price=_cost(meta,level,skills.get('blueprint',0)*5)
        scrap=_scrap_cost(item,level,skills)
        wallet=con.execute('SELECT torque FROM forge_state WHERE device_id=?',
                           (device,)).fetchone()[0]
        if wallet<price or combat['scrap']<scrap:
            raise ValueError('Not enough Torque or Scrap. Pedal to earn more!')
        con.execute('UPDATE forge_state SET torque=torque-? WHERE device_id=?',(price,device))
        con.execute('UPDATE forge_combat SET scrap=scrap-? WHERE device_id=?',(scrap,device))
        con.execute('''INSERT INTO forge_upgrades(device_id,item_id,level) VALUES(?,?,1)
            ON CONFLICT(device_id,item_id) DO UPDATE SET level=level+1''',(device,item))
        if item=='battery':
            con.execute('UPDATE forge_combat SET hero_hp=hero_hp+20 WHERE device_id=?',(device,))
    return state(device)


def learn(device: str, skill: str) -> dict:
    store._id(device,'device_id')
    if skill not in SKILL_BY_ID:
        raise ValueError('Unknown skill')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con,device)
        _require_enabled(con,device)
        current=con.execute('SELECT run_revs,skill_spent FROM forge_state WHERE device_id=?',
                            (device,)).fetchone()
        skills=_levels(con,device,'forge_skills','skill_id')
        meta=SKILL_BY_ID[skill]
        level=skills.get(skill,0)
        if level>=meta[4]:
            raise ValueError('Skill already at maximum level')
        req=meta[5]
        if req and skills.get(req[0],0)<req[1]:
            raise ValueError('Unlock its prerequisite skill first')
        if current['run_revs']//POINT_EVERY_REVS<=current['skill_spent']:
            raise ValueError('No free skill points. Pedal to earn more!')
        con.execute('UPDATE forge_state SET skill_spent=skill_spent+1 WHERE device_id=?',(device,))
        con.execute('''INSERT INTO forge_skills(device_id,skill_id,level) VALUES(?,?,1)
            ON CONFLICT(device_id,skill_id) DO UPDATE SET level=level+1''',(device,skill))
        if skill=='bulkhead':
            con.execute('UPDATE forge_combat SET hero_hp=hero_hp+25 WHERE device_id=?',(device,))
    return state(device)


def set_tactic(device: str, tactic: str) -> dict:
    store._id(device,'device_id')
    if tactic not in TACTICS:
        raise ValueError('Unknown combat tactic')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con,device)
        _require_enabled(con,device)
        con.execute('UPDATE forge_combat SET tactic=? WHERE device_id=?',(tactic,device))
    return state(device)


def permanent_upgrade(device: str, trait: str) -> dict:
    store._id(device,'device_id')
    if trait not in RELIC_BY_ID:
        raise ValueError('Unknown relic trait')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con,device)
        _require_enabled(con,device)
        levels=_levels(con,device,'forge_relic_traits','trait_id')
        level=levels.get(trait,0)
        cap=RELIC_BY_ID[trait][3]
        if level>=cap:
            raise ValueError('Relic trait already mastered')
        cost=RELIC_BY_ID[trait][4]+level*(level+1)//2
        result=con.execute('UPDATE forge_combat SET relics=relics-? WHERE device_id=? AND relics>=?',
                           (cost,device,cost))
        if result.rowcount!=1:
            raise ValueError('Not enough relics. Defeat sector bosses to earn more!')
        con.execute('''INSERT INTO forge_relic_traits(device_id,trait_id,level) VALUES(?,?,1)
            ON CONFLICT(device_id,trait_id) DO UPDATE SET level=level+1''',(device,trait))
        if trait=='hardened_frame':
            con.execute('UPDATE forge_combat SET hero_hp=hero_hp+12 WHERE device_id=?',(device,))
    return state(device)


def prestige(device: str, now_ms: int | None = None) -> dict:
    store._id(device,'device_id')
    now_ms=int(time.time()*1000) if now_ms is None else now_ms
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con,device)
        _require_enabled(con,device)
        row=con.execute('SELECT * FROM forge_state WHERE device_id=?',(device,)).fetchone()
        if row['run_revs']<PRESTIGE_MIN_REVS:
            raise ValueError(f'Prestige requires {PRESTIGE_MIN_REVS:,} revolutions this run')
        cores=max(1,min(20,row['run_revs']//PRESTIGE_MIN_REVS))
        con.execute('''INSERT INTO forge_prestiges
            (device_id,number,earned_cores,previous_run_revs,previous_run_earned,at_ms)
            VALUES(?,?,?,?,?,?)''',
            (device,row['prestiges']+1,cores,row['run_revs'],row['run_earned'],now_ms))
        con.execute('''UPDATE forge_state SET torque=0,run_revs=0,run_earned=0,
            prestiges=prestiges+1,cores=cores+?,skill_spent=0,
            last_live_pulse_ms=NULL,combo=0,torque_fraction=0 WHERE device_id=?''',
            (cores,device))
        con.execute('DELETE FROM forge_upgrades WHERE device_id=?',(device,))
        con.execute('DELETE FROM forge_skills WHERE device_id=?',(device,))
        traits=_levels(con,device,'forge_relic_traits','trait_id')
        max_hull=_hero_stats({}, {}, traits)['hull']
        con.execute('''UPDATE forge_combat SET sector=1,wave=1,enemy_hp=?,hero_hp=?,
            scrap=0,kills_run=0,bosses_run=0,defeats_this_wave=0,
            last_hit=0,last_counter=0,last_crit=0,last_loot=0,tactic='balanced',
            last_activity_ms=NULL WHERE device_id=?''',
            (_enemy(1,1)['hp'],max_hull,device))
        _log(con,device,now_ms,f'✨ Prestige {row["prestiges"]+1}! +{cores} cores. Regions reset; relic tech persists.')
    return state(device)
