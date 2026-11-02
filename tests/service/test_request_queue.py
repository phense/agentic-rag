"""Queue acceptance, authorization and effect/result atomicity through real HTTP/SQL."""
from datetime import datetime, timezone
import uuid
import pytest
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


@pytest.mark.parametrize("initial,observed,code,lookups", [("pending","pending",202,1),("pending","completed",200,1),("completed","completed",200,0)])
def test_submit_short_wait_checks_status_once(service_store,tmp_path,monkeypatch,initial,observed,code,lookups):
    """A 100ms preference must not create ten owner DB sessions per submit."""
    from agentic_rag.service import requests as queue
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    receipt={'request_id':str(uuid.uuid4()),'state':initial,'durable':True,'retry_after':1}
    calls=[]
    monkeypatch.setattr(queue,'submit',lambda *a:dict(receipt))
    def status(*args,**kwargs):
        calls.append(1)
        return {**receipt,'state':observed}
    monkeypatch.setattr(queue,'status',status)
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post('/v1/requests',headers={**headers(KEYS[0]),'Prefer':'wait=0.1'},json=packet())
    assert response.status_code==code and response.json()['request_id']==receipt['request_id']
    assert len(calls)==lookups


@pytest.mark.parametrize("fail_after_insert", [False, True])
def test_submit_reuses_admission_session_and_commits_receipt(service_store,tmp_path,monkeypatch,fail_after_insert):
    from agentic_rag import db
    from agentic_rag.service import requests as queue
    from agentic_rag.service.auth import Policy
    cfg,_=service_store
    _,path=app_fixture(tmp_path,cfg)
    principal=Policy.load(path).authenticate_key(KEYS[0])
    real=db.connect
    opened=[]
    def connect(*args,**kwargs):
        conn=real(*args,**kwargs)
        opened.append(conn)
        return conn
    monkeypatch.setattr(db,'connect',connect)
    value=packet()
    identity=uuid.uuid5(uuid.NAMESPACE_URL,principal.namespace+':'+value['idempotency_key'])
    if fail_after_insert:
        def fail(*args,**kwargs):raise RuntimeError('injected after insert')
        monkeypatch.setattr(queue.tracing,'link_job',fail)
        with pytest.raises(RuntimeError,match='injected after insert'):
            queue.submit(cfg,principal,value)
    else:
        receipt=queue.submit(cfg,principal,value)
        assert receipt['request_id']==str(identity)
    assert len(opened)==1
    assert opened[0].closed
    with real(cfg) as conn:
        row=conn.execute('SELECT state FROM service_requests WHERE id=%s',(identity,)).fetchone()
        assert row is None if fail_after_insert else row['state']=='pending'


@pytest.mark.parametrize('fail_after_insert',[False,True])
def test_submit_holds_admission_until_commit_or_rollback(service_store,tmp_path,monkeypatch,fail_after_insert):
    from agentic_rag import db
    from agentic_rag.service import requests as queue
    from agentic_rag.service.auth import Policy
    from agentic_rag.service.engine import ResourcePressure
    cfg,_=service_store
    _,path=app_fixture(tmp_path,cfg)
    principal=Policy.load(path).authenticate_key(KEYS[0])
    seen=[]
    def before_commit(*args,**kwargs):
        with db.connect(cfg) as other:
            assert not other.execute('SELECT pg_try_advisory_xact_lock(%s) ok',(5840919371552461,)).fetchone()['ok']
        with pytest.raises(ResourcePressure,match='write_capacity_exceeded'):
            queue.submit(cfg,principal,packet())
        seen.append(True)
        if fail_after_insert:raise RuntimeError('abort before commit')
    monkeypatch.setattr(queue.tracing,'link_job',before_commit)
    if fail_after_insert:
        with pytest.raises(RuntimeError,match='abort before commit'):queue.submit(cfg,principal,packet())
    else:queue.submit(cfg,principal,packet())
    assert seen==[True]
    with db.connect(cfg) as other:
        assert other.execute('SELECT pg_try_advisory_xact_lock(%s) ok',(5840919371552461,)).fetchone()['ok']
