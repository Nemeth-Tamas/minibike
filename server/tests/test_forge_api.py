"""v0.4 authenticated API/CSRF surface: no click-to-earn endpoint."""
from __future__ import annotations
import importlib.util
import sys
import types
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
if 'paho' not in sys.modules and importlib.util.find_spec('paho') is None:
    paho=types.ModuleType('paho')
    mqtt=types.ModuleType('paho.mqtt')
    client=types.ModuleType('paho.mqtt.client')
    mqtt.client=client;paho.mqtt=mqtt
    sys.modules.update({'paho':paho,'paho.mqtt':mqtt,'paho.mqtt.client':client})
from app import main,store


def test_forge_access_and_validation(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'SESSION_SECRET','test-only-secret')
    monkeypatch.setattr(main,'DASHBOARD_USER','admin')
    monkeypatch.setattr(main,'DASHBOARD_PASSWORD','test-pass')
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'dev.sqlite3'))
    store.initialize()
    c=TestClient(main.app)
    root='/api/v1/devices/bike-001/forge'
    assert c.get(root).status_code==401
    assert c.post(root+'/buy',json={'item_id':'chain'}).status_code==401
    assert c.post('/login',data={'username':'admin','password':'test-pass'}).status_code==200
    assert c.get(root).status_code==200
    state=c.get(root).json()
    assert state['torque']==0 and state['no_idle_earnings']
    assert c.post(root+'/buy',data={'item_id':'chain'}).status_code==400
    assert c.post(root+'/skill',json={'skill_id':'steel'},headers={'origin':'http://evil.example'}).status_code==400
    assert c.post(root+'/buy',json={'item_id':'chain'}).status_code==400
    assert c.post(root+'/buy',json={'item_id':'fake'}).status_code==400
    assert c.post(root+'/skill',json={'skill_id':'fake'}).status_code==400
    assert c.post(root+'/prestige',json={}).status_code==400
    assert c.post(root+'/prestige',json={'dummy':True}).status_code==400
    assert c.get(root).json()['torque']==0
    assert c.post(root+'/earn',json={'torque':100000}).status_code==404


def test_cadence_streak_is_continuous(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DB_PATH',str(tmp_path/'cadence.sqlite3'))
    store.initialize()
    import time
    base=int(time.time()*1000)
    t=base
    for seq,gap in enumerate((0,1000,1000,1000,1100,1000),start=1):
        t+=gap
        store.ingest({'v':1,'device_id':'bike-001','boot_id':'boot_test',
                      'batch_id':f'b_{seq}',
                      'events':[{'seq':seq,'t_ms':t}]},'bike-001',t)
    with store.db() as db:
        r=db.execute('SELECT steady_60_ms,max_steady_60_ms FROM sessions WHERE device_id=?',('bike-001',)).fetchone()
    assert r['steady_60_ms']==1000
    assert r['max_steady_60_ms']==3000
    a=store.achievements('bike-001')
    cruise=next(x for x in a['achievements'] if x['id']=='cruise_control')
    assert cruise['progress']==3 and cruise['unlocked_ms'] is None
