"""Authenticated game mode endpoint may pause combat but cannot mint rewards."""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app import main,store

def test_game_mode_api_requires_login_same_origin_and_strict_boolean(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'mode-api.sqlite3'))
    monkeypatch.setattr(main,'SESSION_SECRET','unit-test-session')
    monkeypatch.setattr(main,'DASHBOARD_USER','admin')
    monkeypatch.setattr(main,'DASHBOARD_PASSWORD','test-password')
    store.initialize()
    c=TestClient(main.app)
    path='/api/v1/devices/bike-001/forge/mode'
    assert c.post(path,json={'enabled':False}).status_code==401
    assert c.post('/login',data={'username':'admin','password':'test-password'}).status_code==200
    assert c.post(path,json={'enabled':False},headers={'origin':'http://evil.site'}).status_code==400
    assert c.post(path,json={'enabled':0}).status_code==400
    assert c.post(path,json={'enabled':False,'extra':1}).status_code==400
    assert c.post(path,json={'enabled':False}).status_code==200
    data=c.get('/api/v1/devices/bike-001/forge').json()
    assert data['enabled'] is False
    assert c.post(path,json={'enabled':True}).status_code==200
    assert c.get('/api/v1/devices/bike-001/forge').json()['enabled'] is True
