"""Queue acceptance, authorization and effect/result atomicity through real HTTP/SQL."""
from datetime import datetime, timezone
import uuid
from starlette.testclient import TestClient
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS


def packet(tool='memory_domains',arguments=None):
    return {'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),
            'tool':tool,'arguments':arguments or {}}


def test_queue_acceptance_has_durable_replayable_owner_handle(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    value=packet()
    with TestClient(app,base_url='https://testserver') as client:
        first=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert first.status_code==202,first.text
        assert first.json()['durable'] is True
        receipt=first.json()['request_id']
        replay=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert replay.status_code==202 and replay.json()['request_id']==receipt
        foreign=client.get('/v1/requests/'+receipt,headers=headers(KEYS[2]))
        assert foreign.status_code==404
        altered={**value,'arguments':{'unexpected':'different'}}
        assert client.post('/v1/requests',headers=headers(KEYS[0]),json=altered).status_code==409


def test_submit_short_wait_checks_status_once(service_store,tmp_path,monkeypatch):
    """A 100ms preference must not create ten owner DB sessions per submit."""
    from agentic_rag.service import requests as queue
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    receipt={'request_id':str(uuid.uuid4()),'state':'pending','durable':True,'retry_after':1}
    calls=[]
    monkeypatch.setattr(queue,'submit',lambda *a:dict(receipt))
    def status(*args,**kwargs):
        calls.append(1)
        return dict(receipt)
    monkeypatch.setattr(queue,'status',status)
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post('/v1/requests',headers={**headers(KEYS[0]),'Prefer':'wait=0.1'},json=packet())
    assert response.status_code==202 and response.json()['request_id']==receipt['request_id']
    assert len(calls)==1
