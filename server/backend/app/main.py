"""Authenticated telemetry dashboard, preferences + durable MQTT event storage."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

import paho.mqtt.client as mqtt
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import store

LOG = logging.getLogger("pedal")
logging.basicConfig(level=logging.INFO)
BASE = Path(__file__).resolve().parent.parent
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
DEVICE_ID = os.getenv("DEVICE_ID", "bike-001")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def make_cookie() -> str:
    expiry = int(time.time()) + 7 * 24 * 3600
    value = f"{DASHBOARD_USER}:{expiry}"
    signature = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}:{signature}"


def cookie_valid(cookie: str | None) -> bool:
    if not cookie or not SESSION_SECRET:
        return False
    try:
        user, expiry, mac = cookie.rsplit(":", 2)
        if user != DASHBOARD_USER or int(expiry) < time.time():
            return False
        check = hmac.new(SESSION_SECRET.encode(), f"{user}:{expiry}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(check, mac)
    except (ValueError, TypeError):
        return False


class SocketHub:
    def __init__(self) -> None:
        self.clients: dict[str, set[WebSocket]] = {}

    async def push(self, device: str) -> None:
        packet = json.dumps({"type": "summary", "data": store.summary(device)})
        stale = []
        for ws in tuple(self.clients.get(device, ())):
            try:
                await ws.send_text(packet)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.clients.get(device, set()).discard(ws)


hub = SocketHub()


class MqttIngestor:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="pedal-ingestor", clean_session=False)
        self.client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
        self.client.on_connect = self.connected
        self.client.on_message = self.message
        self.client.on_disconnect = self.disconnected
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def connected(self, client, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            client.subscribe("pedal/v1/+/events", qos=1)
            LOG.info("MQTT connected, subscribed to bike events")
        else:
            LOG.error("MQTT connect rejected: %s", reason_code)

    def disconnected(self, client, userdata, disconnect_flags, reason_code, properties):
        LOG.warning("MQTT disconnected: %s", reason_code)

    def message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 4 or parts[:2] != ["pedal", "v1"] or parts[3] != "events":
            return
        device = parts[2]
        try:
            if len(msg.payload) > 60_000:
                raise ValueError("Oversized MQTT payload")
            payload = json.loads(msg.payload)
            result = store.ingest(payload, device)
            # Durable SQLite commit has completed before application ACK.
            ack = json.dumps(result, separators=(",", ":"))
            client.publish(f"pedal/v1/{device}/ack", ack, qos=1, retain=False)
            if result["inserted"]:
                asyncio.run_coroutine_threadsafe(hub.push(device), self.loop)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            LOG.warning("Rejected event batch from %s: %s", device, e)
        except Exception:
            LOG.exception("Ingestion failure (device will retry unacknowledged batch)")

    def start(self):
        self.client.connect_async(os.getenv("MQTT_HOST", "mqtt"),
                                  int(os.getenv("MQTT_PORT", "1883")), keepalive=30)
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not SESSION_SECRET or not DASHBOARD_PASSWORD:
        raise RuntimeError("Missing dashboard credentials or SESSION_SECRET")
    store.initialize()
    consumer = MqttIngestor(asyncio.get_running_loop())
    consumer.start()
    webhook_url = os.getenv('PEDAL_WEBHOOK_URL', '').strip()
    async def notification_worker():
        while True:
            try:
                await asyncio.to_thread(features.deliver_notifications, webhook_url)
            except Exception:
                LOG.exception('Optional achievement delivery worker error')
            await asyncio.sleep(10)
    task = asyncio.create_task(notification_worker()) if webhook_url else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        consumer.stop()


app = FastAPI(title="Pedal Telemetry", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def auth(request: Request, call_next):
    if request.url.path in ("/health", "/login") or request.url.path.startswith("/static/"):
        return await call_next(request)
    if not cookie_valid(request.cookies.get("pedal_session")):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/login")
async def login_page():
    return FileResponse(BASE / "static" / "login.html")


@app.post("/login")
async def login(request: Request):
    body = (await request.body()).decode("utf-8", errors="replace")
    params = parse_qs(body, keep_blank_values=True)
    user = params.get("username", [""])[0]
    password = params.get("password", [""])[0]
    if not (secrets.compare_digest(user, DASHBOARD_USER)
            and secrets.compare_digest(password, DASHBOARD_PASSWORD)):
        return HTMLResponse("<h3>Wrong credentials.</h3><a href='/login'>Try again</a>", status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("pedal_session", make_cookie(), httponly=True, secure=COOKIE_SECURE,
                        samesite="strict", max_age=7 * 24 * 3600)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("pedal_session")
    return response


@app.get("/")
async def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/v1/devices/{device}/summary")
async def api_summary(device: str):
    try:
        return store.summary(device)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/v1/devices/{device}/history")
async def api_history(device: str, period: str = "24h"):
    try:
        return store.history(device, period)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/v1/devices/{device}/achievements")
async def api_achievements(device: str):
    try:
        return store.achievements(device)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/v1/devices/{device}/sessions")
async def api_sessions(device: str):
    try:
        return {"sessions": store.recent_sessions(device)}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.websocket("/ws/{device}")
async def websocket(ws: WebSocket, device: str):
    if not cookie_valid(ws.cookies.get("pedal_session")):
        await ws.close(code=1008)
        return
    try:
        store._id(device, "device_id")
    except ValueError:
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.clients.setdefault(device, set()).add(ws)
    await ws.send_json({"type": "summary", "data": store.summary(device)})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients[device].discard(ws)

@app.get("/api/v1/config")
async def api_config():
    return {"device_id": DEVICE_ID, "timezone": "Europe/Budapest"}

@app.get("/api/v1/devices/{device}/export.csv")
async def api_export(device: str):
    from fastapi.responses import StreamingResponse
    try:
        store._id(device, "device_id")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return StreamingResponse(store.export_csv_rows(device), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="pedal-{device}.csv"'})

# v0.3 cockpit, daily goals, virtual rides and cadence challenges.
# Existing MQTT topics, cookies and REST endpoints remain unchanged.
from . import features


def _write_allowed(request: Request) -> bool:
    # A JSON-only same-origin write surface; no cross-site form POSTs.
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc.lower() != request.headers.get('host', '').lower():
            return False
    if request.headers.get('sec-fetch-site') == 'cross-site':
        return False
    return request.headers.get('content-type', '').split(';')[0].strip().lower() == 'application/json'


async def _small_json(request: Request):
    if not _write_allowed(request):
        raise ValueError('JSON request from the same origin required')
    body = await request.body()
    if len(body) > 4096:
        raise ValueError('Request too large')
    obj = json.loads(body)
    if not isinstance(obj, dict):
        raise ValueError('JSON object required')
    return obj


@app.get('/api/v1/devices/{device}/features')
async def api_features(device: str):
    try:
        return features.dashboard_features(device)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.get('/api/v1/devices/{device}/cadence')
async def api_cadence(device: str, minutes: int = 5):
    try:
        return features.cadence_chart(device, minutes)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/preferences')
async def api_preferences(device: str, request: Request):
    try:
        return features.change_preferences(device, await _small_json(request))
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/challenge/start')
async def api_challenge_start(device: str, request: Request):
    try:
        obj = await _small_json(request)
        if set(obj) != {'target_rpm', 'duration_s'}:
            raise ValueError('target_rpm and duration_s required')
        return features.start_challenge(device, obj['target_rpm'], obj['duration_s'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/challenge/stop')
async def api_challenge_stop(device: str, request: Request):
    try:
        if await _small_json(request):
            raise ValueError('Expected empty JSON object')
        return features.stop_challenge(device)
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


# v0.4 PEDAL FORGE. Writes are same-origin JSON only; no earn/click endpoint.
from . import game

@app.get('/api/v1/devices/{device}/forge')
async def api_forge(device: str):
    try:
        return game.state(device)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/forge/buy')
async def api_forge_buy(device: str, request: Request):
    try:
        obj = await _small_json(request)
        if set(obj) != {'item_id'} or not isinstance(obj['item_id'], str):
            raise ValueError('item_id required')
        return game.purchase(device, obj['item_id'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/forge/skill')
async def api_forge_skill(device: str, request: Request):
    try:
        obj = await _small_json(request)
        if set(obj) != {'skill_id'} or not isinstance(obj['skill_id'], str):
            raise ValueError('skill_id required')
        return game.learn(device, obj['skill_id'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/forge/prestige')
async def api_forge_prestige(device: str, request: Request):
    try:
        if await _small_json(request):
            raise ValueError('Expected empty JSON object')
        return game.prestige(device)
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/forge/mode')
async def api_forge_mode(device: str, request: Request):
    """Explicit, persisted game participation; never affects bike recording."""
    try:
        obj = await _small_json(request)
        if set(obj) != {'enabled'} or type(obj['enabled']) is not bool:
            raise ValueError('enabled must be a boolean')
        return game.set_enabled(device, obj['enabled'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)

# v0.5 GEARBOUND. All combat advancement comes from MQTT ingest, never HTTP.
@app.post('/api/v1/devices/{device}/forge/tactic')
async def api_forge_tactic(device: str, request: Request):
    try:
        obj = await _small_json(request)
        if set(obj) != {'tactic'} or not isinstance(obj['tactic'], str):
            raise ValueError('tactic required')
        return game.set_tactic(device, obj['tactic'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)


@app.post('/api/v1/devices/{device}/forge/relic')
async def api_forge_relic(device: str, request: Request):
    try:
        obj = await _small_json(request)
        if set(obj) != {'trait_id'} or not isinstance(obj['trait_id'], str):
            raise ValueError('trait_id required')
        return game.permanent_upgrade(device, obj['trait_id'])
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
