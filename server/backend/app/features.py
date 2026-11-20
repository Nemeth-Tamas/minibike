"""PEDAL cockpit and gamification. Additive, SQLite-backed v0.3 features.

All telemetry remains owned by store.py. Features never replace the journal,
sequence deduplication or the MQTT application-level ACK contract.
"""
from __future__ import annotations

import math
import logging
import sqlite3
import urllib.request
from urllib.parse import urlsplit
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import store

TZ = ZoneInfo('Europe/Budapest')
DEFAULTS = {
    'daily_goal': 2000,
    'weekly_goal': 12000,
    'meters_per_rev': 0.30,  # fictional distance proxy, NOT wheel circumference
    'target_rpm': 70,
    'weight_kg': None,       # optional: do not assume someone's weight
}

# Fictional levels, not assertions about travel/geography.
DESTINATIONS = [
    ('Warm-up Lane', 0.25, 'First quarter-kilometre equivalent'),
    ('Copper Creek', 1.0, 'A tiny virtual countryside loop'),
    ('Pixel Pines', 2.5, 'A forest made of pixels'),
    ('Circuit Ridge', 5.0, 'The climb your desk never asked for'),
    ('Neon Coast', 10.0, 'A glowing imaginary coastline'),
    ('Infinite Highway', 25.0, 'The road keeps going'),
    ('Orbit Station', 50.0, 'Your pedals have left the atmosphere'),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    event_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    delivered_ms INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_ms INTEGER NOT NULL DEFAULT 0,
    UNIQUE(device_id, event_key)
);
CREATE INDEX IF NOT EXISTS notification_queue ON notification_outbox(delivered_ms,next_attempt_ms);
CREATE TABLE IF NOT EXISTS cadence_bands (
    device_id TEXT NOT NULL,
    band TEXT NOT NULL,
    samples INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(device_id, band)
);
CREATE TABLE IF NOT EXISTS bike_preferences (
    device_id TEXT PRIMARY KEY,
    daily_goal INTEGER NOT NULL DEFAULT 2000,
    weekly_goal INTEGER NOT NULL DEFAULT 12000,
    meters_per_rev REAL NOT NULL DEFAULT 0.30,
    target_rpm INTEGER NOT NULL DEFAULT 70,
    weight_kg REAL
);
CREATE TABLE IF NOT EXISTS cadence_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    target_rpm INTEGER NOT NULL,
    duration_s INTEGER NOT NULL,
    started_ms INTEGER NOT NULL,
    last_pulse_ms INTEGER,
    streak_ms INTEGER NOT NULL DEFAULT 0,
    best_ms INTEGER NOT NULL DEFAULT 0,
    finished_ms INTEGER,
    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS challenges_device ON cadence_challenges(device_id, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS challenge_one_active
  ON cadence_challenges(device_id) WHERE status='active';
"""


def initialize() -> None:
    with store.db() as con:
        con.executescript(SCHEMA)
        columns = {row[1] for row in con.execute('PRAGMA table_info(sessions)')}
        if 'moving_ms' not in columns:
            con.execute('ALTER TABLE sessions ADD COLUMN moving_ms INTEGER NOT NULL DEFAULT 0')
        if 'peak_rpm' not in columns:
            con.execute('ALTER TABLE sessions ADD COLUMN peak_rpm REAL NOT NULL DEFAULT 0')
        if 'steady_60_ms' not in columns:
            con.execute('ALTER TABLE sessions ADD COLUMN steady_60_ms INTEGER NOT NULL DEFAULT 0')
        if 'max_steady_60_ms' not in columns:
            con.execute('ALTER TABLE sessions ADD COLUMN max_steady_60_ms INTEGER NOT NULL DEFAULT 0')


def on_event(con: sqlite3.Connection, device: str, pulse_ms: int,
             previous_pulse_ms: int | None, session_id: int, now_ms: int) -> None:
    """Called exactly once for newly inserted, in-order events, IN the ingest TX."""
    interval = pulse_ms - previous_pulse_ms if previous_pulse_ms is not None else None
    if interval is not None and 180 <= interval <= 6000:
        instantaneous_rpm = min(250.0, 60000 / interval)
        con.execute('''UPDATE sessions SET moving_ms=moving_ms+?,
                     peak_rpm=MAX(peak_rpm,?) WHERE id=? AND device_id=?''',
                    (interval, round(instantaneous_rpm, 2), session_id, device))
        band = ('0–40' if instantaneous_rpm < 40 else '40–60' if instantaneous_rpm < 60
                else '60–80' if instantaneous_rpm < 80 else '80–100' if instantaneous_rpm < 100
                else '100–120' if instantaneous_rpm < 120 else '120+')
        con.execute('''INSERT INTO cadence_bands(device_id,band,samples) VALUES(?,?,1)
            ON CONFLICT(device_id,band) DO UPDATE SET samples=samples+1''',
                    (device, band))

    # A sustained 60 RPM metric is computed from accepted in-order intervals,
    # never from a one-off speed spike. 20 minutes must be continuous.
    if interval is not None and 180 <= interval <= 1000:
        con.execute('''UPDATE sessions SET steady_60_ms=steady_60_ms+?,
            max_steady_60_ms=MAX(max_steady_60_ms,steady_60_ms+?)
            WHERE id=? AND device_id=?''', (interval, interval, session_id, device))
    else:
        con.execute('UPDATE sessions SET steady_60_ms=0 WHERE id=? AND device_id=?',
                    (session_id, device))

    challenge = con.execute('''SELECT id,target_rpm,duration_s,started_ms,
        last_pulse_ms,streak_ms,best_ms FROM cadence_challenges
        WHERE device_id=? AND status='active' LIMIT 1''', (device,)).fetchone()
    if not challenge or pulse_ms < challenge['started_ms']:
        return
    # Only recent live events can advance a live cadence challenge. A delayed
    # offline EEPROM replay must never retroactively complete a timed workout.
    if abs(now_ms - pulse_ms) > 15_000:
        return
    previous = challenge['last_pulse_ms']
    elapsed = pulse_ms - previous if previous is not None else None
    if elapsed is not None and 180 <= elapsed <= (60000 / challenge['target_rpm']):
        streak = challenge['streak_ms'] + elapsed
    else:
        streak = 0
    best = max(challenge['best_ms'], streak)
    completed = streak >= challenge['duration_s'] * 1000
    con.execute('''UPDATE cadence_challenges SET last_pulse_ms=?,
        streak_ms=?, best_ms=?, status=?, finished_ms=? WHERE id=?''',
                (pulse_ms, streak, best, 'completed' if completed else 'active',
                 pulse_ms if completed else None, challenge['id']))


def preferences(device: str) -> dict:
    store._id(device, 'device_id')
    with store.db() as con:
        row = con.execute('SELECT * FROM bike_preferences WHERE device_id=?', (device,)).fetchone()
    return {k: row[k] if row is not None else v for k, v in DEFAULTS.items()}


def change_preferences(device: str, data: dict) -> dict:
    store._id(device, 'device_id')
    if not isinstance(data, dict) or not data or any(k not in DEFAULTS for k in data):
        raise ValueError('Specify one or more known preference fields')
    values = preferences(device)
    for key, value in data.items():
        if key == 'weight_kg':
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or not 25 <= value <= 300):
                raise ValueError('weight_kg must be null or 25–300')
        elif key == 'meters_per_rev':
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0.01 <= value <= 20):
                raise ValueError('meters_per_rev must be 0.01–20')
        else:
            limits = {'daily_goal': (1, 100000), 'weekly_goal': (1, 700000),
                      'target_rpm': (30, 180)}
            low, high = limits[key]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f'{key} must be an integer {low}–{high}')
        values[key] = value
    with store.db() as con:
        con.execute('''INSERT INTO bike_preferences
            (device_id,daily_goal,weekly_goal,meters_per_rev,target_rpm,weight_kg)
            VALUES(?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET
            daily_goal=excluded.daily_goal,weekly_goal=excluded.weekly_goal,
            meters_per_rev=excluded.meters_per_rev,target_rpm=excluded.target_rpm,
            weight_kg=excluded.weight_kg''',
            (device, *(values[k] for k in DEFAULTS)))
    return values


def start_challenge(device: str, target_rpm: int, duration_s: int,
                    now_ms: int | None = None) -> dict:
    store._id(device, 'device_id')
    if isinstance(target_rpm, bool) or not isinstance(target_rpm, int) or not 30 <= target_rpm <= 180:
        raise ValueError('target_rpm must be an integer between 30 and 180')
    if isinstance(duration_s, bool) or not isinstance(duration_s, int) or not 15 <= duration_s <= 3600:
        raise ValueError('duration_s must be an integer between 15 and 3600')
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    with store.db() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE cadence_challenges SET status='cancelled',finished_ms=? WHERE device_id=? AND status='active'",
                    (now_ms, device))
        con.execute('''INSERT INTO cadence_challenges
            (device_id,target_rpm,duration_s,started_ms,status)
            VALUES(?,?,?,?,'active')''', (device, target_rpm, duration_s, now_ms))
    return challenge_state(device)


def stop_challenge(device: str) -> dict:
    store._id(device, 'device_id')
    with store.db() as con:
        con.execute('''UPDATE cadence_challenges SET status='cancelled',finished_ms=?
            WHERE device_id=? AND status='active' ''', (int(time.time()*1000), device))
    return challenge_state(device)


def challenge_state(device: str) -> dict:
    store._id(device, 'device_id')
    with store.db() as con:
        row = con.execute('''SELECT * FROM cadence_challenges WHERE device_id=?
            ORDER BY id DESC LIMIT 1''', (device,)).fetchone()
        done = con.execute('''SELECT COUNT(*) FROM cadence_challenges
            WHERE device_id=? AND status='completed' ''', (device,)).fetchone()[0]
    return {'current': dict(row) if row is not None else None, 'completed_count': done}


def _level(xp: int) -> tuple[int, int, int]:
    # level n starts after 250*(n-1)*n/2 XP.
    level = (1 + math.isqrt(1 + 8 * xp // 250)) // 2
    level = max(1, level)
    while 250 * level * (level - 1) // 2 > xp:
        level -= 1
    while 250 * (level + 1) * level // 2 <= xp:
        level += 1
    return level, 250 * level * (level - 1) // 2, 250 * (level + 1) * level // 2


def dashboard_features(device: str, now_ms: int | None = None) -> dict:
    store._id(device, 'device_id')
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    today = datetime.fromtimestamp(now_ms / 1000, TZ).date()
    since = today - timedelta(days=364)
    prefs = preferences(device)
    with store.db() as con:
        daily = {row['day_local']: row['revs'] for row in con.execute(
            'SELECT day_local,revs FROM day_stats WHERE device_id=? AND day_local>=? ORDER BY day_local',
            (device, since.isoformat()))}
        best_day = con.execute('SELECT COALESCE(MAX(revs),0) FROM day_stats WHERE device_id=?', (device,)).fetchone()[0]
        best_session = con.execute('SELECT COALESCE(MAX(revs),0) FROM sessions WHERE device_id=?', (device,)).fetchone()[0]
        longest_session_ms = con.execute('SELECT COALESCE(MAX(ended_ms-started_ms),0) FROM sessions WHERE device_id=?', (device,)).fetchone()[0]
        best_rpm = con.execute('SELECT COALESCE(MAX(peak_rpm),0) FROM sessions WHERE device_id=?', (device,)).fetchone()[0]
        moving = con.execute('SELECT COALESCE(SUM(moving_ms),0) FROM sessions WHERE device_id=?', (device,)).fetchone()[0]
        rpm_bands = {row['band']: row['samples'] for row in con.execute(
            'SELECT band,samples FROM cadence_bands WHERE device_id=?', (device,))}
        unlocked = con.execute('SELECT COUNT(*) FROM achievements WHERE device_id=?', (device,)).fetchone()[0]
        session_count = con.execute('SELECT COUNT(*) FROM sessions WHERE device_id=?', (device,)).fetchone()[0]
        total = con.execute('SELECT recorded_revs,reported_lifetime_revs FROM devices WHERE device_id=?', (device,)).fetchone()
        completed = con.execute("SELECT COUNT(*) FROM cadence_challenges WHERE device_id=? AND status='completed'", (device,)).fetchone()[0]
        latest = con.execute('SELECT * FROM cadence_challenges WHERE device_id=? ORDER BY id DESC LIMIT 1', (device,)).fetchone()
        weekly = con.execute('SELECT COALESCE(SUM(revs),0) FROM day_stats WHERE device_id=? AND day_local>=?',
                             (device, (today-timedelta(days=6)).isoformat())).fetchone()[0]
        all_days = [date.fromisoformat(row[0]) for row in con.execute(
            'SELECT day_local FROM day_stats WHERE device_id=? AND revs>0 ORDER BY day_local', (device,))]
        last_sessions = [dict(r) for r in con.execute('''SELECT started_ms,ended_ms,revs,moving_ms,peak_rpm
            FROM sessions WHERE device_id=? ORDER BY ended_ms DESC LIMIT 12''', (device,))]
    lifetime = max(total['recorded_revs'], total['reported_lifetime_revs']) if total else 0
    day_total = daily.get(today.isoformat(), 0)
    streak = best_streak = 0
    previous = None
    for d in all_days:
        streak = streak+1 if previous and (d-previous).days == 1 else 1
        best_streak = max(streak, best_streak)
        previous = d
    current_streak = streak if previous and (today-previous).days <= 1 else 0
    xp = lifetime + unlocked * 150 + completed * 250
    level, level_start, next_level = _level(xp)
    distance_km = round(lifetime * prefs['meters_per_rev'] / 1000, 3)
    destinations = [{'name': name, 'km': km, 'description': desc,
                     'unlocked': distance_km >= km} for name, km, desc in DESTINATIONS]
    next_destination = next((x for x in destinations if not x['unlocked']), None)
    quests = [
        {'name': 'Today’s spins', 'progress': day_total, 'target': prefs['daily_goal'], 'icon': '🎯'},
        {'name': 'This week', 'progress': weekly, 'target': prefs['weekly_goal'], 'icon': '🗓️'},
        {'name': 'Next thousand', 'progress': lifetime % 1000, 'target': 1000, 'icon': '⚡'},
    ]
    # For achieved exact thousands, retain a full quest bar until the next spin.
    if lifetime > 0 and lifetime % 1000 == 0:
        quests[-1]['progress'] = 1000
    heatmap = [{'date': (since + timedelta(days=i)).isoformat(),
                'revs': daily.get((since + timedelta(days=i)).isoformat(), 0)} for i in range(365)]
    moving_minutes = round(moving / 60000, 1)
    energy = (round((2.8 * 3.5 * prefs['weight_kg'] / 200) * moving_minutes)
              if prefs['weight_kg'] is not None else None)
    for s in last_sessions:
        s['duration_s'] = max(0, (s['ended_ms'] - s['started_ms']) / 1000)
        s['average_rpm'] = (round((s['revs'] - 1) * 60000 / (s['ended_ms'] - s['started_ms']), 1)
                            if s['revs'] > 1 and s['ended_ms'] > s['started_ms'] else 0)
    return {
        'preferences': prefs,
        'goals': {'daily': {'value': day_total, 'target': prefs['daily_goal']},
                  'weekly': {'value': weekly, 'target': prefs['weekly_goal']}},
        'rpg': {'xp': xp, 'level': level, 'level_start_xp': level_start,
                'next_level_xp': next_level, 'completed_challenges': completed},
        'adventure': {'distance_km': distance_km, 'meters_per_rev': prefs['meters_per_rev'],
                      'destinations': destinations, 'next': next_destination},
        'records': {'best_day': best_day, 'best_session': best_session,
                    'longest_session_s': longest_session_ms / 1000,
                    'best_rpm_since_upgrade': round(best_rpm, 1), 'session_count': session_count,
                    'current_streak': current_streak, 'best_streak': best_streak,
                    'moving_minutes_since_upgrade': moving_minutes},
        'energy_kcal_estimate': energy,
        'cadence_distribution': [{'band': band, 'samples': rpm_bands.get(band, 0)}
                                 for band in ('0–40', '40–60', '60–80', '80–100', '100–120', '120+')],
        'heatmap': heatmap,
        'quests': quests,
        'recent_sessions': last_sessions,
        'challenge': {'current': dict(latest) if latest else None, 'completed_count': completed},
        'timezone': 'Europe/Budapest',
        'server_time_ms': now_ms,
    }


def cadence_chart(device: str, minutes: int = 5, now_ms: int | None = None) -> dict:
    """Only the last few minutes; never replay whole lifetime to the client."""
    store._id(device, 'device_id')
    if isinstance(minutes, bool) or minutes not in (5, 10, 15):
        raise ValueError('minutes must be 5, 10 or 15')
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    width = 5_000
    last = now_ms // width * width
    count = minutes * 60 // 5
    start = last - (count - 1) * width
    with store.db() as con:
        rows = con.execute('''SELECT (event_time_ms / ?) * ? AS bucket, COUNT(*) AS revs
            FROM events WHERE device_id=? AND time_quality='device'
            AND event_time_ms >= ? AND event_time_ms < ?
            GROUP BY bucket ORDER BY bucket''',
                           (width, width, device, start, last + width)).fetchall()
    values = {row['bucket']: row['revs'] for row in rows}
    return {'device_id': device, 'window_minutes': minutes, 'bucket_seconds': 5,
            'points': [{'x': x, 'rpm': values.get(x, 0) * 12}
                       for x in range(start, last + width, width)]}


LOG = logging.getLogger('pedal.webhooks')


def deliver_notifications(url: str, now_ms: int | None = None) -> int:
    """Best-effort outbound HA/n8n events, retried without blocking MQTT ACKs.

    Deliveries are at-least-once; the receiver should deduplicate event_key.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('PEDAL_WEBHOOK_URL must be an absolute HTTP(S) URL')
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    with store.db() as con:
        rows = con.execute("""SELECT id,payload,attempts FROM notification_outbox
            WHERE delivered_ms IS NULL AND next_attempt_ms <= ? ORDER BY id LIMIT 5""", (now_ms,)).fetchall()
    delivered = 0
    for row in rows:
        try:
            req = urllib.request.Request(url, row['payload'].encode('utf-8'), method='POST',
                                         headers={'Content-Type': 'application/json',
                                                  'User-Agent': 'PEDAL-Telemetry/0.3'})
            with urllib.request.urlopen(req, timeout=4) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f'Webhook HTTP {response.status}')
            with store.db() as con:
                con.execute('UPDATE notification_outbox SET delivered_ms=? WHERE id=? AND delivered_ms IS NULL',
                            (now_ms, row['id']))
            delivered += 1
        except Exception as exc:
            backoff = min(3600, 5 * (2 ** min(row['attempts'], 10))) * 1000
            with store.db() as con:
                con.execute("""UPDATE notification_outbox SET attempts=attempts+1,
                    next_attempt_ms=? WHERE id=? AND delivered_ms IS NULL""",
                            (now_ms + backoff, row['id']))
            LOG.warning('Optional achievement webhook failed (attempt %d): %s',
                        row['attempts'] + 1, type(exc).__name__)
    return delivered
