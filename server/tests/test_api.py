import importlib.util
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
if importlib.util.find_spec('paho') is None:
    # API tests do not start MQTT; only stub the import in offline build environments.
    paho = types.ModuleType('paho')
    mqtt = types.ModuleType('paho.mqtt')
    client = types.ModuleType('paho.mqtt.client')
    mqtt.client = client
    paho.mqtt = mqtt
    sys.modules.update({'paho':paho, 'paho.mqtt':mqtt, 'paho.mqtt.client':client})

from app import main, store


def test_auth_dashboard_and_api(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'SESSION_SECRET', 'test-only-secret')
    monkeypatch.setattr(main, 'DASHBOARD_USER', 'admin')
    monkeypatch.setattr(main, 'DASHBOARD_PASSWORD', 'abc123')
    monkeypatch.setattr(store, 'DB_PATH', str(tmp_path / 'test.sqlite3'))
    store.initialize()
    c=TestClient(main.app)
    first=c.get('/', follow_redirects=False)
    assert first.status_code == 303
    assert first.headers['location'] == '/login'
    assert c.get('/login').status_code == 200
    assert 'text/css' in c.get('/static/styles.css').headers['content-type']
    assert c.get('/api/v1/config').status_code == 401
    assert c.post('/login', data={'username':'admin','password':'bad'}).status_code == 401
    response=c.post('/login', data={'username':'admin','password':'abc123'}, follow_redirects=False)
    assert response.status_code == 303
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert c.get('/').status_code == 200
    assert c.get('/api/v1/config').json()['device_id'] == 'bike-001'
    assert c.get('/api/v1/devices/bike-001/summary').json()['lifetime_revolutions'] == 0
    assert c.get('/api/v1/devices/bike-001/achievements').json()['total_count'] == 40
    with c.websocket_connect('/ws/bike-001') as ws:
        assert ws.receive_json()['type'] == 'summary'
    assert c.get('/logout').status_code == 200
