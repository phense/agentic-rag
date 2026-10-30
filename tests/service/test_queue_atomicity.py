"""Queued writes cannot escape cancellation/revocation or oversized results."""
from dataclasses import replace
import asyncio
import uuid

import pytest
from starlette.testclient import TestClient
from agentic_rag import db
from agentic_rag.service import requests as queue
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS
from .test_request_queue import packet


@pytest.fixture
def paused(monkeypatch):
    async def consume(self):
        await self.stop.wait()
    monkeypatch.setattr(queue.Executor,'consume',consume)


def queued(client, tool='memory_save', arguments=None):
    result=client.post('/v1/requests',headers=headers(KEYS[0]),json=packet(tool,arguments if arguments is not None else {
        'title':'Queued '+str(uuid.uuid4()),'body':'Synthetic queued evidence',
        'domain':'alpha','project':'/projects/a'}))
    assert result.status_code==202,result.text
    return result.json()['request_id']


def test_effect_and_receipt_commit_once(service_store,tmp_path,paused):
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client)
        assert queue.run_one(cfg)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed',result
        doc=result['result']['doc_id']
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE id=%s',(doc,)).fetchone()['n']==1
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE document_id=%s AND op='save_document'",(doc,)).fetchone()['n']==1
        assert not queue.run_one(cfg)


def test_cancel_during_embedding_rolls_back_canonical_effect(service_store,tmp_path,paused,monkeypatch):
    from agentic_rag import embed
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    title='Cancelled '+str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client,arguments={'title':title,'body':'Uncommitted value','domain':'alpha','project':'/projects/a'})
        def cancelled(*args,**kwargs):
            assert client.post('/v1/requests/'+identity+'/cancel',headers=headers(KEYS[0])).json()['state']=='cancelled'
            return None
        from agentic_rag import store
        monkeypatch.setattr(store,'try_embed_texts',cancelled)
        assert queue.run_one(cfg)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==0
        assert client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()['state']=='cancelled'


def test_result_budget_rolls_back_effect(service_store,tmp_path,paused,monkeypatch):
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    from agentic_rag.service import engine
    original=engine.validator('memory_save')[0]
    title='Oversized '+str(uuid.uuid4())
    def huge(**args):
        original(**args)
        return {'oversized':'x'*131073}
    monkeypatch.setattr(engine,'validator',lambda name:(huge,True))
    monkeypatch.setattr(queue,'validator',engine.validator)
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client,arguments={'title':title,'body':'Uncommitted value','domain':'alpha','project':'/projects/a'})
        assert queue.run_one(cfg)
        assert client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()['code']=='result_too_large'
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==0


def test_expiry_replay_and_idempotent_cancel(service_store,tmp_path,paused):
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg)
    from datetime import datetime,timezone,timedelta
    with TestClient(app,base_url='https://testserver') as client:
        value=packet();value['created_at']=(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
        assert client.post('/v1/requests',headers=headers(KEYS[0]),json=value).status_code==409
        identity=queued(client,'memory_domains')
        first=client.post('/v1/requests/'+identity+'/cancel',headers=headers(KEYS[0])).json()
        assert first['state']=='cancelled'
        assert client.post('/v1/requests/'+identity+'/cancel',headers=headers(KEYS[0])).json()==first
        with db.connect(cfg) as conn:
            conn.execute("UPDATE service_requests SET expires_at=now()-interval '20 minutes' WHERE id=%s",(identity,))
            queue.cleanup(conn)
        assert client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).status_code==404


@pytest.mark.parametrize('tool',['memory_domains','memory_save'])
def test_result_publication_waits_for_brief_competing_commit(service_store,tmp_path,paused,tool):
    """Another result's short commit must not fail already accepted work."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client,tool,{} if tool=='memory_domains' else None)
        with db.connect(cfg) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.execute("SELECT pg_advisory_xact_lock(hashtext('request_result_budget'))")
            future=pool.submit(queue.run_one,cfg)
            # Observe the real execution reaching publication, then release the
            # other publisher after a finite interval. No provider is involved.
            deadline=time.monotonic()+5
            while not future.done() and time.monotonic()<deadline:
                waiting=blocker.execute("SELECT count(*) n FROM pg_locks WHERE locktype='advisory' AND NOT granted").fetchone()['n']
                if waiting:break
                time.sleep(.01)
            blocker.commit()
            assert future.result(timeout=5)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed',result
        if tool=='memory_save':
            with db.connect(cfg) as conn:
                assert conn.execute("SELECT count(*) n FROM audit_log WHERE document_id=%s AND op='save_document'",(result['result']['doc_id'],)).fetchone()['n']==1


def test_result_publication_pressure_retains_input_then_retries_once(service_store,tmp_path,paused):
    """A stalled publisher must not turn temporary contention into data loss."""
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    title='Retry publication '+str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client,arguments={'title':title,'body':'Synthetic retry evidence','domain':'alpha','project':'/projects/a'})
        with db.connect(cfg) as blocker:
            blocker.execute("SELECT pg_advisory_xact_lock(hashtext('request_result_budget'))")
            assert queue.run_one(cfg)
            result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
            assert result['state']=='pending',result
            assert result['code']=='result_capacity_exceeded'
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==0
            conn.execute('UPDATE service_requests SET retry_at=now() WHERE id=%s',(identity,))
        assert queue.run_one(cfg)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed',result
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==1
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE document_id=%s AND op='save_document'",(result['result']['doc_id'],)).fetchone()['n']==1
