"""SQLite event journal. MQTT ACKs must only be sent AFTER ingest() returns."""
from __future__ import annotations

import os
import json
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

DB_PATH = os.getenv("DB_PATH", "/data/pedals.sqlite3")
LOCAL_TZ = ZoneInfo(os.getenv("TZ", "Europe/Budapest"))
VALID_ID = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")
SESSION_GAP_MS = 180_000
MAX_BATCH = 256

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    device_id TEXT NOT NULL,
    seq INTEGER NOT NULL CHECK(seq > 0),
    boot_id TEXT NOT NULL,
    event_time_ms INTEGER NOT NULL,
    uptime_ms INTEGER,
    received_ms INTEGER NOT NULL,
    time_quality TEXT NOT NULL CHECK(time_quality IN ('device','received')),
    PRIMARY KEY (device_id, seq)
);
CREATE INDEX IF NOT EXISTS events_time ON events(device_id, event_time_ms);
CREATE TABLE IF NOT EXISTS minute_stats (
    device_id TEXT NOT NULL,
    minute_utc_ms INTEGER NOT NULL,
    revs INTEGER NOT NULL,
    PRIMARY KEY(device_id, minute_utc_ms)
);
CREATE TABLE IF NOT EXISTS day_stats (
    device_id TEXT NOT NULL,
    day_local TEXT NOT NULL,
    revs INTEGER NOT NULL,
    PRIMARY KEY(device_id, day_local)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    started_ms INTEGER NOT NULL,
    ended_ms INTEGER NOT NULL,
    revs INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_by_device ON sessions(device_id, ended_ms DESC);
CREATE TABLE IF NOT EXISTS achievements (
    device_id TEXT NOT NULL,
    achievement_id TEXT NOT NULL,
    unlocked_ms INTEGER NOT NULL,
    PRIMARY KEY(device_id, achievement_id)
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    recorded_revs INTEGER NOT NULL DEFAULT 0,
    reported_lifetime_revs INTEGER NOT NULL DEFAULT 0,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    last_pulse_ms INTEGER,
    current_session_id INTEGER,
    last_seq_seen INTEGER NOT NULL DEFAULT 0
);
"""


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def initialize() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.executescript(SCHEMA)
        from . import features
        features.initialize()
        from . import game
        game.initialize()
        # Backfill milestones when upgrading an existing v0.1 database.
        for row in con.execute("SELECT device_id FROM devices").fetchall():
            _award_unlocked(con, row[0], int(time.time() * 1000))


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > 2**63 - 1:
        raise ValueError(f"{label} must be an integer in [{minimum}, 2^63-1]")
    return value


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or not VALID_ID.fullmatch(value):
        raise ValueError(f"{label} must be 1–48 letters, numbers, - or _")
    return value


def validate(payload: object, topic_device: str, now_ms: int) -> dict:
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("Invalid event envelope or protocol version")
    device_id = _id(payload.get("device_id"), "device_id")
    if device_id != topic_device:
        raise ValueError("Device ID does not match MQTT topic")
    boot_id = _id(payload.get("boot_id"), "boot_id")
    batch_id = _id(payload.get("batch_id"), "batch_id")
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= MAX_BATCH:
        raise ValueError(f"events must be an array of 1–{MAX_BATCH} records")
    normalized = []
    seen = set()
    for e in raw_events:
        if not isinstance(e, dict):
            raise ValueError("Each event must be an object")
        seq = _int(e.get("seq"), "seq", minimum=1)
        if seq in seen:
            raise ValueError("Duplicate sequence number inside batch")
        seen.add(seq)
        uptime = e.get("uptime_ms")
        if uptime is not None:
            uptime = _int(uptime, "uptime_ms")
        pulse_time = e.get("t_ms")
        if pulse_time is None:
            timestamp, quality = now_ms, "received"
        else:
            timestamp = _int(pulse_time, "t_ms")
            if timestamp < 1577836800000 or timestamp > now_ms + 600_000:
                raise ValueError("t_ms outside supported epoch range")
            quality = "device"
        normalized.append((seq, timestamp, uptime, quality))
    reported = payload.get("lifetime_revs")
    if reported is not None:
        reported = _int(reported, "lifetime_revs")
    return {
        "device_id": device_id, "boot_id": boot_id, "batch_id": batch_id,
        "events": sorted(normalized, key=lambda item: item[0]),
        "lifetime_revs": reported,
    }


# Award rules deliberately depend only on persisted aggregate data, never on
# client-supplied "achievement" messages. Unlocked rows survive reboot/replay.
AWARDS = (
    # Original IDs remain unchanged. Every achievement is public and visible.
    ("first_spin", "First Spin", "Record your first revolution", "lifetime", 1, "🚴"),
    ("century", "Century Club", "100 lifetime revolutions", "lifetime", 100, "💯"),
    ("one_k", "Four-Digit Club", "1,000 lifetime revolutions", "lifetime", 1000, "⚡"),
    ("ten_k", "No Rollover", "10,000 lifetime revolutions. Take that, original LCD.", "lifetime", 10000, "♾️"),
    ("hundred_k", "Legendary Legs", "100,000 lifetime revolutions", "lifetime", 100000, "🏆"),
    ("daily_500", "Five Hundred", "500 revolutions in one day", "best_day", 500, "🌤️"),
    ("daily_2000", "Daily Dynamo", "2,000 revolutions in one day", "best_day", 2000, "🔥"),
    ("half_hour", "Half-Hour Hero", "30 minutes from first to last pulse in a session", "best_session_s", 1800, "⏱️"),
    ("streak_3", "Hat Trick", "Exercise on 3 consecutive days", "best_streak", 3, "🌱"),
    ("streak_7", "One-Week Wonder", "Exercise on 7 consecutive days", "best_streak", 7, "🌟"),
    # Visible expansion: lifetime ladder
    ("five_k", "Five Thousand Fury", "5,000 lifetime revolutions", "lifetime", 5000, "🔩"),
    ("twentyfive_k", "Pedal Addict", "25,000 lifetime revolutions", "lifetime", 25000, "🔋"),
    ("fifty_k", "Built Different", "50,000 lifetime revolutions", "lifetime", 50000, "🛠️"),
    ("quarter_million", "Human Dynamo", "250,000 lifetime revolutions", "lifetime", 250000, "⚙️"),
    ("half_million", "Half a Million", "500,000 lifetime revolutions", "lifetime", 500000, "🌌"),
    ("million", "Desk Tour de France", "1,000,000 lifetime revolutions", "lifetime", 1000000, "🚀"),
    ("two_million", "Crank Immortal", "2,000,000 lifetime revolutions", "lifetime", 2000000, "👑"),
    # Best daily total
    ("daily_3000", "Three Thousand Day", "3,000 revolutions in one day", "best_day", 3000, "🌞"),
    ("daily_5000", "Five Thousand Day", "5,000 revolutions in one day", "best_day", 5000, "🌋"),
    ("daily_7500", "Seven-Five", "7,500 revolutions in one day", "best_day", 7500, "💥"),
    ("daily_10000", "Five Digits Daily", "10,000 revolutions in one day", "best_day", 10000, "☄️"),
    # Sessions judged by validated counters
    ("session_2500", "Long Haul", "2,500 revolutions in one session", "best_session_revs", 2500, "🛤️"),
    ("session_3000", "The 3K Club", "3,000 revolutions in one session", "best_session_revs", 3000, "🚆"),
    ("session_5000", "Endurance Engine", "5,000 revolutions in one session", "best_session_revs", 5000, "⚗️"),
    ("cruise_control", "Cruise Control", "Maintain 60+ RPM for 20 minutes continuously", "best_steady_60_s", 1200, "🦾"),
    # Wall-clock session duration (distinct from measured moving time)
    ("session_hour", "Marathon Meeting", "60 minutes measured moving in one session", "best_moving_s", 3600, "🕰️"),
    ("session_two_hour", "Double Shift", "120 minutes from first to last pulse in one session", "best_session_s", 7200, "⌛"),
    ("session_three_hour", "Triple Shift", "180 minutes from first to last pulse in one session", "best_session_s", 10800, "🏛️"),
    # Streaks
    ("streak_14", "Unstoppable", "Exercise on 14 consecutive days", "best_streak", 14, "🎗️"),
    ("streak_21", "Habit Formed", "Exercise on 21 consecutive days", "best_streak", 21, "🌳"),
    ("streak_30", "Unbroken Chain", "Exercise on 30 consecutive days", "best_streak", 30, "🔗"),
    ("streak_60", "Two-Month Machine", "Exercise on 60 consecutive days", "best_streak", 60, "🦿"),
    ("streak_100", "Century Streak", "Exercise on 100 consecutive days", "best_streak", 100, "🏅"),
    ("streak_365", "One Year, One Bike", "Exercise on 365 consecutive days", "best_streak", 365, "🎆"),
    # Measured moving time only, available after the v0.3 migration
    ("moving_hour", "Hour in Motion", "60 minutes of measured moving time", "total_moving_s", 3600, "⏲️"),
    ("moving_5hour", "Five Hours On", "5 hours of measured moving time", "total_moving_s", 18000, "🎽"),
    ("moving_20hour", "Twenty-Hour Cyclist", "20 hours of measured moving time", "total_moving_s", 72000, "🧭"),
    ("moving_100hour", "Hundred-Hour Engine", "100 hours of measured moving time", "total_moving_s", 360000, "🗻"),
    # Sampled cadence, not isolated raw electrical edges
    ("rpm_100", "Triple Digits", "Reach 100 sampled RPM", "best_rpm", 100, "💨"),
    ("rpm_120", "Turbo Legs", "Reach 120 sampled RPM", "best_rpm", 120, "🌀"),
)
assert len(AWARDS) == 40


def _achievement_metrics(con: sqlite3.Connection, device: str) -> dict:
    d = con.execute("SELECT recorded_revs,reported_lifetime_revs FROM devices WHERE device_id=?",
                    (device,)).fetchone()
    lifetime = max(d[0], d[1]) if d else 0
    best_day = con.execute("SELECT COALESCE(MAX(revs),0) FROM day_stats WHERE device_id=?",
                           (device,)).fetchone()[0]
    session = con.execute("SELECT COALESCE(MAX((ended_ms-started_ms)/1000),0) FROM sessions WHERE device_id=?",
                          (device,)).fetchone()[0]
    days = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in con.execute(
        "SELECT day_local FROM day_stats WHERE device_id=? AND revs>0 ORDER BY day_local", (device,))]
    best_streak = streak = 0
    previous = None
    for day in days:
        streak = streak + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best_streak = max(best_streak, streak)
        previous = day
    best_session_revs = con.execute('SELECT COALESCE(MAX(revs),0) FROM sessions WHERE device_id=?',
                                    (device,)).fetchone()[0]
    moving = con.execute('SELECT COALESCE(SUM(moving_ms),0) FROM sessions WHERE device_id=?',
                         (device,)).fetchone()[0]
    best_rpm = con.execute('SELECT COALESCE(MAX(peak_rpm),0) FROM sessions WHERE device_id=?',
                           (device,)).fetchone()[0]
    best_moving = con.execute('SELECT COALESCE(MAX(moving_ms),0) FROM sessions WHERE device_id=?',
                              (device,)).fetchone()[0]
    best_steady = con.execute('SELECT COALESCE(MAX(max_steady_60_ms),0) FROM sessions WHERE device_id=?',
                              (device,)).fetchone()[0]
    return {"lifetime": lifetime, "best_day": best_day,
            "best_session_s": session, "best_streak": best_streak,
            "best_session_revs": best_session_revs, "total_moving_s": moving/1000,
            "best_moving_s": best_moving/1000, "best_steady_60_s": best_steady/1000,
            "best_rpm": best_rpm}


def _award_unlocked(con: sqlite3.Connection, device: str, unlocked_ms: int, notify: bool = False) -> None:
    metrics = _achievement_metrics(con, device)
    for key, name, _desc, category, target, emoji in AWARDS:
        if metrics[category] >= target:
            inserted = con.execute("INSERT OR IGNORE INTO achievements VALUES(?,?,?)",
                                   (device, key, unlocked_ms)).rowcount
            if inserted and notify:
                payload = json.dumps({'event':'achievement_unlocked', 'event_key':f'achievement:{key}',
                                      'device_id':device, 'occurred_ms':unlocked_ms,
                                      'achievement':{'id':key,'name':name,'icon':emoji}},
                                     ensure_ascii=False, separators=(',',':'))
                con.execute('INSERT OR IGNORE INTO notification_outbox '
                            '(device_id,event_key,payload,created_ms) VALUES(?,?,?,?)',
                            (device, f'achievement:{key}', payload, unlocked_ms))


def _award_tier(category: str, target: int) -> str:
    thresholds = {
        'lifetime': (1000, 10000, 100000),
        'best_day': (2000, 5000, 10000),
        'best_session_revs': (2500, 3000, 5000),
        'best_session_s': (1800, 3600, 7200),
        'best_moving_s': (1800, 3600, 7200),
        'best_steady_60_s': (300, 900, 1200),
        'best_streak': (7, 30, 100),
        'total_moving_s': (3600, 18000, 72000),
        'best_rpm': (60, 100, 120),
    }
    silver, gold, diamond = thresholds[category]
    return 'diamond' if target >= diamond else 'gold' if target >= gold else 'silver' if target >= silver else 'bronze'


def achievements(device: str) -> dict:
    _id(device, "device_id")
    with db() as con:
        metrics = _achievement_metrics(con, device)
        unlocked = {row[0]: row[1] for row in con.execute(
            "SELECT achievement_id,unlocked_ms FROM achievements WHERE device_id=?", (device,))}
    return {"device_id": device, "unlocked_count": len(unlocked), "total_count": len(AWARDS),
            "achievements": [
                {"id": key, "name": name, "description": desc, "icon": emoji,
                 "unlocked_ms": unlocked.get(key), "progress": min(target, metrics[category]),
                 "target": target, "series": category,
                 "tier": _award_tier(category, target)}
                for key, name, desc, category, target, emoji in AWARDS
            ]}


def ingest(payload: object, topic_device: str, now_ms: int | None = None) -> dict:
    """Atomic batch processing. Replayed (device_id, seq) pairs are ignored."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    p = validate(payload, topic_device, now_ms)
    device = p["device_id"]
    inserted = 0
    with db() as con:
        con.execute("PRAGMA synchronous=FULL")
        con.execute("BEGIN IMMEDIATE")
        con.execute("""INSERT OR IGNORE INTO devices(device_id,first_seen_ms,last_seen_ms)
                    VALUES(?,?,?)""", (device, now_ms, now_ms))
        state = con.execute("""SELECT last_pulse_ms,current_session_id FROM devices
                               WHERE device_id=?""", (device,)).fetchone()
        last_pulse = state["last_pulse_ms"]
        session_id = state["current_session_id"]
        last_seq = 0
        for seq, ts, uptime, quality in p["events"]:
            last_seq = max(last_seq, seq)
            result = con.execute("""INSERT OR IGNORE INTO events
                (device_id,seq,boot_id,event_time_ms,uptime_ms,received_ms,time_quality)
                VALUES(?,?,?,?,?,?,?)""", (device, seq, p["boot_id"], ts, uptime, now_ms, quality))
            if result.rowcount == 0:
                continue
            inserted += 1
            # Exactly-once FORGE reward: only NEW, committed physical pulse events.
            # Same transaction as telemetry insertion; no game API can mint torque.
            from . import game
            game.on_event(con, device, ts, now_ms)
            minute = (ts // 60_000) * 60_000
            day = datetime.fromtimestamp(ts / 1000, LOCAL_TZ).date().isoformat()
            con.execute("""INSERT INTO minute_stats VALUES(?,?,1)
                           ON CONFLICT(device_id,minute_utc_ms) DO UPDATE SET revs=revs+1""",
                        (device, minute))
            con.execute("""INSERT INTO day_stats VALUES(?,?,1)
                           ON CONFLICT(device_id,day_local) DO UPDATE SET revs=revs+1""",
                        (device, day))
            # In-order ingest is normal (firmware sends oldest unsent first).
            # Late/out-of-order historical replays are still counted and stored,
            # but don't mutate the most recently built session.
            if last_pulse is None or ts >= last_pulse:
                if session_id is None or last_pulse is None or ts - last_pulse > SESSION_GAP_MS:
                    cur = con.execute("""INSERT INTO sessions(device_id,started_ms,ended_ms,revs)
                                         VALUES(?,?,?,1)""", (device, ts, ts))
                    session_id = cur.lastrowid
                else:
                    con.execute("""UPDATE sessions SET ended_ms=?, revs=revs+1 WHERE id=?""",
                                (ts, session_id))
                from . import features
                features.on_event(con, device, ts, last_pulse, session_id, now_ms)
                last_pulse = ts
        reported = p["lifetime_revs"]
        con.execute("""UPDATE devices SET recorded_revs=recorded_revs+?,
                      reported_lifetime_revs=MAX(reported_lifetime_revs,?),
                      last_seen_ms=MAX(last_seen_ms,?),
                      last_pulse_ms=?, current_session_id=?,
                      last_seq_seen=MAX(last_seq_seen,?) WHERE device_id=?""",
                    (inserted, reported or 0, now_ms, last_pulse, session_id, last_seq, device))
        _award_unlocked(con, device, now_ms, notify=True)
    return {
        "v": 1, "batch_id": p["batch_id"],
        "ack_sequences": [seq for seq, *_ in p["events"]],
        "inserted": inserted, "server_time_ms": now_ms,
    }


def summary(device: str, now_ms: int | None = None) -> dict:
    _id(device, "device_id")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    today = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ).date().isoformat()
    with db() as con:
        d = con.execute("SELECT * FROM devices WHERE device_id=?", (device,)).fetchone()
        day = con.execute("SELECT revs FROM day_stats WHERE device_id=? AND day_local=?",
                          (device, today)).fetchone()
        sess = con.execute("""SELECT started_ms,ended_ms,revs FROM sessions
                              WHERE device_id=? ORDER BY ended_ms DESC LIMIT 1""", (device,)).fetchone()
        recent = con.execute("""SELECT event_time_ms FROM events
                               WHERE device_id=? AND time_quality='device'
                               ORDER BY event_time_ms DESC LIMIT 6""", (device,)).fetchall()
    total = max(d["recorded_revs"], d["reported_lifetime_revs"]) if d else 0
    active = bool(sess and now_ms - sess["ended_ms"] < SESSION_GAP_MS and now_ms >= sess["ended_ms"])
    rpm = 0.0
    if len(recent) >= 2 and 0 <= now_ms - recent[0]["event_time_ms"] <= 6000:
        times = [recent[0]["event_time_ms"]]
        for event in recent[1:]:
            if times[-1] - event["event_time_ms"] > 6000:
                break
            times.append(event["event_time_ms"])
        if len(times) >= 2 and times[0] > times[-1]:
            rpm = round(min(300, (len(times) - 1) * 60_000 / (times[0] - times[-1])), 1)
    return {
        "device_id": device,
        "recorded_revolutions": d["recorded_revs"] if d else 0,
        "lifetime_revolutions": total,
        "unlogged_revolutions": max(0, total - (d["recorded_revs"] if d else 0)),
        "today_revolutions": day["revs"] if day else 0,
        "live_rpm": rpm,
        "last_event_ms": d["last_pulse_ms"] if d else None,
        "last_seen_ms": d["last_seen_ms"] if d else None,
        "session_active": active,
        "session_revolutions": sess["revs"] if sess else 0,
        "session_started_ms": sess["started_ms"] if sess else None,
        "session_ended_ms": sess["ended_ms"] if sess else None,
        "session_duration_s": max(0, ((now_ms if active else sess["ended_ms"]) - sess["started_ms"]) // 1000) if sess else 0,
        "server_time_ms": now_ms,
    }


def history(device: str, period: str, now_ms: int | None = None) -> dict:
    _id(device, "device_id")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    with db() as con:
        if period == "24h":
            start = now_ms - 86_400_000
            rows = con.execute("""SELECT minute_utc_ms AS bucket, revs
                FROM minute_stats WHERE device_id=? AND minute_utc_ms>=? ORDER BY bucket""",
                (device, start)).fetchall()
            points = [{"x": r["bucket"], "y": r["revs"]} for r in rows]
        elif period == "7d":
            start = now_ms - 7 * 86_400_000
            rows = con.execute("""SELECT (minute_utc_ms/3600000)*3600000 AS bucket,
                SUM(revs) AS revs FROM minute_stats
                WHERE device_id=? AND minute_utc_ms>=?
                GROUP BY bucket ORDER BY bucket""", (device, start)).fetchall()
            points = [{"x": r["bucket"], "y": r["revs"]} for r in rows]
        elif period == "30d":
            start = datetime.fromtimestamp((now_ms - 30 * 86_400_000) / 1000, LOCAL_TZ).date().isoformat()
            rows = con.execute("""SELECT day_local AS bucket,revs FROM day_stats
                WHERE device_id=? AND day_local>=? ORDER BY bucket""", (device, start)).fetchall()
            points = [{"x": r["bucket"], "y": r["revs"]} for r in rows]
        elif period in ("1y", "all"):
            start = datetime.fromtimestamp((now_ms - 366 * 86_400_000) / 1000, LOCAL_TZ).date().isoformat()
            if period == "1y":
                rows = con.execute("""SELECT substr(day_local,1,7) AS bucket,SUM(revs) AS revs
                    FROM day_stats WHERE device_id=? AND day_local>=?
                    GROUP BY bucket ORDER BY bucket""", (device, start)).fetchall()
            else:
                rows = con.execute("""SELECT substr(day_local,1,7) AS bucket,SUM(revs) AS revs
                    FROM day_stats WHERE device_id=? GROUP BY bucket ORDER BY bucket""", (device,)).fetchall()
            points = [{"x": r["bucket"], "y": r["revs"]} for r in rows]
        else:
            raise ValueError("Period must be 24h, 7d, 30d, 1y or all")
    # Always return regularly spaced buckets. Missing buckets mean zero activity,
    # not 'remove this time from the horizontal axis'.
    by_x = {p["x"]: p["y"] for p in points}
    if period in ("24h", "7d"):
        width_ms = 60_000 if period == "24h" else 3_600_000
        end = (now_ms // width_ms) * width_ms
        count = 1440 if period == "24h" else 168
        points = [{"x": t, "y": by_x.get(t, 0)}
                  for t in range(end - (count - 1) * width_ms, end + width_ms, width_ms)]
    elif period == "30d":
        from datetime import timedelta
        end_day = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ).date()
        points = [{"x": (end_day - timedelta(days=i)).isoformat(),
                   "y": by_x.get((end_day - timedelta(days=i)).isoformat(), 0)}
                  for i in range(29, -1, -1)]
    elif period in ("1y", "all"):
        end_date = datetime.fromtimestamp(now_ms / 1000, LOCAL_TZ).date()
        end_month = end_date.year * 12 + end_date.month - 1
        if period == "1y":
            first_month = end_month - 11
        else:
            first_month = min((int(k[:4]) * 12 + int(k[5:7]) - 1 for k in by_x), default=end_month)
        points = [{"x": f"{m//12:04d}-{m%12+1:02d}",
                   "y": by_x.get(f"{m//12:04d}-{m%12+1:02d}", 0)}
                  for m in range(first_month, end_month + 1)]
    return {"device_id": device, "period": period, "points": points}


def recent_sessions(device: str, limit: int = 15) -> list[dict]:
    _id(device, "device_id")
    with db() as con:
        rows = con.execute("""SELECT started_ms,ended_ms,revs FROM sessions
                              WHERE device_id=? ORDER BY ended_ms DESC LIMIT ?""",
                           (device, max(1, min(limit, 100)))).fetchall()
    return [dict(row) for row in rows]


def export_csv_rows(device: str):
    """On-demand streaming export; no entire lifetime loaded into memory."""
    import csv
    import io
    _id(device, "device_id")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["device_id", "seq", "boot_id", "event_time_ms", "uptime_ms", "received_ms", "time_quality"])
    yield buffer.getvalue()
    with db() as con:
        cur = con.execute("""SELECT device_id,seq,boot_id,event_time_ms,uptime_ms,received_ms,time_quality
                             FROM events WHERE device_id=? ORDER BY seq""", (device,))
        while batch := cur.fetchmany(1024):
            buffer.seek(0)
            buffer.truncate(0)
            for row in batch:
                writer.writerow(tuple(row))
            yield buffer.getvalue()
