from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
if 'paho' not in sys.modules and importlib.util.find_spec('paho') is None:
    paho = types.ModuleType('paho')
    mqtt = types.ModuleType('paho.mqtt')
    client = types.ModuleType('paho.mqtt.client')
    mqtt.client = client
    paho.mqtt = mqtt
    sys.modules.update({'paho':paho, 'paho.mqtt':mqtt, 'paho.mqtt.client':client})
from app import main, store


def test_new_api_auth_preferences_and_challenge(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'SESSION_SECRET', 'api-testing-secret')
    monkeypatch.setattr(main, 'DASHBOARD_USER', 'admin')
    monkeypatch.setattr(main, 'DASHBOARD_PASSWORD', 'api-test-password')
    monkeypatch.setattr(store, 'DB_PATH', str(tmp_path / 'test.sqlite3'))
    store.initialize()
    client = TestClient(main.app)
    root='/api/v1/devices/bike-001'
    assert client.get(f'{root}/features').status_code == 401
    assert client.post(f'{root}/preferences', json={'daily_goal': 50}).status_code == 401
    assert client.post('/login', data={'username':'admin','password':'api-test-password'}).status_code == 200
    status=client.get(f'{root}/features')
    assert status.status_code == 200
    assert len(status.json()['heatmap']) == 365
    assert len(client.get(f'{root}/cadence').json()['points']) == 60
    assert client.get(f'{root}/cadence?minutes=999').status_code == 400
    assert client.post(f'{root}/preferences', data={'daily_goal':'99'}).status_code == 400
    assert client.post(f'{root}/preferences', json={'daily_goal':99}, headers={'origin':'http://evil.test'}).status_code == 400
    updated=client.post(f'{root}/preferences', json={'daily_goal':99})
    assert updated.status_code == 200
    assert updated.json()['daily_goal']==99
    assert client.get(f'{root}/features').json()['preferences']['daily_goal']==99
    assert client.post(f'{root}/challenge/start', json={'target_rpm':-1,'duration_s':45}).status_code == 400
    started=client.post(f'{root}/challenge/start', json={'target_rpm':80,'duration_s':30})
    assert started.status_code == 200
    assert started.json()['current']['status']=='active'
    assert client.post(f'{root}/challenge/stop', json={}).json()['current']['status']=='cancelled'


def test_frontend_assets_present_and_api_no_protocol_change():
    root=ROOT / 'backend' / 'static'
    html=(root/'index.html').read_text()
    js=(root/'feature-ui.js').read_text()
    assert 'live-chart' in html and 'heatmap' in html and 'settings-form' in html
    assert 'PedalFeatures' in js
    assert 'export.csv' in (ROOT/'backend'/'app'/'main.py').read_text()
    assert 'pedal/v1/+/events' in (ROOT/'backend'/'app'/'main.py').read_text()
