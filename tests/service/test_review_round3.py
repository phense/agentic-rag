"""Final S2 review regressions: revoked human jobs and idempotent cancellation."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from agentic_rag import db,mining
from agentic_rag.service.api import authenticate
from agentic_rag.service.auth import Policy
from agentic_rag.service.ingest import accept,receipt_status
from agentic_rag.service.worker import process_source,JobBlocked
from .test_worker_fencing import owned,window
from .test_api import app_fixture,headers


@pytest.mark.parametrize('revoke',['logout','expire','during_provider'])
def test_human_jobs_cannot_continue_after_session_revocation(owned,tmp_path,monkeypatch,revoke):
    cfg,_=owned;app,path=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=path)
    calls=[]
    with TestClient(app,base_url='https://testserver') as client:
        login=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'alice','password':'correct horse synthetic password'})
        assert login.status_code==200
        token=login.json()['access_token'];policy=Policy.load(path);principal=authenticate(policy,cfg,token)
        receipt=client.post('/v1/windows',headers=headers(token),json=window()).json()['receipt']
        def revoke_session():
            # Worker rechecks may run with SQL scope active: emulate independent
            # logout HTTP transport outside that immutable request context.
            from agentic_rag.service.context import CURRENT
            state=CURRENT.set(None)
            try:
                if revoke=='expire':
                    with db.connect(cfg) as conn:conn.execute("UPDATE service_sessions SET expires_at=now()-interval '1 minute'")
                else:assert client.post('/v1/logout',headers=headers(token),json={}).status_code==200
            finally:CURRENT.reset(state)
        if revoke!='during_provider':revoke_session()
        def provider(*a,**k):
            calls.append(1);revoke_session()
            return {'memories':[dict(title='Revoked human memory',body='server port is now 9000',domain='alpha',edges=[],claim_kind='stated',evidence=[dict(source_id='event-1',quote='server port is now 9000')])]}
        monkeypatch.setattr(mining,'run_structured',provider)
        with db.connect(cfg) as conn:
            job=dict(conn.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON w.queue_id=q.id WHERE w.id=%s',(receipt,)).fetchone())
            with pytest.raises(JobBlocked):process_source(conn,cfg,job)
            assert conn.execute("SELECT count(*) n FROM documents WHERE title='Revoked human memory'").fetchone()['n']==0
        assert calls==([1] if revoke=='during_provider' else [])


def test_repeated_cancel_under_pressure_has_no_additional_writes(owned):
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    receipt=accept(cfg,p,policy,window())['receipt']
    receipt_status(cfg,p,receipt,cancel=True)
    with db.connect(cfg) as conn:
        before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
        original=dict(conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone())
    pressured=replace(cfg,service_max_database_bytes=1)
    for _ in range(5):assert receipt_status(pressured,p,receipt,cancel=True)['state']=='cancelled'
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before
        assert dict(conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone())==original


def test_job_status_exposes_only_allowlisted_block_reason(owned,monkeypatch):
    from agentic_rag.service import resources
    from agentic_rag.service.engine import ResourcePressure
    cfg,policy=owned;p=policy.authenticate_key('review.synthetic-key-for-isolated-probe')
    receipt=accept(cfg,p,policy,window())['receipt']
    monkeypatch.setattr(resources.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:{})
    with db.connect(cfg) as conn:
        job=dict(conn.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON w.queue_id=q.id WHERE w.id=%s',(receipt,)).fetchone())
        with pytest.raises(ResourcePressure):process_source(conn,cfg,job)
    assert receipt_status(cfg,p,receipt)['code']=='storage_low'
    with db.connect(cfg) as conn:conn.execute("UPDATE service_windows SET result=%s WHERE id=%s",('{"code":"/srv/private/path"}',receipt))
    assert receipt_status(cfg,p,receipt).get('code') is None


def test_utf8_diagnostic_limit_counts_bytes_and_prefix(tmp_path):
    from agentic_rag.bounded_log import append
    path=tmp_path/'unicode.log';append(path,'😀'*9000)
    assert 0<len(path.read_bytes())<=8192
    assert path.read_text().endswith('\n')
