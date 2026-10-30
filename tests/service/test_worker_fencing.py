"""Verified S2 concurrency regressions; writes only to owned disposable databases."""
from contextlib import contextmanager
from dataclasses import replace
import json
import threading
from unittest.mock import patch

import pytest
from agentic_rag import db, mining, store, worker, query_cache
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service.auth import Policy, hash_key
from agentic_rag.service.ingest import accept, receipt_status
from agentic_rag.service.worker import process_source

@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(mining, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(query_cache, 'model_digest', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'LOG_PATH', tmp_path/'worker.log')
    policy = tmp_path/'policy.toml'
    policy.write_text('version=1\n[users.review]\nread_domains=["alpha"]\nwrite_domains=["alpha"]\nread_projects=["/projects/a"]\nwrite_projects=["/projects/a"]\n[machines.review]\nuser="review"\nread_domains=["alpha"]\nwrite_domains=["alpha"]\nread_projects=["/projects/a"]\nwrite_projects=["/projects/a"]\nkeys={review="'+hash_key('review.synthetic-key-for-isolated-probe')+'"}\n')
    policy.chmod(0o600)
    cfg=Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1',service_auth_file=policy)
    with isolated_database(cfg) as cfg:
        with db.connect(cfg) as c: c.execute("INSERT INTO domains(name) VALUES ('alpha')")
        yield cfg,Policy.load(policy)


def window():
    text='[user] server port is now 9000'
    return dict(version=1,session_id='probe',project='/projects/a',input_cursor='',output_cursor='cursor-1',window=dict(text=text,events=[dict(source_id='event-1',role='user',timestamp=None,text=text,offset=0,complete=True)],warnings=[],synthetic=False,has_more=False))


def test_cancel_must_recognize_already_committed_mining_batch(owned,monkeypatch):
    from agentic_rag.service.engine import ServiceError
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    receipt=accept(cfg,p,policy,window())['receipt']
    with db.connect(cfg) as c:
        job=dict(c.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id WHERE w.id=%s',(receipt,)).fetchone())
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:{'memories':[dict(title='Port declaration',body='server port is now 9000',domain='alpha',edges=[],claim_kind='stated',evidence=[dict(source_id='event-1',quote='server port is now 9000')])]})
    original=mining.mine_session
    def crash(*a,**k):
        original(*a,**k)
        raise RuntimeError('synthetic crash after knowledge commit before receipt commit')
    monkeypatch.setattr(mining,'mine_session',crash)
    with db.connect(cfg) as c:
        with pytest.raises(RuntimeError):process_source(c,cfg,job)
        saved=c.execute("SELECT count(*) n FROM documents WHERE title='Port declaration'").fetchone()['n']
        applied=c.execute('SELECT count(*) n FROM mining_batches WHERE session_id=%s AND applied_at IS NOT NULL',(p.session_id('probe'),)).fetchone()['n']
    assert saved==1 and applied==1
    with pytest.raises(ServiceError,match="already_applied") as exc:
        receipt_status(cfg,p,receipt,cancel=True)
    assert exc.value.status==409


def test_runner_must_fence_live_worker_after_lock_connection_loss(owned,monkeypatch):
    from agentic_rag.service.runner import run
    cfg,_=owned;stop=threading.Event();observed={}
    real_lock=worker.acquire_database_lock
    @contextmanager
    def tracked_lock(cfg):
        with real_lock(cfg) as first:
            observed['pid']=first.info.backend_pid
            yield first
    monkeypatch.setattr(worker,'acquire_database_lock',tracked_lock)
    monkeypatch.setattr(worker,'requeue_orphans',lambda *a,**k:0)
    def drain(connection,cfg,**kw):
        from agentic_rag.service.fence import LEASE, WorkerAuthorityLost
        # Fault injector/replacement are independent processes, outside the old lease.
        token=LEASE.set(None)
        try:
            with db.connect(cfg) as owner:
                assert owner.execute('SELECT pg_terminate_backend(%s) ok',(observed['pid'],)).fetchone()['ok']
            with real_lock(cfg) as replacement:
                observed['replacement_acquired']=replacement is not None
        finally:LEASE.reset(token)
        with pytest.raises(WorkerAuthorityLost):
            connection.execute('SELECT 1 AS ok')
        observed['old_worker_still_operates']=False
        stop.set()
    monkeypatch.setattr(worker,'drain',drain)
    status=run(cfg,stop=stop,interval=.01)
    assert status==1
    print('LOCK_CONNECTION_LOSS',json.dumps(dict(observed,runner_return=status)))
    assert not (observed['replacement_acquired'] and observed['old_worker_still_operates']), 'New singleton and unfenced old worker are both active'


def test_successful_cancellation_must_not_be_resurrected_by_failure_cleanup(owned,monkeypatch,tmp_path):
    from agentic_rag.service import worker as source_worker
    from agentic_rag import provider_health
    from agentic_rag.llm import LLMUnavailableError
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    monkeypatch.setattr(provider_health,'HEALTH_PATH',tmp_path/'provider-health.json')
    receipt=accept(cfg,p,policy,window())['receipt'];original_state=source_worker._state;cancelled=[]
    def outage(*a,**k):raise LLMUnavailableError('synthetic outage')
    monkeypatch.setattr(mining,'run_structured',outage)
    def cancellation_between_unlock_and_failure_state(conn,receipt,state,code):
        # process_source has closed its scoped connection (and advisory lock)
        # before invoking _state. A concurrent HTTP cancel can win here.
        cancelled.append(receipt_status(cfg,p,receipt,cancel=True))
        return original_state(conn,receipt,state,code)
    monkeypatch.setattr(source_worker,'_state',cancellation_between_unlock_and_failure_state)
    with db.connect(cfg) as c:
        worker.drain(c,cfg,max_jobs=1)
        row=c.execute('SELECT w.state,q.status,q.next_attempt_at FROM service_windows w JOIN mining_queue q ON q.id=w.queue_id WHERE w.id=%s',(receipt,)).fetchone()
        print('CANCEL_RACE',json.dumps(dict(cancel_ack=cancelled[0],after_cleanup=row),default=str))
    assert row['state']=='cancelled' and row['status']=='done', 'A durable successful cancellation was overwritten and requeued by failed worker cleanup'


@pytest.mark.parametrize('lost_backend',['keeper','main'])
def test_real_workers_must_not_infer_concurrently_after_lock_loss(owned,monkeypatch,lost_backend):
    from agentic_rag.service.runner import run
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    for session in ('first-live','second-replacement'):
        packet=window();packet['session_id']=session
        accept(cfg,p,policy,packet)
    first_in_provider=threading.Event();replacement_in_provider=threading.Event();release_first=threading.Event()
    stop_first=threading.Event();stop_second=threading.Event();errors=[];pids={};observed=[]
    real_requeue=worker.requeue_orphans
    def record_parent(conn,cfg):
        pids[threading.current_thread().name+'-main']=conn.info.backend_pid
        return real_requeue(conn,cfg)
    monkeypatch.setattr(worker,'requeue_orphans',record_parent)
    real_lock=worker.acquire_database_lock
    @contextmanager
    def tracked(cfg):
        with real_lock(cfg) as connection:
            if connection is not None:pids[threading.current_thread().name]=connection.info.backend_pid
            yield connection
    monkeypatch.setattr(worker,'acquire_database_lock',tracked)
    def provider(*a,**kw):
        name=threading.current_thread().name
        observed.append(name)
        if name=='first-worker':
            first_in_provider.set()
            assert release_first.wait(10),'test timeout waiting for replacement'
            stop_first.set()
        else:
            replacement_in_provider.set();stop_second.set()
        return {}
    monkeypatch.setattr(mining,'run_structured',provider)
    def launch(stop):
        try:run(cfg,stop=stop,interval=.01)
        except BaseException as error:errors.append(repr(error))
    first=threading.Thread(name='first-worker',target=launch,args=(stop_first,))
    second=threading.Thread(name='replacement-worker',target=launch,args=(stop_second,))
    first.start()
    try:
        assert first_in_provider.wait(10)
        with db.connect(cfg) as owner:
            assert owner.execute('SELECT pg_terminate_backend(%s) ok',(pids['first-worker' if lost_backend=='keeper' else 'first-worker-main'],)).fetchone()['ok']
        second.start()
        replacement_started=replacement_in_provider.wait(5)
        print('REAL_PARALLEL_PROVIDER',json.dumps(dict(old_provider_still_running=first.is_alive() and not release_first.is_set(),replacement_provider_started=replacement_started,provider_threads=observed,errors=errors)))
    finally:
        release_first.set();stop_first.set();stop_second.set()
        first.join(10)
        if second.ident:second.join(10)
    assert not errors,errors
    assert not replacement_started,'Two real service runners reached mocked inference concurrently after lock-session loss'


def test_lost_authority_blocks_apply_then_replays_accepted_batch_without_provider(owned,monkeypatch):
    from agentic_rag.service import worker as source_worker
    from agentic_rag.service.fence import LEASE, worker_scope, WorkerAuthorityLost
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    receipt=accept(cfg,p,policy,window())['receipt']
    real_principal=source_worker._principal;checks=[];calls=[]
    def provider(*a,**k):
        calls.append(1)
        return {'memories':[dict(title='Fenced port declaration',body='server port is now 9000',domain='alpha',edges=[],claim_kind='stated',evidence=[dict(source_id='event-1',quote='server port is now 9000')])]}
    monkeypatch.setattr(mining,'run_structured',provider)
    with worker.acquire_database_lock(cfg) as keeper:
        def revoke_after_accept(*a):
            result=real_principal(*a);checks.append(1)
            if len(checks)==2:
                token=LEASE.set(None)
                try:
                    with db.connect(cfg) as fault:
                        assert fault.execute('SELECT pg_terminate_backend(%s) ok',(keeper.info.backend_pid,)).fetchone()['ok']
                finally:LEASE.reset(token)
            return result
        monkeypatch.setattr(source_worker,'_principal',revoke_after_accept)
        with pytest.raises(WorkerAuthorityLost):
            with worker_scope(keeper),db.connect(cfg,role='writer') as conn:
                worker.drain(conn,cfg,max_jobs=1)
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM mining_batches WHERE applied_at IS NULL').fetchone()['n']==1
        assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==0
    monkeypatch.setattr(source_worker,'_principal',real_principal)
    with worker.acquire_database_lock(cfg) as replacement:
        assert replacement is not None
        with worker_scope(replacement),db.connect(cfg,role='writer') as conn:
            worker.requeue_orphans(conn,cfg)
            assert worker.drain(conn,cfg,max_jobs=1)['done']==1
    assert len(calls)==1
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT state FROM service_windows WHERE id=%s',(receipt,)).fetchone()['state']=='applied'
        assert conn.execute("SELECT count(*) n FROM documents WHERE title='Fenced port declaration'").fetchone()['n']==1
