"""v0.5 combat controls: authorized JSON only, no HTTP attack/loot endpoints."""
import sys
import importlib.util
import types
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
if 'paho' not in sys.modules and importlib.util.find_spec('paho') is None:
    paho=types.ModuleType('paho');mqtt=types.ModuleType('paho.mqtt')
    client=types.ModuleType('paho.mqtt.client')
    mqtt.client=client;paho.mqtt=mqtt
    sys.modules.update({'paho':paho,'paho.mqtt':mqtt,'paho.mqtt.client':client})
from app import main,store


def test_new_routes_only_allow_valid_authenticated_decisions(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(main,'SESSION_SECRET','unit-test-session')
    monkeypatch.setattr(main,'DASHBOARD_USER','admin')
    monkeypatch.setattr(main,'DASHBOARD_PASSWORD','test-password')
    store.initialize()
    c=TestClient(main.app)
    base='/api/v1/devices/bike-001/forge'
    assert c.post(base+'/tactic',json={'tactic':'guard'}).status_code==401
    assert c.post(base+'/contract',json={'contract_id':'steady_work'}).status_code==401
    assert c.post('/login',data={'username':'admin','password':'test-password'}).status_code==200
    assert c.post(base+'/tactic',json={'tactic':'guard'},headers={'origin':'http://evil.site'}).status_code==400
    assert c.post(base+'/tactic',data={'tactic':'guard'}).status_code==400
    assert c.post(base+'/tactic',json={'tactic':'invincible'}).status_code==400
    assert c.post(base+'/tactic',json={'tactic':'guard'}).status_code==200
    assert c.get(base).json()['combat']['tactic']=='guard'
    assert c.post(base+'/relic',json={'trait_id':'unknown'}).status_code==400
    assert c.post(base+'/relic',json={'trait_id':'war_engine'}).status_code==400
    assert c.post(base+'/contract',json={'contract_id':True}).status_code==400
    assert c.post(base+'/contract',json={'contract_id':'invented'}).status_code==400
    assert c.post(base+'/contract',json={'contract_id':'steady_work'},headers={'origin':'http://evil.site'}).status_code==400
    selected=c.post(base+'/contract',json={'contract_id':'steady_work'})
    assert selected.status_code==200 and selected.json()['contracts'][0]['active']
    assert selected.json()['torque']==0
    paused=c.post(base+'/contract',json={'contract_id':None})
    assert paused.status_code==200 and not paused.json()['contracts'][0]['active']
    assert c.post(base+'/attack',json={'damage':999999}).status_code==404
    assert c.post(base+'/loot',json={'scrap':999999}).status_code==404
