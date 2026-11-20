"""v0.3 additive migration, persistence, chart limits and achievement-safe quests."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import store, features

DEVICE = 'bike-001'


@pytest.fixture(autouse=True)
def sandbox_db(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DB_PATH', str(tmp_path / 'pedal.sqlite3'))
    store.initialize()


def send(seq, timestamp_ms, now_ms=None):
    now_ms = timestamp_ms if now_ms is None else now_ms
    return store.ingest({'v': 1, 'device_id': DEVICE, 'boot_id': 'boot_test',
                         'batch_id': f'batch_{seq}', 'lifetime_revs': seq,
                         'events': [{'seq': seq, 't_ms': timestamp_ms}]}, DEVICE, now_ms)


def test_defaults_goals_heatmap_and_calibration():
    now = int(time.time() * 1000)
    state = features.dashboard_features(DEVICE, now)
    assert state['goals']['daily']['target'] == 2000
    assert state['adventure']['distance_km'] == 0
    assert len(state['heatmap']) == 365
    assert state['energy_kcal_estimate'] is None
    assert state['rpg']['level'] == 1
    send(1, now)
    saved = features.change_preferences(DEVICE, {'daily_goal': 1500, 'meters_per_rev': 1.25,
                                                  'weight_kg': 90.0})
    assert saved['daily_goal'] == 1500
    assert saved['weight_kg'] == 90.0
    assert features.dashboard_features(DEVICE, now)['adventure']['distance_km'] == .001
    store.initialize()
    assert features.preferences(DEVICE)['daily_goal'] == 1500
    assert features.dashboard_features(DEVICE, now)['goals']['daily']['value'] == 1


@pytest.mark.parametrize('changes', [
    {'daily_goal': False}, {'meters_per_rev': -4}, {'weight_kg': 0},
    {'daily_goal': '2000'}, {'unknown': 1}, {'meters_per_rev': float('nan')},
    {'target_rpm': 1000}, {'weekly_goal': 0}, {},
])
def test_settings_reject_bad_values(changes):
    with pytest.raises(ValueError):
        features.change_preferences(DEVICE, changes)
    assert features.preferences(DEVICE) == features.DEFAULTS


def test_cadence_chart_bounded_and_deduplicated():
    now = int(time.time() * 1000)
    base = now // 5000 * 5000
    for seq in range(1, 8):
        send(seq, base - 3000 + 100 * seq, base + 1000)
    replay = send(7, base - 2300, base + 1000)
    assert replay['inserted'] == 0
    chart = features.cadence_chart(DEVICE, 5, base + 1000)
    assert len(chart['points']) == 60
    assert sum(p['rpm'] for p in chart['points']) == 7 * 12
    with pytest.raises(ValueError):
        features.cadence_chart(DEVICE, 25)


def test_cadence_challenge_persists_and_dedup_does_not_advance():
    now = int(time.time() * 1000)
    features.start_challenge(DEVICE, 60, 15, now - 500)
    for seq in range(1, 17):
        t = now + (seq - 1) * 1000
        result = send(seq, t, t)
        assert result['inserted'] == 1
    state = features.challenge_state(DEVICE)
    assert state['current']['status'] == 'completed'
    assert state['current']['best_ms'] >= 15000
    assert state['completed_count'] == 1
    send(16, now + 15_000, now + 15_000)
    assert features.challenge_state(DEVICE)['completed_count'] == 1
    assert features.dashboard_features(DEVICE, now + 15_000)['rpg']['xp'] >= 250
    store.initialize()
    assert features.challenge_state(DEVICE)['current']['status'] == 'completed'


def test_challenge_slow_pedaling_resets_and_offline_replays_ignored():
    now = int(time.time() * 1000)
    features.start_challenge(DEVICE, 80, 15, now - 1000)
    send(1, now)
    send(2, now + 1000, now + 1000)  # 60 RPM, too slow
    assert features.challenge_state(DEVICE)['current']['streak_ms'] == 0
    send(3, now + 1600, now + 1600)
    assert features.challenge_state(DEVICE)['current']['streak_ms'] == 600
    send(4, now + 2200, now + 180_000)  # old event, e.g. EEPROM replay
    assert features.challenge_state(DEVICE)['current']['streak_ms'] == 600
    assert features.challenge_state(DEVICE)['current']['status'] == 'active'
    features.stop_challenge(DEVICE)
    assert features.challenge_state(DEVICE)['current']['status'] == 'cancelled'


def test_moving_time_is_idempotent_and_old_sessions_still_usable():
    now = int(time.time() * 1000)
    send(1, now)
    send(2, now + 1000, now + 1000)
    send(2, now + 1000, now + 1000)
    state = features.dashboard_features(DEVICE, now + 1000)
    assert state['records']['moving_minutes_since_upgrade'] == pytest.approx(.0, abs=.1)
    assert state['recent_sessions'][0]['moving_ms'] == 1000
    assert state['recent_sessions'][0]['average_rpm'] == pytest.approx(60)


def test_level_curve_borders():
    assert features._level(0)[0] == 1
    assert features._level(249)[0] == 1
    assert features._level(250)[0] == 2
    assert features._level(749)[0] == 2
    assert features._level(750)[0] == 3
    assert features._level(50000000)[0] > 500


def test_achievement_webhook_outbox_exactly_once_and_retry(monkeypatch):
    now = int(time.time()*1000)
    sent=[]
    send(1, now)
    send(1, now)
    with store.db() as con:
        rows=con.execute('SELECT event_key,payload,delivered_ms FROM notification_outbox').fetchall()
        assert len(rows)==1
        assert rows[0]['event_key']=='achievement:first_spin'
        assert rows[0]['delivered_ms'] is None

    class FakeResponse:
        status=204
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False

    def fake_urlopen(req, timeout):
        sent.append(req.data)
        return FakeResponse()
    monkeypatch.setattr(features.urllib.request, 'urlopen', fake_urlopen)
    assert features.deliver_notifications('http://ha.local/webhook/secret', now)==1
    assert features.deliver_notifications('http://ha.local/webhook/secret', now+1000)==0
    assert len(sent)==1
    store.initialize()  # Existing unlocks must not create a second notification.
    with store.db() as con:
        assert con.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0]==1
        assert con.execute('SELECT delivered_ms FROM notification_outbox').fetchone()[0]==now


def test_webhook_failure_retains_queue_and_backoff(monkeypatch):
    now=int(time.time()*1000)
    send(1, now)
    def fail(_req,timeout):
        raise OSError('test failure')
    monkeypatch.setattr(features.urllib.request, 'urlopen',fail)
    assert features.deliver_notifications('http://ha.local/webhook/secret',now)==0
    with store.db() as con:
        row=con.execute('SELECT attempts,next_attempt_ms,delivered_ms FROM notification_outbox').fetchone()
        assert row['attempts']==1
        assert row['next_attempt_ms']>now
        assert row['delivered_ms'] is None


def test_legacy_v02_sessions_gain_columns_without_losing_rows(monkeypatch, tmp_path):
    legacy = str(tmp_path / 'legacy.sqlite3')
    monkeypatch.setattr(store, 'DB_PATH', legacy)
    import sqlite3
    with sqlite3.connect(legacy) as con:
        con.execute('''CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL, started_ms INTEGER NOT NULL,
            ended_ms INTEGER NOT NULL,revs INTEGER NOT NULL)''')
        con.execute('INSERT INTO sessions(device_id,started_ms,ended_ms,revs) VALUES(?,?,?,?)',
                    (DEVICE, 1000, 2000, 102))
    store.initialize()
    with store.db() as con:
        row = con.execute('SELECT revs,moving_ms,peak_rpm FROM sessions WHERE device_id=?',
                          (DEVICE,)).fetchone()
        assert (row['revs'], row['moving_ms'], row['peak_rpm']) == (102, 0, 0)
        assert con.execute("SELECT name FROM sqlite_master WHERE name='notification_outbox'").fetchone()
