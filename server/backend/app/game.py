"""PEDAL FORGE: physical-revolution-powered incremental game, v0.4.

Only store.ingest() may mint torque; purchases and prestige never mint it.
All changes to game state run inside SQLite write transactions. No AFK income.
Previous lifetime events are left untouched and DO NOT retroactively mint currency.
"""
from __future__ import annotations

import sqlite3
import time
from . import store

MAX_BALANCE = 2**62
PRESTIGE_MIN_REVS = 2_000
POINT_EVERY_REVS = 150

# id, name, description, base price, price multiplier numerator/denominator,
# max level, additive torque, bonus percent per level
UPGRADES = (
    ('chain', 'Chain Drive', '+1 base torque per revolution', 15, 18, 10, 20, 1, 0),
    ('flywheel', 'Flywheel', '+5 base torque per revolution', 220, 19, 10, 15, 5, 0),
    ('alternator', 'Alternator', '+35 base torque per revolution', 2000, 2, 1, 12, 35, 0),
    ('gearbox', 'Variable Gearbox', '+25% torque yield per level', 6000, 2, 1, 10, 0, 25),
    ('capacitor', 'Flux Capacitor', '+160 base torque per revolution', 35_000, 22, 10, 8, 160, 0),
    ('quantum', 'Quantum Crank', '+750 base torque per revolution', 250_000, 25, 10, 6, 750, 0),
)
# id, branch, name, description, max level, (predecessor, minimum level),
# base bonus per level, multiplier percent per level, discount percent per level
SKILLS = (
    ('steel', 'POWER', 'Steel Pedals', '+2 base torque per level', 3, None, 2, 0, 0),
    ('transmission', 'POWER', 'Transmission', '+25% torque yield per level', 3, ('steel', 2), 0, 25, 0),
    ('overdrive', 'POWER', 'Overdrive', '+100% torque yield', 1, ('transmission', 3), 0, 100, 0),
    ('steady', 'MOMENTUM', 'Steady Rider', '+10% torque yield per level', 3, None, 0, 10, 0),
    ('cadence', 'MOMENTUM', 'Cadence Engine', '+10% extra yield per level during valid cadence streaks', 3, ('steady', 2), 0, 0, 0),
    ('surge', 'MOMENTUM', 'Surge Mode', '+100% yield during a 10-revolution cadence streak', 1, ('cadence', 2), 0, 0, 0),
    ('blueprint', 'ENGINEERING', 'Blueprints', 'Reduce upgrade prices by 5% per level', 3, None, 0, 0, 5),
    ('salvage', 'ENGINEERING', 'Scrap Savant', '+15 base torque per level', 3, ('blueprint', 2), 15, 0, 0),
    ('legacy', 'ENGINEERING', 'Legacy Circuitry', '+10% yield per prestige core', 1, ('salvage', 3), 0, 0, 0),
)
UPGRADE_BY_ID = {row[0]: row for row in UPGRADES}
SKILL_BY_ID = {row[0]: row for row in SKILLS}

SCHEMA = """
CREATE TABLE IF NOT EXISTS forge_state (
    device_id TEXT PRIMARY KEY,
    torque INTEGER NOT NULL DEFAULT 0,
    run_revs INTEGER NOT NULL DEFAULT 0,
    total_game_revs INTEGER NOT NULL DEFAULT 0,
    run_earned INTEGER NOT NULL DEFAULT 0,
    total_earned INTEGER NOT NULL DEFAULT 0,
    prestiges INTEGER NOT NULL DEFAULT 0,
    cores INTEGER NOT NULL DEFAULT 0,
    skill_spent INTEGER NOT NULL DEFAULT 0,
    last_live_pulse_ms INTEGER,
    combo INTEGER NOT NULL DEFAULT 0,
    torque_fraction INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS forge_upgrades (
    device_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id,item_id)
);
CREATE TABLE IF NOT EXISTS forge_skills (
    device_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id,skill_id)
);
CREATE TABLE IF NOT EXISTS forge_prestiges (
    device_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    earned_cores INTEGER NOT NULL,
    previous_run_revs INTEGER NOT NULL,
    previous_run_earned INTEGER NOT NULL,
    at_ms INTEGER NOT NULL,
    PRIMARY KEY(device_id,number)
);
"""


def initialize() -> None:
    with store.db() as con:
        con.executescript(SCHEMA)


def _ensure(con: sqlite3.Connection, device: str) -> None:
    con.execute('INSERT OR IGNORE INTO forge_state(device_id) VALUES(?)', (device,))


def _levels(con: sqlite3.Connection, device: str, table: str, key: str) -> dict[str, int]:
    # table / column are hardcoded by caller, never user-controlled.
    return {row[0]: row[1] for row in con.execute(
        f'SELECT {key},level FROM {table} WHERE device_id=?', (device,))}


def _yield_scaled(upgrades: dict, skills: dict, cores: int, combo: int) -> int:
    base = 1
    bonus_pct = 100 + min(cores, 1000) * 10
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
        bonus_pct += 10 * skills.get('cadence', 0)
    if combo >= 10 and skills.get('surge', 0):
        bonus_pct += 100
    return max(100, min(100_000_000_000, base * bonus_pct))


def on_event(con: sqlite3.Connection, device: str, pulse_ms: int, received_ms: int) -> None:
    """Called only for NEW inserted raw sensor events, inside original ingest TX.

    No retroactive currency for events predating the game's first deployment.
    A legitimately new unacknowledged offline pulse may still earn base torque.
    """
    _ensure(con, device)
    state = con.execute('SELECT * FROM forge_state WHERE device_id=?', (device,)).fetchone()
    upgrades = _levels(con, device, 'forge_upgrades', 'item_id')
    skills = _levels(con, device, 'forge_skills', 'skill_id')
    previous = state['last_live_pulse_ms']
    live = 0 <= received_ms - pulse_ms <= 15_000
    gap = pulse_ms - previous if previous is not None else None
    combo = (min(999, state['combo']+1) if live and gap is not None and
             300 <= gap <= 1333 else 0)
    scaled = _yield_scaled(upgrades, skills, state['cores'], combo)
    reward, fraction = divmod(scaled + state['torque_fraction'], 100)
    con.execute('''UPDATE forge_state SET
       torque=MIN(?,torque+?), run_revs=run_revs+1,
       total_game_revs=total_game_revs+1,
       run_earned=MIN(?,run_earned+?), total_earned=MIN(?,total_earned+?),
       last_live_pulse_ms=?, combo=?, torque_fraction=? WHERE device_id=?''',
       (MAX_BALANCE, reward, MAX_BALANCE, reward, MAX_BALANCE, reward,
        pulse_ms if live else None, combo, fraction, device))


def _cost(upgrade: tuple, level: int, discount: int) -> int:
    # Explicit rational integer power, never float overflow.
    base, n, d = upgrade[3], upgrade[4], upgrade[5]
    raw = base * n**level // d**level
    return max(1, raw * max(50, 100 - discount) // 100)


def state(device: str) -> dict:
    store._id(device, 'device_id')
    with store.db() as con:
        _ensure(con, device)
        state_row = con.execute('SELECT * FROM forge_state WHERE device_id=?', (device,)).fetchone()
        u = _levels(con, device, 'forge_upgrades', 'item_id')
        s = _levels(con, device, 'forge_skills', 'skill_id')
        progress = con.execute('SELECT COALESCE(MAX(number),0) FROM forge_prestiges WHERE device_id=?', (device,)).fetchone()[0]
    row = dict(state_row)
    available = row['run_revs'] // POINT_EVERY_REVS - row['skill_spent']
    discount = 5 * s.get('blueprint', 0)
    upgrades = [
        {'id': key, 'name': name, 'description': desc, 'level': u.get(key, 0),
         'max_level': max_lvl,
         'cost': _cost(meta, u.get(key, 0), discount) if u.get(key, 0) < max_lvl else None,
         'can_buy': u.get(key, 0) < max_lvl and row['torque'] >= _cost(meta, u.get(key, 0), discount)}
        for meta in UPGRADES
        for key, name, desc, _base, _n, _d, max_lvl, _add, _pct in [meta]
    ]
    skills = []
    for key, branch, name, desc, cap, req, *_ in SKILLS:
        level = s.get(key, 0)
        meets = (not req or s.get(req[0], 0) >= req[1])
        skills.append({'id': key, 'branch': branch, 'name': name, 'description': desc,
                       'level': level, 'max_level': cap, 'prerequisite':
                       None if req is None else f'{SKILL_BY_ID[req[0]][2]} Lv {req[1]}',
                       'unlocked': bool(meets), 'can_learn': bool(meets and level < cap and available >= 1)})
    row.update({
        'torque_per_rev': round(_yield_scaled(u, s, row['cores'], row['combo']) / 100, 2),
        'skill_points_available': available,
        'skill_points_earned': row['run_revs'] // POINT_EVERY_REVS,
        'skill_points_every_revs': POINT_EVERY_REVS,
        'next_skill_point_at': (row['run_revs']//POINT_EVERY_REVS+1)*POINT_EVERY_REVS,
        'upgrades': upgrades, 'skills': skills,
        'prestige_available': row['run_revs'] >= PRESTIGE_MIN_REVS,
        'prestige_min_revs': PRESTIGE_MIN_REVS,
        'next_prestige_cores': max(1, min(20, row['run_revs'] // PRESTIGE_MIN_REVS)),
        'no_idle_earnings': True, 'prestige_history_count': progress,
    })
    return row


def purchase(device: str, item: str) -> dict:
    store._id(device, 'device_id')
    if item not in UPGRADE_BY_ID:
        raise ValueError('Unknown upgrade')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con, device)
        row = con.execute('SELECT torque FROM forge_state WHERE device_id=?', (device,)).fetchone()
        u = con.execute('SELECT level FROM forge_upgrades WHERE device_id=? AND item_id=?',
                        (device, item)).fetchone()
        level = u['level'] if u else 0
        meta = UPGRADE_BY_ID[item]
        if level >= meta[6]:
            raise ValueError('Upgrade already at maximum level')
        skills = _levels(con, device, 'forge_skills', 'skill_id')
        price = _cost(meta, level, skills.get('blueprint', 0) * 5)
        if row['torque'] < price:
            raise ValueError('Not enough torque. Pedal to earn more!')
        con.execute('UPDATE forge_state SET torque=torque-? WHERE device_id=?', (price, device))
        con.execute('''INSERT INTO forge_upgrades(device_id,item_id,level) VALUES(?,?,1)
            ON CONFLICT(device_id,item_id) DO UPDATE SET level=level+1''', (device, item))
    return state(device)


def learn(device: str, skill: str) -> dict:
    store._id(device, 'device_id')
    if skill not in SKILL_BY_ID:
        raise ValueError('Unknown skill')
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con, device)
        current = con.execute('SELECT run_revs,skill_spent FROM forge_state WHERE device_id=?',
                              (device,)).fetchone()
        skills = _levels(con, device, 'forge_skills', 'skill_id')
        meta = SKILL_BY_ID[skill]
        level = skills.get(skill, 0)
        if level >= meta[4]:
            raise ValueError('Skill already at maximum level')
        req = meta[5]
        if req and skills.get(req[0], 0) < req[1]:
            raise ValueError('Unlock its prerequisite skill first')
        if current['run_revs']//POINT_EVERY_REVS <= current['skill_spent']:
            raise ValueError('No free skill points. Pedal to earn more!')
        con.execute('UPDATE forge_state SET skill_spent=skill_spent+1 WHERE device_id=?', (device,))
        con.execute('''INSERT INTO forge_skills(device_id,skill_id,level) VALUES(?,?,1)
            ON CONFLICT(device_id,skill_id) DO UPDATE SET level=level+1''', (device, skill))
    return state(device)


def prestige(device: str, now_ms: int | None = None) -> dict:
    store._id(device, 'device_id')
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        _ensure(con, device)
        row = con.execute('SELECT * FROM forge_state WHERE device_id=?', (device,)).fetchone()
        if row['run_revs'] < PRESTIGE_MIN_REVS:
            raise ValueError(f'Prestige requires {PRESTIGE_MIN_REVS:,} revolutions this run')
        cores = max(1, min(20, row['run_revs'] // PRESTIGE_MIN_REVS))
        con.execute('''INSERT INTO forge_prestiges
            (device_id,number,earned_cores,previous_run_revs,previous_run_earned,at_ms)
            VALUES(?,?,?,?,?,?)''',
            (device, row['prestiges']+1, cores, row['run_revs'], row['run_earned'], now_ms))
        con.execute('''UPDATE forge_state SET torque=0,run_revs=0,run_earned=0,
            prestiges=prestiges+1,cores=cores+?,skill_spent=0,
            last_live_pulse_ms=NULL,combo=0,torque_fraction=0 WHERE device_id=?''', (cores, device))
        con.execute('DELETE FROM forge_upgrades WHERE device_id=?', (device,))
        con.execute('DELETE FROM forge_skills WHERE device_id=?', (device,))
    return state(device)
