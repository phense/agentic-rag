"""Adversarial dashboard commit, negotiation and owner-only state regressions."""
from dataclasses import replace
import uuid
import inspect,time

import pytest
from starlette.testclient import TestClient
from agentic_rag import db
from agentic_rag.service import dashboard_policy as dp
from agentic_rag.service.auth import hash_key
from agentic_rag.service.api import create_app
from .test_api import KEYS
from .http_server import server
from .test_scope import service_store
from .test_api import app_fixture,headers
from .test_dashboard import login
from .test_dashboard_policy import apply


def test_revocation_before_store_must_prevent_commit(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    real=dp._store
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=path.read_bytes()
        token=client.cookies.get('__Host-rag_dashboard')
        def revoke_then_store(*args,**kwargs):
            revoked=client.post('/v1/logout',headers=headers(token))
            assert revoked.status_code==200,revoked.text
            return real(*args,**kwargs)
        monkeypatch.setattr(dp,'_store',revoke_then_store)
        response=apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'revoked-session-write'}})
        print('H1 observed',response.status_code,'file_changed',path.read_bytes()!=before,'next_me',client.get('/dashboard/api/me').status_code)
        assert response.status_code in {401,403} and path.read_bytes()==before



def test_policy_replace_serializes_with_real_logout(service_store,tmp_path,monkeypatch):
    """Removing the session-row lock lets logout acknowledge before replace."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    real=dp._replace
    with TestClient(app,base_url='https://testserver') as client,ThreadPoolExecutor(max_workers=1) as pool:
        csrf=login(client);token=client.cookies.get('__Host-rag_dashboard');pending=[]
        def replace_with_concurrent_logout(target,data):
            pending.append(pool.submit(client.post,'/v1/logout',headers=headers(token)))
            # Observe a real blocked DELETE rather than assuming thread scheduling.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with db.connect(cfg) as conn:
                    blocked=conn.execute("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND query LIKE 'DELETE FROM service_sessions WHERE token_hash=%%' AND wait_event_type='Lock'").fetchone()
                if blocked:break
                if pending[0].done():pytest.fail('logout completed before the policy replace')
                time.sleep(.01)
            else:pytest.fail('logout did not reach its bounded session-row wait')
            real(target,data)
        monkeypatch.setattr(dp,'_replace',replace_with_concurrent_logout)
        result=apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'serialized-before-logout'}})
        assert result.status_code==200,result.text
        assert pending[0].result(timeout=3).status_code==200
        assert client.get('/dashboard/api/me').status_code==401
        assert 'serialized-before-logout' in path.read_text()


def test_expiry_after_prepared_journal_prevents_policy_replace(service_store,tmp_path,monkeypatch):
    from agentic_rag.service.auth import hash_key
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    real=dp._recover;operation=str(uuid.uuid4())
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=path.read_bytes();token=client.cookies.get('__Host-rag_dashboard')
        def expire_after_recovery(conn,target):
            real(conn,target)
            with db.connect(cfg) as other:
                other.execute("UPDATE service_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE token_hash=%s",(hash_key(token),))
        monkeypatch.setattr(dp,'_recover',expire_after_recovery)
        response=apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'expired-write'}},operation=operation)
        assert response.status_code==401 and path.read_bytes()==before
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(operation,)).fetchone()['state']=='prepared'
        monkeypatch.setattr(dp,'_recover',real)
        csrf=login(client)
        assert apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'fresh-authority'}}).status_code==200
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(operation,)).fetchone()['state']=='not_applied'


def test_client_setup_must_not_verify_unreachable_unconfigured_target(service_store,tmp_path):
    cfg,_=service_store
    cfg=replace(cfg,service_url='http://127.0.0.1:1',service_token_file=None)
    app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'client'}).status_code==200
        response=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'})
        check=response.json()['checks']['compatibility']
        print('M1 observed',response.status_code,check['state'],check['code'])
        assert check['state']!='verified'



def test_authenticated_compatibility_target_restart_drift_and_revocation(service_store,tmp_path):
    from .http_server import server
    from .test_api import KEYS
    from agentic_rag.service.api import create_app
    from agentic_rag.service.dashboard_policy import identity
    cfg,_=service_store;target,path=app_fixture(tmp_path,cfg);target.allowed_hosts.append('127.0.0.1')
    token=tmp_path/'discovery.key';token.write_text(KEYS[0]);token.chmod(0o600)
    with server(target) as url:
        configured=replace(cfg,service_url=url,service_token_file=token,service_auth_file=path,service_spool_dir=tmp_path/'no-outbox')
        def dashboard():return create_app(configured,path,allowed_hosts=['testserver'])
        with TestClient(dashboard(),base_url='https://testserver') as client:
            csrf=login(client)
            assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'client'}).status_code==200
            response=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'})
            check=response.json()['checks']['compatibility']
            assert check['state']=='verified' and check['code']=='protocol1_queue1_verified'
            assert check['details']['protocol']==1 and check['details']['queued_tools']==1
            assert len(check['details']['target_id'])==64
            assert not configured.service_spool_dir.exists()  # discovery is read-only
        with TestClient(dashboard(),base_url='https://testserver') as restarted:
            csrf=login(restarted)
            assert restarted.get('/dashboard/api/setup').json()['checks']['compatibility']==check
            token.write_text('one.revoked-synthetic-secret')
            assert restarted.get('/dashboard/api/setup').json()['checks']['compatibility']['state']=='stale'
            failed=restarted.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'}).json()['checks']['compatibility']
            assert failed['state']=='unavailable' and failed['code']=='compatibility_authentication_failed'
            assert restarted.post('/dashboard/api/setup/complete',headers=csrf,json={}).status_code==409
            token.write_text(KEYS[0])
            assert restarted.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'}).json()['checks']['compatibility']['state']=='verified'
    # Same configured endpoint, now truly offline; no synthetic success fallback.
    with TestClient(dashboard(),base_url='https://testserver') as client:
        csrf=login(client)
        assert client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'}).json()['checks']['compatibility']['code']=='compatibility_target_unavailable'


@pytest.mark.parametrize('capabilities,code',[
    ({'protocol':2,'extensions':{'queued_tools':1}},'unsupported_protocol'),
    ({'protocol':1,'extensions':{}},'queued_tools_required'),
])
def test_live_compatibility_rejects_protocol_or_queue_drift(service_store,tmp_path,capabilities,code):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from .http_server import server
    from .test_api import KEYS
    cfg,_=service_store
    async def endpoint(request):
        assert request.headers['authorization']=='Bearer '+KEYS[0]
        assert request.headers['x-rag-protocol']=='1'
        return JSONResponse(capabilities)
    token=tmp_path/'probe.key';token.write_text(KEYS[0]);token.chmod(0o600)
    with server(Starlette(routes=[Route('/v1/capabilities',endpoint)])) as target:
        configured=replace(cfg,service_url=target,service_token_file=token)
        app,path=app_fixture(tmp_path,configured)
        with TestClient(app,base_url='https://testserver') as client:
            csrf=login(client)
            assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'central'}).status_code==200
            response=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'})
            check=response.json()['checks']['compatibility']
            assert check['state']=='unavailable' and check['code']==code


def test_clock_expiry_after_fresh_authority_before_replace(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    real=dp.protected_file;delayed=[]
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=path.read_bytes()
        token_hash=hash_key(client.cookies.get('__Host-rag_dashboard'))
        with db.connect(cfg) as conn:
            conn.execute("UPDATE service_sessions SET expires_at=clock_timestamp()+interval '1 second' WHERE token_hash=%s",(token_hash,))
        def read_after_authority(target,*a,**kw):
            raw=real(target,*a,**kw)
            if inspect.currentframe().f_back.f_code.co_name=='_store':
                delayed.append(True);time.sleep(1.15)
            return raw
        monkeypatch.setattr(dp,'protected_file',read_after_authority)
        result=apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'must-not-commit-after-clock-expiry'}})
        assert delayed and result.status_code==401,result.text
        assert path.read_bytes()==before
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM dashboard_changes WHERE policy_id=%s AND state='prepared'",(dp.identity(path),)).fetchone()['n']==1
    print('CLOCK: expiry after exact fresh authority ->401, unchanged bytes, durable prepared audit')


def test_token_changes_during_real_discovery_not_persisted_green(service_store,tmp_path):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    cfg,_=service_store
    token=tmp_path/'synthetic-discovery.key';token.write_text(KEYS[0]);token.chmod(0o600)
    async def endpoint(request):
        assert request.headers['authorization']=='Bearer '+KEYS[0]
        token.write_text('one.changed-synthetic-credential')
        return JSONResponse({'protocol':1,'extensions':{'queued_tools':1},'server_version':'0.6.12'})
    with server(Starlette(routes=[Route('/v1/capabilities',endpoint)])) as target:
        cfg=replace(cfg,service_url=target,service_token_file=token,service_spool_dir=tmp_path/'must-not-create')
        app,path=app_fixture(tmp_path,cfg)
        with TestClient(app,base_url='https://testserver') as client:
            csrf=login(client)
            assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'client'}).status_code==200
            result=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'compatibility'})
            assert result.status_code==409 and result.json()['error']=='setup_configuration_changed',result.text
            assert 'compatibility' not in client.get('/dashboard/api/setup').json()['checks']
            assert not cfg.service_spool_dir.exists()
    print('DISCOVERY: credential drift during real HTTP response ->409; no verified check/outbox')


def test_all_four_setup_modes_resume_complete_without_data_movement(tmp_path,monkeypatch):
    from agentic_rag.config import Config
    from agentic_rag.benchmark.database import isolated_database
    from agentic_rag import llm,embed,query_cache
    monkeypatch.setattr(llm,'run_structured',lambda *a,**k:{'ok':True})
    monkeypatch.setattr(embed,'_embed_texts',lambda texts,cfg,**k:[[0.0]*cfg.embed_dim for _ in texts])
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'independent-synthetic-model')
    with isolated_database(Config(ollama_url='http://127.0.0.1:1')) as owned:
        target,path=app_fixture(tmp_path,owned);target.allowed_hosts.append('127.0.0.1')
        token=tmp_path/'probe.key';token.write_text(KEYS[0]);token.chmod(0o600)
        with server(target) as url:
            cfg=replace(owned,service_url=url,service_token_file=token,service_auth_file=path)
            for mode in ['new-local','existing-local','central','client']:
                with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as client:
                    csrf=login(client)
                    response=client.post('/dashboard/api/setup',headers=csrf,json={'mode':mode})
                    assert response.status_code==200,response.text
                    assert not response.json()['discovery']['existing_data']
                    for check in ['database','permissions','compatibility','embedding','provider']:
                        response=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':check})
                        assert response.status_code==200 and response.json()['checks'][check]['state']=='verified',response.text
                with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as restarted:
                    csrf=login(restarted)
                    state=restarted.get('/dashboard/api/setup').json()
                    assert state['mode']==mode and len(state['checks'])==5
                    one=restarted.post('/dashboard/api/setup/complete',headers=csrf,json={})
                    two=restarted.post('/dashboard/api/setup/complete',headers=csrf,json={})
                    assert one.json()['completed'] and one.json()==two.json()
                    exported=restarted.get('/dashboard/api/setup/export').json()
                    assert exported['mode']==mode and not exported['destructive_actions']
                with db.connect(cfg) as conn: assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==0
                print('MODE:',mode,'5 checks/restart/idempotent complete/export; zero documents before/after')
