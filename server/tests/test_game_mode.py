"""Game OFF means fitness-only, and combat cannot forcibly reset progress."""
from __future__ import annotations
import sys
import time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import game, store

D = 'bike-001'

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DB_PATH', str(tmp_path / 'pedals.sqlite3'))
    store.initialize()

def pedal(seq, timestamp):
    return store.ingest({
        'v': 1, 'device_id': D, 'boot_id': 'realbike',
        'batch_id': 'packet_' + str(seq),
        'events': [{'seq': seq, 't_ms': timestamp}],
    }, D, timestamp)

def test_off_is_true_fitness_only_and_missed_game_pulses_do_not_backfill():
    base = int(time.time() * 1000)
    assert game.state(D)['enabled']
    assert pedal(1, base)['inserted'] == 1
    before = game.state(D)
    assert before['torque'] == 1 and before['combat']['attacks'] == 1
    paused = game.set_enabled(D, False)
    assert paused['enabled'] is False
    with pytest.raises(ValueError, match='OFF'):
        game.purchase(D, 'chain')
    for seq in range(2, 10):
        assert pedal(seq, base + seq * 900)['inserted'] == 1
    assert pedal(9, base + 9 * 900)['inserted'] == 0
    off = game.state(D)
    assert off['torque'] == before['torque']
    assert off['total_game_revs'] == before['total_game_revs']
    assert off['combat'] == before['combat']
    assert store.summary(D)['lifetime_revolutions'] == 9
    store.initialize()
    assert game.state(D)['enabled'] is False
    assert game.set_enabled(D, True)['enabled'] is True
    assert pedal(10, base + 10000)['inserted'] == 1
    resumed = game.state(D)
    assert resumed['torque'] == before['torque'] + 1
    assert resumed['total_game_revs'] == before['total_game_revs'] + 1
    assert resumed['combat']['attacks'] == before['combat']['attacks'] + 1
    assert store.summary(D)['lifetime_revolutions'] == 10

def test_no_death_enemy_hp_never_resets_on_shield_trigger():
    base = int(time.time() * 1000)
    game.state(D)
    with store.db() as con:
        con.execute("UPDATE forge_combat SET hero_hp=2, enemy_hp=50, scrap=30 WHERE device_id=?", (D,))
    for seq in range(1, 9):
        pedal(seq, base + seq*900)
    state = game.state(D)
    assert state['combat']['hero_hp'] == 1
    assert state['combat']['enemy_hp'] == 34
    assert state['combat']['retreats'] == 0
    assert state['combat']['scrap'] == 30
    for seq in range(9, 19):
        pedal(seq, base + seq*900)
    end = game.state(D)
    # Attack 13 is a guaranteed critical strike, adding two extra damage.
    assert end['combat']['enemy_hp'] == 12
    assert end['combat']['wave'] == 1
    assert end['combat']['retreats'] == 0

def test_mode_parameter_requires_real_boolean():
    for value in (0, 1, 'false', None):
        with pytest.raises(ValueError, match='boolean'):
            game.set_enabled(D, value)
