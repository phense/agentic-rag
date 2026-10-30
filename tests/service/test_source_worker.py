"""The central worker reuses accepted mining batches and rechecks live authority."""
from dataclasses import replace

import pytest

from agentic_rag import db, mining
from agentic_rag.service.auth import Policy
from agentic_rag.service.ingest import accept
from .test_scope import service_store
from .test_auth import policy_file
from .test_ingest import envelope


def submitted(cfg,path,session):
    policy=Policy.load(path)
    p=policy.authenticate_key('one.synthetic-long-random-machine-secret')
    receipt=accept(cfg,p,policy,envelope(session=session))['receipt']
    with db.connect(cfg) as conn:
        row=conn.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id WHERE w.id=%s',(receipt,)).fetchone()
    return p,receipt,dict(row)


def extraction():
    return {'memories':[{'title':'Port declaration','body':'server port is now 9000','domain':'alpha',
        'edges':[],'claim_kind':'stated','evidence':[{'source_id':'event-1','quote':'server port is now 9000'}]}]}


def test_source_worker_applies_once_without_a_server_transcript_path(service_store,tmp_path,monkeypatch):
    from agentic_rag.service.worker import process_source
    cfg,_=service_store
    path=policy_file(tmp_path)
    cfg=replace(cfg,service_auth_file=path)
    calls=[]
    monkeypatch.setattr(mining,'run_structured',lambda *args,**kw:calls.append(True) or extraction())
    monkeypatch.setattr(mining,'read_window',lambda *args,**kw:pytest.fail('remote ingestion cannot open a server transcript'))
    p,receipt,job=submitted(cfg,path,'apply-once')
    with db.connect(cfg) as conn:
        first=process_source(conn,cfg,job)
        second=process_source(conn,cfg,job)
        assert first.saved==1 and second.saved==1
        assert calls==[True]
        window=conn.execute('SELECT state,result FROM service_windows WHERE id=%s',(receipt,)).fetchone()
        assert window['state']=='applied'
        row=conn.execute("SELECT d.project_scope,s.namespace,a.actor FROM documents d JOIN claim_evidence e ON e.document_id=d.id JOIN knowledge_sources s USING(source_key) JOIN audit_log a ON a.document_id=d.id AND a.op='save_document' WHERE d.title='Port declaration'").fetchone()
        assert row=={'project_scope':'/projects/a','namespace':p.session_id('apply-once'),'actor':p.actor}


def test_revocation_and_mid_extraction_revocation_retain_source(service_store,tmp_path,monkeypatch):
    from agentic_rag.service.worker import process_source,JobBlocked
    cfg,_=service_store
    path=policy_file(tmp_path);cfg=replace(cfg,service_auth_file=path)
    original=path.read_text()
    _,receipt,job=submitted(cfg,path,'revoked-before')
    path.write_text(original.replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
    with db.connect(cfg) as conn:
        with pytest.raises(JobBlocked):process_source(conn,cfg,job)
        assert conn.execute('SELECT state FROM service_windows WHERE id=%s',(receipt,)).fetchone()['state']=='blocked'
    path.write_text(original)
    with db.connect(cfg) as conn:
        before=conn.execute('SELECT count(*) n FROM claim_evidence').fetchone()['n']
    _,receipt,job=submitted(cfg,path,'revoked-during')
    def revoke(*args,**kw):
        path.write_text(original.replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
        return extraction()
    monkeypatch.setattr(mining,'run_structured',revoke)
    with db.connect(cfg) as conn:
        with pytest.raises(JobBlocked):process_source(conn,cfg,job)
        assert conn.execute('SELECT count(*) n FROM claim_evidence').fetchone()['n']==before
        assert conn.execute('SELECT count(*) n FROM mining_batches WHERE session_id LIKE %s',('%',)).fetchone()['n']>=1
    path.write_text(original)
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:pytest.fail('accepted output must replay without another provider call'))
    with db.connect(cfg) as conn:
        assert process_source(conn,cfg,job).saved==1


def test_database_singleton_survives_commits_and_prevents_another_host(service_store):
    from agentic_rag.worker import acquire_database_lock
    cfg,_=service_store
    with acquire_database_lock(cfg) as first:
        assert first is not None
        first.commit()
        with acquire_database_lock(cfg) as second:assert second is None
    with acquire_database_lock(cfg) as recovered:assert recovered is not None


def test_scoped_deferred_embeddings_recheck_credential_before_application(service_store,tmp_path,monkeypatch):
    from agentic_rag import store,worker
    from agentic_rag.service.context import request_scope
    from agentic_rag.service.worker import JobBlocked
    cfg,_=service_store;path=policy_file(tmp_path);cfg=replace(cfg,service_auth_file=path)
    policy=Policy.load(path);principal=policy.authenticate_key('one.synthetic-long-random-machine-secret')
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with request_scope(principal,cfg),db.connect(cfg,role='writer') as conn:
        saved=store.save_document(conn,cfg,dtype='memory',title='Deferred private embedding',body='A synthetic durable body.',domain='alpha',project='/projects/a',actor=principal.actor)
    with db.connect(cfg) as conn:
        job=dict(conn.execute("SELECT * FROM mining_queue WHERE kind='embed' AND payload->>'document_id'=%s",(saved.doc_id,)).fetchone())
    assert job['payload']['_principal']['user']=='alice'
    original=path.read_text();path.write_text(original.replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
    monkeypatch.setattr(store,'embed_texts',lambda *a,**k:pytest.fail('revoked job reached inference'))
    with db.connect(cfg) as conn:
        with pytest.raises(JobBlocked):worker.process_job(conn,cfg,job)


def test_crash_after_gateway_commit_replays_without_another_provider_call(service_store,tmp_path,monkeypatch):
    from agentic_rag.service.worker import process_source
    cfg,_=service_store;path=policy_file(tmp_path);cfg=replace(cfg,service_auth_file=path)
    policy=Policy.load(path);p=policy.authenticate_key('one.synthetic-long-random-machine-secret')
    data=envelope(session='crash-after-apply');text='[user] The recovery endpoint is port 9307.'
    data['window']['text']=text;data['window']['events'][0]['text']=text
    receipt=accept(cfg,p,policy,data)['receipt']
    with db.connect(cfg) as conn:job=dict(conn.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id WHERE w.id=%s',(receipt,)).fetchone())
    output={'memories':[{'title':'Recovery endpoint','body':'The recovery endpoint is port 9307.','domain':'alpha','edges':[],
        'claim_kind':'stated','evidence':[{'source_id':'event-1','quote':'The recovery endpoint is port 9307.'}]}]}
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:output)
    original=mining.mine_session
    def crash(*a,**k):
        original(*a,**k)
        raise RuntimeError('synthetic crash after gateway commit')
    monkeypatch.setattr(mining,'mine_session',crash)
    with db.connect(cfg) as conn:
        with pytest.raises(RuntimeError):process_source(conn,cfg,job)
    monkeypatch.setattr(mining,'mine_session',original)
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:pytest.fail('recovery repeated provider call'))
    with db.connect(cfg) as conn:
        process_source(conn,cfg,job)
        assert conn.execute('SELECT state FROM service_windows WHERE id=%s',(receipt,)).fetchone()['state']=='applied'
        assert conn.execute('SELECT count(*) n FROM mining_batches WHERE session_id=%s AND applied_at IS NOT NULL',(p.session_id('crash-after-apply'),)).fetchone()['n']==1


def test_provider_outage_retains_window_and_uppercase_cancel_obeys_worker_lock(service_store,tmp_path,monkeypatch):
    from agentic_rag.service.worker import process_source
    from agentic_rag.service.ingest import receipt_status
    from agentic_rag.service.engine import ServiceError
    from agentic_rag.llm import LLMUnavailableError
    cfg,_=service_store;path=policy_file(tmp_path);cfg=replace(cfg,service_auth_file=path)
    p,receipt,job=submitted(cfg,path,'provider-outage')
    def outage(*a,**k):raise LLMUnavailableError('synthetic outage')
    monkeypatch.setattr(mining,'run_structured',outage)
    with db.connect(cfg) as conn:
        with pytest.raises(LLMUnavailableError):process_source(conn,cfg,job)
        assert conn.execute('SELECT state FROM service_windows WHERE id=%s',(receipt,)).fetchone()['state']=='blocked'
        conn.execute("SELECT pg_advisory_lock(hashtext('service_window'),hashtext(%s))",(receipt,));conn.commit()
        with pytest.raises(ServiceError,match='job_in_progress'):receipt_status(cfg,p,receipt.upper(),cancel=True)
    assert receipt_status(cfg,p,receipt.upper(),cancel=True)['state']=='cancelled'
