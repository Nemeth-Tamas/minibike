"""Fake bike: streams individually numbered revolutions and waits for DB-level ACKs."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from threading import Event, Lock

import paho.mqtt.client as mqtt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpm", type=float, default=65)
    ap.add_argument("--count", type=int, default=120)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--duplicate-last", action="store_true", help="Republish same batch, verifying server deduplication")
    args = ap.parse_args()
    if not 1 <= args.rpm <= 300 or not 1 <= args.count <= 100000 or not 1 <= args.batch_size <= 256:
        ap.error("rpm must be 1–300, count 1–100000 and batch-size 1–256")

    path = Path(os.getenv("STATE_PATH", "/state/simulator.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(path.read_text()) if path.exists() else {"next_seq": 1}
    seq = int(state["next_seq"])
    device = os.getenv("DEVICE_ID", "bike-001")
    boot = uuid.uuid4().hex[:20]
    topic = f"pedal/v1/{device}/events"
    ack_topic = f"pedal/v1/{device}/ack"
    connected = Event()
    acks = {}
    lock = Lock()

    def on_connect(client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            client.subscribe(ack_topic, qos=1)
            connected.set()
        else:
            print(f"MQTT rejected credentials: {reason_code}", flush=True)

    def on_message(client, userdata, msg):
        try:
            response = json.loads(msg.payload)
            with lock:
                acks[response["batch_id"]] = response
        except (KeyError, ValueError, TypeError):
            pass

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"bike-sim-{boot}")
    client.username_pw_set(os.getenv("MQTT_USER", "bike"), os.environ["MQTT_PASSWORD"])
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(os.getenv("MQTT_HOST", "mqtt"), int(os.getenv("MQTT_PORT", "1883")), 30)
    client.loop_start()
    if not connected.wait(15):
        raise RuntimeError("Unable to connect and subscribe to MQTT")
    print(f"Starting {args.count} simulated revolutions at {args.rpm:g} RPM, first seq={seq}", flush=True)

    try:
        emitted = 0
        events = []
        last_batch = None
        start_monotonic = time.monotonic()
        while emitted < args.count:
            target = start_monotonic + emitted * 60 / args.rpm
            time.sleep(max(0.0, target - time.monotonic()))
            events.append({"seq": seq, "t_ms": int(time.time() * 1000),
                           "uptime_ms": int((time.monotonic() - start_monotonic) * 1000)})
            seq += 1
            emitted += 1
            if len(events) == args.batch_size or emitted == args.count:
                batch = {
                    "v": 1, "device_id": device, "boot_id": boot,
                    "batch_id": uuid.uuid4().hex[:20], "lifetime_revs": seq - 1,
                    "events": events,
                }
                last_batch = batch
                client.publish(topic, json.dumps(batch, separators=(",", ":")), qos=1)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    with lock:
                        ack = acks.pop(batch["batch_id"], None)
                    if ack is not None:
                        if set(ack["ack_sequences"]) != {e["seq"] for e in events}:
                            raise RuntimeError(f"Incomplete ACK: {ack}")
                        # Durable server ACK received: safe to advance local journal.
                        state["next_seq"] = seq
                        temp = path.with_suffix(".tmp")
                        temp.write_text(json.dumps(state))
                        temp.replace(path)
                        print(f"ACK seq {events[0]['seq']}–{events[-1]['seq']} | inserted={ack['inserted']}", flush=True)
                        break
                    time.sleep(0.05)
                else:
                    raise TimeoutError("No database ACK; sequence not advanced on disk")
                events = []
        if args.duplicate_last and last_batch:
            print("Replaying last batch to prove deduplication...", flush=True)
            client.publish(topic, json.dumps(last_batch), qos=1)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with lock:
                    ack = acks.pop(last_batch["batch_id"], None)
                if ack:
                    print(f"Replay received inserted={ack['inserted']} (expected zero)", flush=True)
                    assert ack["inserted"] == 0
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError("No ACK for duplicate batch")
    finally:
        client.disconnect()
        client.loop_stop()
    print("Finished. Open the dashboard!", flush=True)


if __name__ == "__main__":
    main()
