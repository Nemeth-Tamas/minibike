"""GEARBOUND v0.5: balance, persistence, combat security, relics, and migrations."""
from __future__ import annotations

import time
import pytest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app import store,game

DEVICE='bike-001'

@pytest.fixture(autouse=True)
def fresh(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'pedals.sqlite3'))
    store.initialize()


def send(seq, t=None, received=None):
    t=t if t is not None else int(time.time()*1000)
    received=received if received is not None else t
    return store.ingest(dict(v=1,device_id=DEVICE,boot_id='realbike',batch_id=f'packet_{seq}',
                             events=[dict(seq=seq,t_ms=t)]),DEVICE,received)


def test_enemy_combat_only_from_new_real_live_pulses_and_duplicate_safe():
    now=int(time.time()*1000)
    before=game.state(DEVICE)
    assert before['combat']['enemy']['name']=='Rust Rat'
    assert before['combat']['enemy_hp']==55
    assert send(1,now)['inserted']==1
    after=game.state(DEVICE)
    assert after['combat']['enemy_hp']==53
    assert after['torque']==1
    assert send(1,now)['inserted']==0
    assert game.state(DEVICE)['combat']==after['combat']
    assert game.state(DEVICE)['torque']==after['torque']
    # Reading/polling the dashboard is not an action and never fights enemies.
    for _ in range(5):
        assert game.state(DEVICE)['combat']['enemy_hp']==53


def test_offline_replays_get_torque_but_never_combat_or_combo():
    now=int(time.time()*1000)
    assert send(1,now-60000,now)['inserted']==1
    c=game.state(DEVICE)
    assert c['torque']==1 and c['combat']['enemy_hp']==55
    assert c['combat']['attacks']==0 and c['combo']==0


def test_victory_scrap_progression_and_second_currency():
    now=int(time.time()*1000)
    for seq in range(1,30):
        send(seq,now+seq*900)
    c=game.state(DEVICE)['combat']
    assert c['kills_total']==1 and c['scrap']>=10
    assert c['wave']==2 and c['enemy']['name']=='Loose Bearing'
    assert c['relics']==0
    # A real new event cannot mint scrap until the next kill.
    old_scrap=c['scrap']
    send(30,now+30*900)
    assert game.state(DEVICE)['combat']['scrap']==old_scrap


def test_stances_modify_damage_and_incoming_counterattack():
    now=int(time.time()*1000)
    with store.db() as c:
        c.execute("UPDATE forge_combat SET hero_hp=100 WHERE device_id=?", (DEVICE,))
    # First 8 hits, the enemy is still alive and retaliates on hit #8.
    for stance in game.TACTICS:
        device='bike-'+stance
        game.set_tactic(device,stance)
        with store.db() as con:
            for i in range(8):
                game.on_event(con,device,now+i*1000,now+i*1000)
        state=game.state(device)['combat']
        assert state['last_counter']>0
    assert game.state('bike-assault')['combat']['hero_hp'] < game.state('bike-balanced')['combat']['hero_hp']
    assert game.state('bike-guard')['combat']['hero_hp'] > game.state('bike-balanced')['combat']['hero_hp']
    assert game.state('bike-assault')['combat']['enemy_hp'] < game.state('bike-balanced')['combat']['enemy_hp']


def test_sector_boss_relics_and_permanent_research_survive_prestige():
    now=int(time.time()*1000)
    game.state(DEVICE)
    with store.db() as con:
        con.execute("UPDATE forge_combat SET wave=5,enemy_hp=1,hero_hp=100 WHERE device_id=?",(DEVICE,))
    assert send(1,now)['inserted']==1
    state=game.state(DEVICE)
    c=state['combat']
    assert c['sector']==2 and c['wave']==1
    assert c['kills_total']==1 and c['bosses_total']==1
    assert c['relics']>=1
    state=game.permanent_upgrade(DEVICE,'war_engine')
    assert next(x for x in state['combat']['permanent'] if x['id']=='war_engine')['level']==1
    assert state['combat']['hero_attack']==5
    with store.db() as con:
        con.execute('UPDATE forge_state SET run_revs=2000,torque=150000,run_earned=150000 WHERE device_id=?',(DEVICE,))
    before=store.summary(DEVICE)['lifetime_revolutions']
    after=game.prestige(DEVICE)
    assert after['combat']['sector']==1 and after['combat']['wave']==1
    assert after['combat']['scrap']==0 and after['combat']['kills_total']==1
    assert after['combat']['bosses_run']==0 and after['combat']['bosses_total']==1
    assert after['combat']['hero_attack']==5
    assert after['cores']==1 and after['run_revs']==0
    assert store.summary(DEVICE)['lifetime_revolutions']==before
    store.initialize()
    assert game.state(DEVICE)['combat']['hero_attack']==5


def test_locked_shop_and_relic_validation_atomic():
    game.state(DEVICE)
    with store.db() as con:
        con.execute('UPDATE forge_state SET torque=100000 WHERE device_id=?',(DEVICE,))
        con.execute('UPDATE forge_combat SET scrap=500 WHERE device_id=?',(DEVICE,))
    with pytest.raises(ValueError,match='sector 2'):
        game.purchase(DEVICE,'railgun')
    with pytest.raises(ValueError):
        game.permanent_upgrade(DEVICE,'war_engine')
    before=game.state(DEVICE)
    assert before['torque']==100000 and before['combat']['scrap']==500
    game.purchase(DEVICE,'sprocket')
    state=game.state(DEVICE)
    assert state['combat']['hero_attack']==4
    assert state['torque']==100000-35
    assert state['combat']['scrap']==500
    with pytest.raises(ValueError):game.set_tactic(DEVICE,'invincible')
    with pytest.raises(ValueError):game.permanent_upgrade(DEVICE,'does_not_exist')


def test_many_visible_skills_and_prerequisites():
    game.state(DEVICE)
    with store.db() as con:
        con.execute('UPDATE forge_state SET run_revs=1500 WHERE device_id=?',(DEVICE,))
    state=game.state(DEVICE)
    assert len(state['skills'])>=30
    assert len(state['upgrades'])>=20
    assert len({x['branch'] for x in state['skills']})>=6
    assert len(state['combat']['permanent'])==4
    with pytest.raises(ValueError,match='prerequisite'):
        game.learn(DEVICE,'precision')
    assert game.learn(DEVICE,'blade')['skill_points_available']==9
    assert game.learn(DEVICE,'blade')['skill_points_available']==8
    assert game.learn(DEVICE,'precision')['combat']['crit_every']==11


def test_emergency_shield_preserves_enemy_damage_and_prevents_involuntary_reset():
    game.state(DEVICE)
    now=int(time.time()*1000)
    with store.db() as c:
        c.execute('UPDATE forge_combat SET hero_hp=1,enemy_hp=999,scrap=40 WHERE device_id=?',(DEVICE,))
        for i in range(8):
            game.on_event(c,DEVICE,now+i*900,now+i*900)
    result=game.state(DEVICE)
    assert result['combat']['retreats']==0
    assert result['combat']['hero_hp']==1
    assert result['combat']['enemy_hp']==39
    assert result['combat']['scrap']==40
    assert result['combat']['wave']==1
    assert result['run_revs']==8


def test_fresh_database_and_upgrade_from_legacy_forge_save():
    # v0.4 tables already exist at next boot; v0.5 adds its own combat tables.
    game.state(DEVICE)
    with store.db() as con:
        con.execute('UPDATE forge_state SET run_revs=500,torque=777,cores=3 WHERE device_id=?',(DEVICE,))
        con.execute("INSERT INTO forge_upgrades(device_id,item_id,level) VALUES(?, 'chain', 4)",(DEVICE,))
    store.initialize()
    state=game.state(DEVICE)
    assert state['torque']==777 and state['cores']==3
    assert state['combat']['enemy_hp']==55
    assert next(u for u in state['upgrades'] if u['id']=='chain')['level']==4


def test_battle_pacing_starter_boss_takes_time_without_forced_retreat():
    # A starter build reaches the boss and keeps its progress at one hull.
    game.state(DEVICE)
    now=int(time.time()*1000)
    with store.db() as con:
        for i in range(500):
            game.on_event(con,DEVICE,now+i*1000,now+i*1000)
    state=game.state(DEVICE)
    c=state['combat']
    assert c['sector']==1 and c['enemy']['boss']
    assert 0<c['enemy_hp']<c['enemy_max_hp']
    assert c['hero_hp']==1 and c['retreats']==0
    assert c['scrap']>30 and state['run_revs']==500

    # Continued pedaling can finish the damaged boss without buying an upgrade.
    with store.db() as con:
        for i in range(500,520):
            game.on_event(con,DEVICE,now+i*1000,now+i*1000)
    state=game.state(DEVICE)
    c=state['combat']
    assert c['sector']==2 and c['bosses_total']==1
    assert c['retreats']==0 and state['run_revs']==520


def test_flywheel_burst_charges_on_live_hits_at_any_cadence():
    now = int(time.time() * 1000)
    assert game.state(DEVICE)['combat']['burst'] is None
    with store.db() as con:
        con.execute('UPDATE forge_state SET run_revs=150 WHERE device_id=?', (DEVICE,))
    game.learn(DEVICE, 'flywheel_burst')

    for seq in range(1, 12):
        send(seq, now + seq * 2000)
    before = game.state(DEVICE)['combat']
    assert before['burst'] == {'charge': 11, 'hits': 12}
    assert before['enemy_hp'] == 33

    # Backfill, duplicate and fitness-only revolutions never charge the skill.
    assert send(12, now - 60000, now + 24000)['inserted'] == 1
    assert send(11, now + 22000)['inserted'] == 0
    game.set_enabled(DEVICE, False)
    assert send(13, now + 26000)['inserted'] == 1
    store.initialize()
    assert game.state(DEVICE)['combat'] == before

    game.set_enabled(DEVICE, True)
    assert send(14, now + 28000)['inserted'] == 1
    after = game.state(DEVICE)['combat']
    assert after['burst'] == {'charge': 0, 'hits': 12}
    assert after['last_hit'] == 8 and after['enemy_hp'] == 25
    assert any('Flywheel Burst' in item['description'] for item in after['log'])


def test_scrap_and_torque_dual_currency_purchase_is_atomic():
    game.state(DEVICE)
    with store.db() as c:
        c.execute('UPDATE forge_state SET torque=200 WHERE device_id=?',(DEVICE,))
        c.execute('UPDATE forge_combat SET scrap=3 WHERE device_id=?',(DEVICE,))
    with pytest.raises(ValueError,match='Scrap'):
        game.purchase(DEVICE,'piston')
    before=game.state(DEVICE)
    assert before['torque']==200 and before['combat']['scrap']==3
    with store.db() as c:
        c.execute('UPDATE forge_combat SET scrap=4 WHERE device_id=?',(DEVICE,))
    after=game.purchase(DEVICE,'piston')
    assert after['torque']==0 and after['combat']['scrap']==0
    assert after['combat']['hero_attack']==8


def test_actual_v04_tables_upgrade_to_v05_without_modifying_economy(tmp_path,monkeypatch):
    # Build the minimum *old* v0.4 schema, without v0.5 combat tables.
    import sqlite3
    legacy=tmp_path/'legacy-v04.sqlite3'
    with sqlite3.connect(legacy) as con:
        con.executescript('''
            CREATE TABLE forge_state (
                device_id TEXT PRIMARY KEY,torque INTEGER NOT NULL DEFAULT 0,
                run_revs INTEGER NOT NULL DEFAULT 0,total_game_revs INTEGER NOT NULL DEFAULT 0,
                run_earned INTEGER NOT NULL DEFAULT 0,total_earned INTEGER NOT NULL DEFAULT 0,
                prestiges INTEGER NOT NULL DEFAULT 0,cores INTEGER NOT NULL DEFAULT 0,
                skill_spent INTEGER NOT NULL DEFAULT 0,last_live_pulse_ms INTEGER,
                combo INTEGER NOT NULL DEFAULT 0,torque_fraction INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE forge_upgrades(device_id TEXT NOT NULL,item_id TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(device_id,item_id));
            CREATE TABLE forge_skills(device_id TEXT NOT NULL,skill_id TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(device_id,skill_id));
            CREATE TABLE forge_prestiges(device_id TEXT NOT NULL,number INTEGER NOT NULL,
                earned_cores INTEGER NOT NULL,previous_run_revs INTEGER NOT NULL,
                previous_run_earned INTEGER NOT NULL,at_ms INTEGER NOT NULL,
                PRIMARY KEY(device_id,number));
            INSERT INTO forge_state(device_id,torque,cores,run_revs,prestiges)
                VALUES('bike-001',12345,6,1670,2);
            INSERT INTO forge_upgrades VALUES('bike-001','flywheel',3);
            INSERT INTO forge_skills VALUES('bike-001','steady',2);
        ''')
    monkeypatch.setattr(store,'DB_PATH',str(legacy))
    store.initialize()
    s=game.state(DEVICE)
    assert s['torque']==12345 and s['cores']==6 and s['run_revs']==1670
    assert s['prestiges']==2 and s['combat']['sector']==1
    assert next(x for x in s['upgrades'] if x['id']=='flywheel')['level']==3
    assert next(x for x in s['skills'] if x['id']=='steady')['level']==2
