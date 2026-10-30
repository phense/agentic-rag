"""Orphan recovery pins, revoked authority, and distinct owner/team quotas."""
from dataclasses import replace
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

from agentic_rag import db,store
from agentic_rag.service import requests as queue
from agentic_rag.service.auth import Policy
from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS
from .test_request_queue import packet
from .test_queue_atomicity import paused


def test_live_execution_is_not_reclaimed_and_dead_keeper_cannot_commit(service_store,tmp_path,paused,monkeypatch):
    from starlette.testclient import TestClient
    cfg,_=service_store;app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    entered=threading.Event();release=threading.Event();title='Fenced '+str(uuid.uuid4())
    def slow(*a,**kw):
        entered.set();assert release.wait(10);return None
    monkeypatch.setattr(store,'try_embed_texts',slow)
    with TestClient(app,base_url='https://testserver') as client:
        receipt=client.post('/v1/requests',headers=headers(KEYS[0]),json=packet('memory_save',{'title':title,'body':'Fenced original','domain':'alpha','project':'/projects/a'})).json()['request_id']
        with ThreadPoolExecutor(max_workers=1) as pool:
            task=pool.submit(queue.run_one,cfg)
            assert entered.wait(10)
            assert queue.claim(cfg) is None
            with db.connect(cfg) as conn:
                row=conn.execute('SELECT lease FROM service_requests WHERE id=%s',(receipt,)).fetchone()
                assert row['lease']
                # Keeper holds the request shared pin; the canonical connection
                # has another. Kill only the oldest backend holding that key.
                key=int.from_bytes(__import__('hashlib').sha256(('rag-queue:'+receipt).encode()).digest()[:8],'big',signed=True)
                pids=conn.execute("SELECT DISTINCT l.pid,a.backend_start FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid WHERE locktype='advisory' AND classid=%s AND objid=%s AND objsubid=1 ORDER BY a.backend_start",((key%(1<<64))>>32,key&0xffffffff)).fetchall()
                assert len(pids)>=2
                conn.execute('SELECT pg_terminate_backend(%s)',(pids[0]['pid'],));conn.commit()
            assert queue.claim(cfg) is None  # surviving execution pin blocks replacement
            release.set();assert task.result(timeout=15)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==0


def test_revoked_queued_key_and_changed_scope_never_execute(service_store,tmp_path,paused):
    cfg,_=service_store;app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    principal=Policy.load(p).authenticate_key(KEYS[0])
    receipt=queue.submit(cfg,principal,packet())
    p.write_text(p.read_text().replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
    assert queue.run_one(cfg)
    with db.connect(cfg) as conn:
        result=conn.execute('SELECT state,code,result FROM service_requests WHERE id=%s',(receipt['request_id'],)).fetchone()
        assert result=={'state':'failed','code':'authorization_changed','result':None}


def test_flooded_owner_has_finite_quota_and_other_department_is_admitted(service_store,tmp_path,paused,monkeypatch):
    import pytest
    from agentic_rag.service.engine import ServiceError
    cfg,_=service_store;_,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    one=Policy.load(p).authenticate_key(KEYS[0]);other=Policy.load(p).authenticate_key(KEYS[2])
    monkeypatch.setattr(queue,'MAX_OWNER',3)
    for _ in range(3):queue.submit(cfg,one,packet())
    with pytest.raises(ServiceError,match='request_queue_full'):queue.submit(cfg,one,packet())
    foreign=queue.submit(cfg,other,packet())
    # At most one first dispatch from the previously unserved flooding owner;
    # then the other department is ahead of the flood's remaining requests.
    assert queue.run_one(cfg);assert queue.run_one(cfg)
    assert queue.status(cfg,other,foreign['request_id'])['state']=='completed'
