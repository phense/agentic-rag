from starlette.testclient import TestClient

from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS


def packet():
    return {'version':1,'session_id':'compact-s','project':'/projects/a','snapshot':{
        'cursor':'pre-1','turn_id':'turn-1','source':'PreCompact','trigger':'auto',
        'cwd':'/projects/a','transcript_fingerprint':None,'git':{},'artifacts':[],'warnings':[]},
        'handoff':'Continue the synthetic deployment verification.','compacted':True}


def test_owned_checkpoint_handoff_replay_and_scope(service_store,tmp_path,monkeypatch):
    from agentic_rag.continuity import capture
    monkeypatch.setattr(capture,'capture_snapshot',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no server capture')))
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        first=client.post('/v1/checkpoints',headers=headers(KEYS[0]),json=packet())
        assert first.status_code==200,first.text
        assert first.json()['durable'] is True
        second=client.post('/v1/checkpoints',headers=headers(KEYS[0]),json=packet())
        assert first.json()['checkpoint']['id']==second.json()['checkpoint']['id']
        loaded=client.get('/v1/checkpoints/compact-s',headers=headers(KEYS[0]))
        assert loaded.status_code==200 and 'synthetic deployment' in loaded.json()['rendered']
        assert client.get('/v1/checkpoints/compact-s',headers=headers(KEYS[2])).status_code==404
        assert client.post('/v1/checkpoints',headers=headers(KEYS[3]),json=packet()).status_code==403
