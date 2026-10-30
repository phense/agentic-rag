"""Regression checks for the first complete Issue68 review."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import uuid
import httpx
import pytest
from agentic_rag import db
from agentic_rag.config import Config
from agentic_rag.service.client import RemoteClient
from agentic_rag.service import requests as queue
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS
from .test_queue_atomicity import paused, queued
from .test_request_queue import packet


def client_config(tmp_path):
    token=tmp_path/'token';token.write_text('synthetic.key');token.chmod(0o600)
    return replace(Config(),service_mode='client',service_url='https://rag.test',service_token_file=token,service_spool_dir=tmp_path/'spool')


@pytest.mark.parametrize('failure',['offline','busy','expired'])
def test_discovery_failure_keeps_identical_durable_local_envelope(tmp_path,failure):
    cfg=client_config(tmp_path)
    def offline(request):
        if failure=='offline':raise httpx.ConnectError('offline')
        return httpx.Response(429 if failure=='busy' else 401,json={'error':'capacity_exceeded' if failure=='busy' else 'invalid_credentials'})
    with httpx.Client(transport=httpx.MockTransport(offline)) as sender,RemoteClient(cfg,sender=sender) as client:
        result=client.invoke('memory_save',{'title':'retained'},seconds=.01)
        assert result['waiting'] and not result['durable']
        original=client.spool.pending_requests()[0]['envelope']
        handle=result['local_request_id']
    posted=[]
    def online(request):
        if request.url.path=='/v1/capabilities':return httpx.Response(200,json={'protocol':1,'extensions':{'queued_tools':1}})
        if request.method=='POST':
            posted.append(request.content.decode())
            return httpx.Response(202,json={'durable':True,'request_id':str(uuid.uuid4()),'state':'pending'})
        return httpx.Response(200,json={'state':'completed','result':{'saved':True}})
    with httpx.Client(transport=httpx.MockTransport(online)) as sender,RemoteClient(cfg,sender=sender) as client:
        assert client.request_status(handle)['result']=={'saved':True}
    assert json.loads(posted[0])==json.loads(original)


def test_uuid_consumption_and_fair_outbox_observation(tmp_path):
    cfg=client_config(tmp_path);seen=[]
    def online(request):
        identity=request.url.path.rsplit('/',1)[-1];seen.append(identity)
        return httpx.Response(200,json={'state':'completed','result':{'ok':True}})
    with httpx.Client(transport=httpx.MockTransport(online)) as sender,RemoteClient(cfg,sender=sender) as client:
        identities=[]
        for n in range(9):
            handle=client.spool.stage_request('memory_domains',{'index':n});identity=str(uuid.uuid4())
            client.spool.request_ack(handle,identity);identities.append(identity)
        client.flush_requests(seconds=10);client.flush_requests(seconds=10)
        assert len(set(seen))==9
        client.request_status(identities[0])
        assert len(client.spool.pending_requests())==8


def test_completed_result_gc_never_claims_null_success(service_store,tmp_path,paused):
    cfg,_=service_store;app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with __import__('starlette.testclient',fromlist=['TestClient']).TestClient(app,base_url='https://testserver') as client:
        value=packet();response=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        identity=response.json()['request_id'];assert queue.run_one(cfg)
        with db.connect(cfg) as conn:
            conn.execute("UPDATE service_requests SET expires_at=now()-interval '1 second' WHERE id=%s",(identity,));queue.cleanup(conn)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed' and result['code']=='result_expired'
        replay=client.post('/v1/requests',headers=headers(KEYS[0]),json=value).json()
        assert replay['code']=='result_expired'


def test_slow_write_does_not_block_durable_read_acceptance(service_store,tmp_path,paused,monkeypatch):
    from starlette.testclient import TestClient
    from agentic_rag import store
    cfg,_=service_store;app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    responses=[]
    with TestClient(app,base_url='https://testserver') as client:
        queued(client)
        def embed(*args,**kwargs):
            responses.append(client.post('/v1/requests',headers=headers(KEYS[0]),json=packet()))
            return None
        monkeypatch.setattr(store,'try_embed_texts',embed)
        assert queue.run_one(cfg)
    assert responses[0].status_code==202,responses[0].text


def test_worker_maintenance_obeys_foreground_and_resumes(service_store,monkeypatch):
    from agentic_rag import worker
    from agentic_rag.service.priority import foreground
    cfg,_=service_store;cfg=replace(cfg,service_mode='server')
    with db.connect(cfg) as conn:conn.execute("UPDATE service_requests SET state='cancelled' WHERE state IN ('pending','running')")
    calls=[]
    monkeypatch.setattr(worker,'requeue_orphans',lambda *a:None)
    monkeypatch.setattr(worker,'drain',lambda *a:{'provider_unavailable':0})
    monkeypatch.setattr(worker.jobs,'last_curation_at',lambda *a:None)
    monkeypatch.setattr(worker.curation,'run_pass',lambda *a:calls.append('curation'))
    monkeypatch.setattr(worker,'_opportunistic_backup',lambda *a:calls.append('backup'))
    with foreground(cfg):worker._run_owned(cfg)
    assert calls==[]
    worker._run_owned(cfg)
    assert calls==['curation','backup']


def test_current_release_supported_for_operator(service_store):
    from agentic_rag.service.upgrade import inventory
    cfg,_=service_store
    result=inventory(cfg,'0.6.11')
    assert result


def test_source_receipt_retains_actual_extraction_state_after_ack(tmp_path):
    cfg=client_config(tmp_path)
    from agentic_rag.service.spool import Spool
    with Spool(cfg.service_spool_dir/'spool.sqlite','placeholder'):pass
    def online(request):return httpx.Response(200,json={'state':'applied'})
    with httpx.Client(transport=httpx.MockTransport(online)) as sender,RemoteClient(cfg,sender=sender) as client:
        identity=str(uuid.uuid4())
        client.spool.conn.execute('INSERT INTO receipts VALUES(?,?,?,?)',('original',client.partition,json.dumps({'receipt':identity,'session':'s','kind':'window','state':'queued'}),0));client.spool.conn.commit()
        assert client.extraction_states('s')[0]['state']=='applied'
        assert client.spool.extraction_states('s')[0]['state']=='applied'
        assert client.spool.extraction_states('foreign')==[]


def test_transient_execution_pressure_retains_accepted_input(service_store,tmp_path,paused,monkeypatch):
    from agentic_rag.service import engine
    from agentic_rag.service.auth import Policy
    cfg,_=service_store;_,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with db.connect(cfg) as conn:conn.execute("UPDATE service_requests SET state='cancelled' WHERE state IN ('pending','running')")
    principal=Policy.load(p).authenticate_key(KEYS[0]);receipt=queue.submit(cfg,principal,packet())
    real=queue.invoke
    async def pressure(*a,**kw):raise engine.ResourcePressure('model_busy',429)
    monkeypatch.setattr(queue,'invoke',pressure)
    assert queue.run_one(cfg)
    assert queue.status(cfg,principal,receipt['request_id'])['state']=='pending'
    monkeypatch.setattr(queue,'invoke',real)
    assert not queue.run_one(cfg)
    with db.connect(cfg) as conn:conn.execute('UPDATE service_requests SET retry_at=now() WHERE id=%s',(receipt['request_id'],))
    assert queue.run_one(cfg)
    assert queue.status(cfg,principal,receipt['request_id'])['state']=='completed'


def test_40_bounded_requests_fairness_and_poll_abuse(service_store,tmp_path,paused,monkeypatch):
    from starlette.testclient import TestClient
    from agentic_rag.service.auth import Policy
    cfg,_=service_store;app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with db.connect(cfg) as conn:conn.execute("UPDATE service_requests SET state='cancelled' WHERE state IN ('pending','running')")
    policy=Policy.load(p);one=policy.authenticate_key(KEYS[0]);other=policy.authenticate_key(KEYS[2])
    receipts=[queue.submit(cfg,one if n<39 else other,packet()) for n in range(40)]
    assert queue.run_one(cfg) and queue.run_one(cfg)
    assert queue.status(cfg,other,receipts[-1]['request_id'])['state']=='completed'
    for _ in range(38):assert queue.run_one(cfg)
    assert all(queue.status(cfg,one if n<39 else other,r['request_id'])['state']=='completed' for n,r in enumerate(receipts))
    with TestClient(app,base_url='https://testserver') as client:
        codes=[client.get('/v1/requests/'+receipts[0]['request_id'],headers=headers(KEYS[0])).status_code for _ in range(25)]
        assert 429 in codes
        assert client.get('/v1/requests/'+receipts[0]['request_id'],headers=headers(KEYS[2])).status_code==404


def test_process_kill_reclaims_uncommitted_write_once(service_store,tmp_path,paused,monkeypatch):
    import os,subprocess,sys,time
    from agentic_rag import store
    from agentic_rag.service.auth import Policy
    cfg,_=service_store;_,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    with db.connect(cfg) as conn:conn.execute("UPDATE service_requests SET state='cancelled' WHERE state IN ('pending','running')")
    principal=Policy.load(p).authenticate_key(KEYS[0]);title='Process restart '+str(uuid.uuid4())
    receipt=queue.submit(cfg,principal,packet('memory_save',{'title':title,'body':'Synthetic restart claim','domain':'alpha','project':'/projects/a'}))
    marker=tmp_path/'inside-embedding'
    program='''from pathlib import Path
from agentic_rag.config import Config
from agentic_rag import store
from agentic_rag.service.requests import run_one
import time,sys
cfg=Config(db_name=sys.argv[1],service_auth_file=Path(sys.argv[2]),ollama_url='http://127.0.0.1:1')
def wait(*a,**kw):
 Path(sys.argv[3]).write_text('entered');time.sleep(60)
store.try_embed_texts=wait
run_one(cfg)
'''
    child=subprocess.Popen([sys.executable,'-c',program,cfg.db_name,str(p),str(marker)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+15
        while not marker.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert marker.exists()
        child.kill();child.wait(timeout=10)
        monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
        assert queue.run_one(cfg)
        result=queue.status(cfg,principal,receipt['request_id'])
        assert result['state']=='completed',result
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents WHERE title=%s',(title,)).fetchone()['n']==1
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE document_id=%s AND op='save_document'",(result['result']['doc_id'],)).fetchone()['n']==1
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=10)
        child.stderr.close()
