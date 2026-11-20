"""PEDAL v0.4 game ledger tests: the real MQTT/SQLite ingest path only."""
from __future__ import annotations
import sys
import time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import store, game

DEVICE='bike-001'

@pytest.fixture(autouse=True)
def db_fixture(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'pedal.sqlite3'))
    store.initialize()


def send(sequences, now=None, initial=None, batch='batch_1'):
    now = now if now is not None else int(time.time()*1000)
    initial = initial if initial is not None else now-(len(sequences)-1)*1000
    return store.ingest({'v':1,'device_id':DEVICE,'boot_id':'testboot',
        'batch_id':batch, 'events':[{'seq':n,'t_ms':initial+i*1000}
            for i,n in enumerate(sequences)]},DEVICE,now)


def test_no_credit_for_pre_migration_history_and_durable_dedup():
    # Pretend existing pre-v0.4 history and milestones have already been logged.
    with store.db() as c:
        c.execute("INSERT INTO devices(device_id,recorded_revs,reported_lifetime_revs,first_seen_ms,last_seen_ms) VALUES(?,5263,5263,1,1)",(DEVICE,))
        c.execute("INSERT INTO events(device_id,seq,boot_id,event_time_ms,received_ms,time_quality) VALUES(?,?,?,?,?,'device')", (DEVICE,100,'boot',1700000000000,1700000000000))
    # Migration/restart does not replay old records into game currency.
    store.initialize()
    assert game.state(DEVICE)['torque']==0
    now=int(time.time()*1000)
    payload=send([101,102],now,now-1000)
    assert payload['inserted']==2
    assert game.state(DEVICE)['torque']==2
    assert send([101,102],now,now-1000)['inserted']==0
    assert game.state(DEVICE)['torque']==2
    store.initialize()
    assert game.state(DEVICE)['total_game_revs']==2
    assert store.summary(DEVICE)['lifetime_revolutions']==5265


def test_purchase_cost_and_only_new_revolution_earns_new_rate():
    now=int(time.time()*1000)
    send(list(range(1,31)),now,now-29_000)
    assert game.state(DEVICE)['torque']==30
    after=game.purchase(DEVICE,'chain')
    assert after['torque']==15
    assert next(x for x in after['upgrades'] if x['id']=='chain')['level']==1
    assert after['torque_per_rev']==2
    send([31],now+1000,now+1000)
    assert game.state(DEVICE)['torque']==17
    send([31],now+1000,now+1000)
    assert game.state(DEVICE)['torque']==17
    with pytest.raises(ValueError): game.purchase(DEVICE,'quantum')
    assert game.state(DEVICE)['torque']==17


def test_points_tree_and_invalid_actions_are_atomic():
    now=int(time.time()*1000)
    send(list(range(1,151)),now,now-149_000)
    assert game.state(DEVICE)['skill_points_available']==1
    with pytest.raises(ValueError): game.learn(DEVICE,'transmission')
    assert game.state(DEVICE)['skill_points_available']==1
    result=game.learn(DEVICE,'steel')
    assert result['skill_points_available']==0
    assert next(s for s in result['skills'] if s['id']=='steel')['level']==1
    with pytest.raises(ValueError): game.learn(DEVICE,'steel')
    with pytest.raises(ValueError): game.learn(DEVICE,'nonesuch')
    with pytest.raises(ValueError): game.purchase(DEVICE,'nonesuch')
    assert game.state(DEVICE)['skill_points_available']==0


def test_prestige_is_irreversible_only_for_game_and_cores_are_fractional():
    now=int(time.time()*1000)
    send(list(range(1,20)),now,now-18_000)
    with store.db() as c:
        c.execute("UPDATE forge_state SET run_revs=2000,torque=12345,run_earned=12345,skill_spent=1 WHERE device_id=?",(DEVICE,))
        c.execute("INSERT INTO forge_skills(device_id,skill_id,level) VALUES(?,?,1)",(DEVICE,'steel'))
        c.execute("INSERT INTO forge_upgrades(device_id,item_id,level) VALUES(?,?,1)",(DEVICE,'chain'))
    before=store.summary(DEVICE)['lifetime_revolutions']
    after=game.prestige(DEVICE,now+1000)
    assert after['run_revs']==0 and after['torque']==0
    assert after['cores']==1 and after['prestiges']==1
    assert after['skill_points_available']==0
    assert after['upgrades'][0]['level']==0
    assert after['torque_per_rev']==1.1  # fractions preserved, not rounded away
    assert store.summary(DEVICE)['lifetime_revolutions']==before
    with pytest.raises(ValueError): game.prestige(DEVICE,now+1001)
    # 10 revs at 1.10 yields precisely 11 units with carry.
    send(list(range(20,30)),now+11000,now+2000)
    assert game.state(DEVICE)['torque']==11
    assert game.state(DEVICE)['total_game_revs']==29
    store.initialize()
    assert game.state(DEVICE)['cores']==1


def test_all_achievements_public_and_backfilled_from_existing_aggregates():
    now=int(time.time()*1000)
    send([1],now)
    with store.db() as c:
        c.execute('UPDATE devices SET reported_lifetime_revs=50263 WHERE device_id=?',(DEVICE,))
        c.execute('INSERT INTO day_stats(device_id,day_local,revs) VALUES(?,?,?)',
                  (DEVICE,'2026-11-19',6000))
        c.execute('INSERT INTO sessions(device_id,started_ms,ended_ms,revs,moving_ms,peak_rpm) VALUES(?,?,?,?,?,?)',
                  (DEVICE,now-3700000,now,3500,3900000,135.1))
    store.initialize()
    a=store.achievements(DEVICE)
    assert a['total_count']==40
    assert len({x['id'] for x in a['achievements']})==40
    assert all(x['name'] and x['description'] and x['target']>0 and x['tier'] for x in a['achievements'])
    unlocked={x['id'] for x in a['achievements'] if x['unlocked_ms']}
    assert {'fifty_k','daily_5000','session_3000','session_hour','rpm_120','moving_hour'} <= unlocked
    assert 'quarter_million' not in unlocked
