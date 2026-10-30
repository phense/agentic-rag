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
