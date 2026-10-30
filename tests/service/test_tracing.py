"""Real HTTP/SQL diagnostics: secret capture, scope bypass and origin loss regressions."""
import json
import base64
import uuid
from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from agentic_rag import db
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS


def test_generated_ids_metadata_only_and_current_scope(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    secret='secret-shaped-password-QUERY-and-BODY'
    supplied=str(uuid.uuid4());correlation=str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post('/v1/tools/memory_domains?password='+secret,
            headers={**headers(KEYS[0]),'x-rag-request-id':supplied,'x-rag-correlation-id':correlation,'x-rag-client-version':secret},json={})
        assert response.status_code==200
        identity=response.headers.get('x-rag-request-id')
        assert identity and str(uuid.UUID(identity))==identity and identity!=supplied
        denied=client.post('/not-found/'+secret+'?token='+secret,content=secret)
        assert denied.headers.get('x-rag-request-id')
        listing=client.get('/v1/traces',headers=headers(KEYS[0]),params={'request_id':identity})
        assert listing.status_code==200,listing.text
        row=listing.json()['rows'][0]
        assert row['operation']=='tool.memory_domains' and row['status']==200
        assert row['outcome']=='completed' and row['response_bytes']==len(response.content)
        assert row['correlation_id']==correlation and row['client_version']==''
        assert secret not in json.dumps(listing.json())
        assert client.get('/v1/traces/'+identity,headers=headers(KEYS[2])).status_code==404
        assert client.get('/v1/traces',headers=headers(KEYS[2]),params={'request_id':identity}).json()['total']==0
        assert client.get('/v1/traces/export',headers=headers(KEYS[0])).status_code==403
    with db.connect(cfg) as conn:
        assert secret not in json.dumps([dict(r) for r in conn.execute('SELECT to_jsonb(t) metadata FROM request_traces t')],default=str)


def test_source_and_foreground_origins_survive_replay_pruning_and_retry(service_store,tmp_path):
    from .test_ingest import envelope
    from datetime import datetime,timezone
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    correlation=str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        first=client.post('/v1/windows',headers={**headers(KEYS[0]),'x-rag-correlation-id':correlation},json=envelope(session='trace-origin'))
        assert first.status_code==202
        identity=first.headers['x-rag-request-id'];receipt=first.json()['receipt']
        again=client.post('/v1/windows',headers=headers(KEYS[0]),json=envelope(session='trace-origin'))
        assert again.json()['receipt']==receipt and again.headers['x-rag-request-id']!=identity
        found=client.get('/v1/traces/'+identity,headers=headers(KEYS[0])).json()
        assert found['trace']['outcome']=='accepted' and found['job']['state']=='queued'
        assert found['job']['origin_request_id']==identity and found['job']['origin_correlation_id']==correlation
        with db.connect(cfg) as conn:
            conn.execute("UPDATE service_windows SET state='blocked',result='{\"code\":\"provider_unavailable\"}' WHERE id=%s",(receipt,))
            conn.execute("UPDATE request_traces SET started_at=now()-interval '8 days' WHERE job_id=%s",(receipt,))
        retried=client.post('/v1/jobs/'+receipt+'/retry',headers=headers(KEYS[0]),json={})
        assert retried.status_code==200 and retried.json()['origin_request_id']==identity
        assert client.get('/v1/traces/'+identity,headers=headers(KEYS[0])).status_code==404
        value={'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),'tool':'memory_domains','arguments':{}}
        submitted=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert submitted.status_code==202 and submitted.json()['origin_request_id']==submitted.headers['x-rag-request-id']
        repeated=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert repeated.json()['origin_request_id']==submitted.headers['x-rag-request-id']
        detail=client.get('/v1/traces/'+submitted.headers['x-rag-request-id'],headers=headers(KEYS[0])).json()
        assert detail['job']['state'] in {'pending','running','completed'}
        assert 'result' not in detail['job'] and 'arguments' not in detail['job']
        import psycopg
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg) as conn:conn.execute('UPDATE service_windows SET origin_request_id=%s WHERE id=%s',(uuid.uuid4(),receipt))


def test_mcp_semantic_failure_under_http200_and_rest_result_errors(service_store,tmp_path):
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        for name,args in [('memory_get',{'id_or_slug':'nonexistent'}),('memory_get',{}),('secret-shaped-unknown-tool',{})]:
            response=client.post('/mcp/rw/',headers={**headers(KEYS[0]),'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
            assert response.status_code==200
            row=client.get('/v1/traces/'+response.headers['x-rag-request-id'],headers=headers(KEYS[0])).json()['trace']
            assert row['outcome']=='failed' and row['error_class'] in {'mcp_error','not_found'}, (name,row)
        protocol=client.post('/mcp/rw/',headers={**headers(KEYS[0]),'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'unknown/secret-shaped'})
        assert protocol.status_code==200
        protocol_row=client.get('/v1/traces/'+protocol.headers['x-rag-request-id'],headers=headers(KEYS[0])).json()['trace']
        assert protocol_row['outcome']=='failed' and protocol_row['error_class']=='mcp_error'
        rest=client.post('/v1/tools/memory_get',headers=headers(KEYS[0]),json={'id_or_slug':'nonexistent'})
        row=client.get('/v1/traces/'+rest.headers['x-rag-request-id'],headers=headers(KEYS[0])).json()['trace']
        assert rest.status_code==200 and row['outcome']=='failed'


def _admin(client):
    response=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'admin','password':'synthetic administrator password'})
    assert response.status_code==200
    return headers(response.json()['access_token'])


def test_scopes_policy_realms_and_every_projection(service_store,tmp_path):
    from agentic_rag.service.api import create_app
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        original=client.get('/v1/capabilities',headers=headers(KEYS[0])).headers['x-rag-request-id']
        admin=_admin(client)
        assert client.get('/v1/traces/export',headers=admin,params={'request_id':original}).json()['total']==1
        # Same named account in a different protected policy file is another realm.
        other=tmp_path/'other.toml';other.write_bytes(path.read_bytes());other.chmod(0o600)
        with TestClient(create_app(cfg,other,allowed_hosts=['testserver']),base_url='https://testserver') as second:
            second_admin=_admin(second)
            assert second.get('/v1/traces/export',headers=second_admin,params={'request_id':original}).json()['total']==0
            assert second.get('/v1/traces/'+original,headers=second_admin).status_code==404
        # Administrator scope shrinks without revoking session identity.
        path.write_text(path.read_text().replace('read_domains = ["*"]','read_domains = ["beta"]').replace('write_domains = ["*"]','write_domains = ["beta"]').replace('read_projects = ["*"]','read_projects = ["/projects/b"]').replace('write_projects = ["*"]','write_projects = ["/projects/b"]'))
        for route in ['/v1/traces','/v1/traces/export']:
            result=client.get(route,headers=admin,params={'request_id':original})
            assert result.status_code==200 and result.json()['total']==0 and result.json()['rows']==[]
            assert result.json()['capture']=={'status':'restricted','payload_capture':False}
        assert client.get('/v1/traces/'+original,headers=admin).status_code==404
        # Own identity cannot bypass a revoked envelope either.
        path.write_text(path.read_text().replace('[machines.vm1]','[machines.vm1]\n').replace('read_domains = ["alpha"]','read_domains = []'))
        assert client.get('/v1/traces',headers=headers(KEYS[0]),params={'request_id':original}).json()['total']==0


def test_keyset_filters_bounded_export_and_invalid_inputs(service_store,tmp_path):
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    correlation=str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        identities=[]
        for _ in range(5):identities.append(client.get('/v1/capabilities',headers={**headers(KEYS[0]),'x-rag-correlation-id':correlation}).headers['x-rag-request-id'])
        filters={'operation':'capabilities','principal':'alice','client':'vm1','status':'200','correlation_id':correlation,'limit':'2'}
        first=client.get('/v1/traces',headers=headers(KEYS[0]),params=filters).json()
        assert first['total']==5 and len(first['rows'])==2 and first['next_cursor']
        client.get('/v1/capabilities',headers={**headers(KEYS[0]),'x-rag-correlation-id':correlation})
        second=client.get('/v1/traces',headers=headers(KEYS[0]),params={**filters,'cursor':first['next_cursor']}).json()
        third=client.get('/v1/traces',headers=headers(KEYS[0]),params={**filters,'cursor':second['next_cursor']}).json()
        assert [r['request_id'] for page in [first,second,third] for r in page['rows']]==list(reversed(identities))
        assert third['total']==5 and third['next_cursor'] is None
        admin=_admin(client)
        page=client.get('/v1/traces/export',headers=admin,params={**filters,'cursor':first['next_cursor']}).json()
        assert page['rows']==second['rows'] and page['next_cursor']==second['next_cursor']
        for invalid in [{'limit':'51'},{'cursor':'garbage'},{'status':'secret'},{'since':'yesterday'},{'until':'2026-01-01'},{'job_id':'secret'},{'sql':'DROP'}]:
            assert client.get('/v1/traces',headers=headers(KEYS[0]),params=invalid).status_code==400
        for invalid_id in [123, None, [], {}, True]:
            values=[first['rows'][0]['started_at'],first['rows'][0]['started_at'],invalid_id]
            cursor=base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip('=')
            assert client.get('/v1/traces',headers=headers(KEYS[0]),params={'cursor':cursor}).status_code==400


def test_logger_lock_outage_does_not_change_audited_write(service_store,tmp_path,caplog,monkeypatch):
    from agentic_rag.service import tracing
    import time
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        admin=_admin(client)
        with db.connect(cfg) as locked:
            locked.execute('LOCK TABLE request_traces IN ACCESS EXCLUSIVE MODE')
            start=time.monotonic()
            saved=client.post('/v1/tools/memory_save',headers=headers(KEYS[0]),json={'title':'Audited through trace outage','body':'Synthetic bounded mutation','domain':'alpha','project':'/projects/a'})
            elapsed=time.monotonic()-start
            assert saved.status_code==200 and saved.json()['created'] and elapsed<3
            unavailable=client.get('/v1/traces',headers=admin)
            assert unavailable.status_code==503 and unavailable.json()=={'error':'tracing_unavailable'}
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE document_id=%s AND op='save_document'",(saved.json()['doc_id'],)).fetchone()['n']==1
        state=client.get('/v1/traces',headers=admin).json()['capture']
        assert state['status']=='degraded' and state['dropped']>=1
        messages=[r.getMessage() for r in caplog.records if r.name==tracing.__name__]
        assert messages==['request_tracing_degraded']


def test_retention_capacity_and_permissions_do_not_touch_canonical_data(service_store,tmp_path,monkeypatch):
    from agentic_rag.service import tracing
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    configured=replace(cfg,service_auth_file=path)
    with db.connect(cfg) as conn:
        conn.execute('TRUNCATE request_traces')
        originals=conn.execute('SELECT count(*) n FROM documents').fetchone()['n']
    monkeypatch.setattr(tracing,'MAX_ROWS',2)
    with TestClient(app,base_url='https://testserver') as client:
        for _ in range(4):assert client.get('/health').status_code==200
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM request_traces').fetchone()['n']==2
            conn.execute("UPDATE request_traces SET started_at=now()-interval '8 days'")
        assert tracing.prune(configured)['pruned']==2
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==originals
        assert client.get('/health').status_code==200
    import psycopg
    for role in ['reader','writer','admin']:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg,role=role) as conn:conn.execute('SELECT * FROM request_traces')


@pytest.mark.parametrize('alter',[
    'ALTER COLUMN origin_request_id TYPE text USING origin_request_id::text',
    'ALTER COLUMN origin_correlation_id SET DEFAULT gen_random_uuid()',
])
def test_origin_schema_guard_rejects_nonplain_columns(service_store,alter):
    from agentic_rag.service.schema import validate_schema,ServiceSchemaError
    cfg,_=service_store
    with db.connect(cfg) as conn:
        conn.execute('ALTER TABLE service_requests '+alter)
        with pytest.raises(ServiceSchemaError):validate_schema(conn)
        conn.rollback()


def test_telemetry_scheduler_failure_cannot_override_success(monkeypatch):
    import asyncio
    from agentic_rag.service.tracing import Middleware
    class Recorder:
        dropped=0
        def record(self,*args):raise RuntimeError('secret-shaped exception')
        def failure(self):self.dropped+=1
    async def endpoint(scope,receive,send):
        await send({'type':'http.response.start','status':201,'headers':[]})
        await send({'type':'http.response.body','body':b'applied'})
    endpoint.allowed_hosts=[];recorder=Recorder();middleware=Middleware(endpoint,recorder)
    async def exercise():
        messages=[]
        async def send(message):messages.append(message)
        async def receive():return {'type':'http.request','body':b''}
        await middleware({'type':'http','path':'/health','method':'GET'},receive,send)
        assert messages[0]['status']==201 and messages[1]['body']==b'applied'
        assert recorder.dropped==1
    asyncio.run(exercise())


def test_cancelled_http_logger_retains_admission_until_thread_finishes():
    import asyncio
    import threading
    from agentic_rag.service.tracing import Middleware
    class Recorder:
        calls=0;dropped=0
        def __init__(self):self.release=threading.Event()
        def record(self,*args):
            self.calls+=1
            self.release.wait(timeout=3)
        def failure(self):self.dropped+=1
    async def endpoint(scope,receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'ok'})
    endpoint.allowed_hosts=[];recorder=Recorder();middleware=Middleware(endpoint,recorder)
    async def exercise():
        async def send(message):pass
        async def receive():return {'type':'http.request','body':b''}
        scope={'type':'http','path':'/health','method':'GET'}
        tasks=[asyncio.create_task(middleware(scope,receive,send)) for _ in range(4)]
        for _ in range(200):
            if recorder.calls==4:break
            await asyncio.sleep(.005)
        assert recorder.calls==4
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks)
        assert middleware.pending==4
        for _ in range(20):await middleware(scope,receive,send)
        assert recorder.calls==4 and recorder.dropped==20
        recorder.release.set()
        for _ in range(200):
            if middleware.pending==0:break
            await asyncio.sleep(.005)
        assert middleware.pending==0
    asyncio.run(exercise())


def test_near_capacity_concurrent_metadata_accounting(service_store,tmp_path):
    """Numeric budgets must stay cheap near20k and account at least real JSON bytes."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime,timezone
    import statistics
    import time
    from agentic_rag.service import tracing
    cfg,_=service_store;_,path=app_fixture(tmp_path,cfg)
    configured=replace(cfg,service_auth_file=path)
    with db.connect(cfg) as conn:
        conn.execute('TRUNCATE request_traces')
        conn.execute("""INSERT INTO request_traces(request_id,policy_id,started_at,operation,status,outcome,duration_ms,response_bytes,server_version,logical_bytes)
            SELECT gen_random_uuid(),%s,now()-interval '1 hour','health',200,'completed',1,15,'0.6.13',1200 FROM generate_series(1,19900)""",(tracing.policy_id(configured),))
    recorder=tracing.Recorder(configured)
    def sample(_):
        start=time.perf_counter()
        recorder.record(tracing.Trace(str(uuid.uuid4()),None,datetime.now(timezone.utc),'health'),200,15,1)
        return (time.perf_counter()-start)*1000
    with ThreadPoolExecutor(max_workers=4) as pool:timings=list(pool.map(sample,range(40)))
    with db.connect(cfg) as conn:
        state=conn.execute('SELECT count(*) n,sum(logical_bytes) budget,sum(octet_length(to_jsonb(t)::text)) actual FROM request_traces t').fetchone()
    assert 19900<state['n']<=19940 and state['actual']<=state['budget']<=64*1024*1024
    assert state['n']+recorder.dropped==19940
    assert recorder.degraded==bool(recorder.dropped)
    # This assertion detects accidental unbounded lock waits; not a performance SLA.
    assert max(timings)<3000
    print('TRACE_NEAR_CAPACITY',json.dumps({'rows':state['n'],'captured':state['n']-19900,'dropped':recorder.dropped,'degraded':recorder.degraded,'concurrency':4,'samples':40,'median_ms':round(statistics.median(timings),3),'p95_ms':round(sorted(timings)[37],3),'logical_budget_bytes':state['budget'],'actual_json_bytes':state['actual']}))
    with db.connect(cfg) as conn:conn.execute('TRUNCATE request_traces')


def test_read_only_load_preserves_real_storage_reserve(service_store,tmp_path,monkeypatch):
    from agentic_rag.service import resources
    from agentic_rag.service.auth import Policy
    from collections import namedtuple
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with db.connect(cfg) as conn:
        conn.execute('TRUNCATE request_traces')
        documents=conn.execute('SELECT count(*) n FROM documents').fetchone()['n']
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr(resources.shutil,'disk_usage',lambda path:usage(100000,100000,0))
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/health').status_code==200
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM request_traces').fetchone()['n']==0
        assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==documents
    assert app.recorder.capture(Policy.load(path).principal('admin'))=={'status':'degraded','dropped':1,'payload_capture':False}
