"""One-time guarded removal of demo data. Execute inside backend container, never blindly."""
import sys
from app import store

if sys.argv[1:] != ["--yes-delete-exactly-40-simulator-events"]:
    raise SystemExit("Refusing: expected --yes-delete-exactly-40-simulator-events")
with store.db() as con:
    con.execute("BEGIN IMMEDIATE")
    row = con.execute("SELECT COUNT(*),MIN(seq),MAX(seq) FROM events WHERE device_id=?",
                      ("bike-001",)).fetchone()
    if tuple(row) != (40, 1, 40):
        raise SystemExit(f"REFUSING: unexpected records {tuple(row)}; this is not the known 40-event demo")
    # Additional guard: simulator boot ids are not valid physical-firmware boot token ids.
    ids = [r[0] for r in con.execute("SELECT DISTINCT boot_id FROM events WHERE device_id='bike-001'")]
    if not ids or any(not str(boot).isalnum() or str(boot).startswith('b') and len(str(boot))==9 for boot in ids):
        raise SystemExit(f"REFUSING: boot IDs do not look like simulator data: {ids}")
    for table in ("events", "minute_stats", "day_stats", "sessions", "devices", "achievements"):
        con.execute(f"DELETE FROM {table} WHERE device_id=?", ("bike-001",))
print("Cleared precisely the 40 known demo events and related aggregates/achievements.")
