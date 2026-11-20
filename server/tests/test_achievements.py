import sys
import time
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import store


@pytest.fixture(autouse=True)
def database(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "achievements.sqlite3"))
    store.initialize()


def batch(ids, now, life=None):
    data = {"v": 1, "device_id": "bike-001", "boot_id": "testboot",
            "batch_id": "testbatch", "events": [
                {"seq": i, "t_ms": now - (len(ids) - 1 - j)*1000}
                for j, i in enumerate(ids)]}
    if life is not None:
        data["lifetime_revs"] = life
    return data


def test_awards_only_after_ingest_and_persist_after_replay():
    now = int(time.time()*1000)
    data = batch([1, 2, 3], now, life=1500)
    assert store.achievements("bike-001")["unlocked_count"] == 0
    store.ingest(data, "bike-001", now)
    a = store.achievements("bike-001")
    keys = {x["id"] for x in a["achievements"] if x["unlocked_ms"]}
    assert {"first_spin", "century", "one_k"} <= keys
    assert "ten_k" not in keys
    assert all(x["unlocked_ms"] == now for x in a["achievements"] if x["id"] in keys)
    store.ingest(data, "bike-001", now+100)
    assert store.achievements("bike-001")["unlocked_count"] == a["unlocked_count"]


def test_daily_achievements_and_progress():
    now = int(time.time()*1000)
    for n in range(5):
        ids = list(range(1+n*110, 111+n*110))
        store.ingest(batch(ids, now), "bike-001", now)
    a = store.achievements("bike-001")
    d = next(x for x in a["achievements"] if x["id"] == "daily_500")
    assert d["unlocked_ms"]
    d2 = next(x for x in a["achievements"] if x["id"] == "daily_2000")
    assert d2["progress"] == 550 and not d2["unlocked_ms"]


def test_achievement_records_survive_store_reinitialize():
    now = int(time.time()*1000)
    store.ingest(batch([1], now), "bike-001", now)
    store.initialize()
    first = next(x for x in store.achievements("bike-001")["achievements"] if x["id"] == "first_spin")
    assert first["unlocked_ms"] == now


def test_upgrade_backfills_existing_data():
    now = int(time.time()*1000)
    store.ingest(batch([1], now), "bike-001", now)
    with store.db() as con:
        con.execute("DELETE FROM achievements WHERE device_id='bike-001'")
    assert store.achievements("bike-001")["unlocked_count"] == 0
    store.initialize()
    assert store.achievements("bike-001")["unlocked_count"] == 1
