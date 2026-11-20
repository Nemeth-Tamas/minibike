import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import store


@pytest.fixture(autouse=True)
def database(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "bike.sqlite3"))
    store.initialize()


def event_batch(seq=(1, 2), now=None, life=None, boot="boot_1", batch="batch_1"):
    now = now or int(time.time()*1000)
    payload = {
        "v": 1, "device_id": "bike-001", "boot_id": boot, "batch_id": batch,
        "events": [{"seq": i, "t_ms": now - (len(seq)-j)*1000,
                    "uptime_ms": i*1000} for j, i in enumerate(seq)],
    }
    if life is not None: payload["lifetime_revs"] = life
    return payload


def test_exactly_once_replays():
    now = int(time.time()*1000)
    payload = event_batch(now=now)
    ack = store.ingest(payload, "bike-001", now)
    assert ack["ack_sequences"] == [1, 2]
    assert ack["inserted"] == 2
    again = store.ingest(payload, "bike-001", now)
    assert again["inserted"] == 0
    s = store.summary("bike-001", now)
    assert s["recorded_revolutions"] == 2
    assert s["session_revolutions"] == 2
    assert 55 < s["live_rpm"] < 65


def test_lifetime_snapshot_counts_missing_events():
    now = int(time.time()*1000)
    store.ingest(event_batch(seq=(30, 31), now=now, life=31), "bike-001", now)
    s = store.summary("bike-001", now)
    assert s["recorded_revolutions"] == 2
    assert s["lifetime_revolutions"] == 31
    assert s["unlogged_revolutions"] == 29


def test_historical_pulse_does_not_corrupt_last_session():
    now = int(time.time()*1000)
    store.ingest(event_batch(seq=(1, 2), now=now), "bike-001", now)
    old = event_batch(seq=(3,), now=now - 3600000, batch="old_2")
    store.ingest(old, "bike-001", now)
    s = store.summary("bike-001", now)
    assert s["recorded_revolutions"] == 3
    assert s["session_revolutions"] == 2


def test_24h_history_has_time_axis_and_valid_aggregates():
    now = int(time.time()*1000)
    store.ingest(event_batch(seq=(1, 2), now=now), "bike-001", now)
    data = store.history("bike-001", "24h", now)
    assert len(data["points"]) == 1440
    assert sum(p["y"] for p in data["points"]) == 2
    assert store.history("bike-001", "7d", now)["points"][-1]["x"] % 3600000 == 0
    assert store.history("bike-001", "30d", now)["points"]
    assert len(store.history("bike-001", "1y", now)["points"]) == 12


def test_invalid_topic_and_duplicates_rejected_without_side_effects():
    now = int(time.time()*1000)
    payload = event_batch(now=now)
    with pytest.raises(ValueError, match="topic"):
        store.ingest(payload, "not-bike", now)
    payload["events"].append(payload["events"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        store.ingest(payload, "bike-001", now)
    assert store.summary("bike-001", now)["recorded_revolutions"] == 0


def test_two_sessions_separated_by_5_minutes():
    now = int(time.time()*1000)
    store.ingest(event_batch(seq=(1, 2), now=now-600000), "bike-001", now)
    store.ingest(event_batch(seq=(3, 4), now=now, batch="next"), "bike-001", now)
    sessions = store.recent_sessions("bike-001")
    assert len(sessions) == 2
    assert [s["revs"] for s in sessions] == [2, 2]


def test_approximate_time_is_marked_and_lifetime_kept():
    now = int(time.time()*1000)
    batch = event_batch(seq=(1,), now=now)
    del batch["events"][0]["t_ms"]
    store.ingest(batch, "bike-001", now)
    with store.db() as conn:
        row = conn.execute("SELECT time_quality FROM events").fetchone()
    assert row[0] == "received"
    assert store.summary("bike-001", now)["lifetime_revolutions"] == 1


def test_export_streaming_csv():
    now = int(time.time()*1000)
    store.ingest(event_batch(now=now), "bike-001", now)
    chunks = list(store.export_csv_rows("bike-001"))
    assert "time_quality" in chunks[0]
    assert sum(chunk.count("bike-001") for chunk in chunks[1:]) == 2
