"""Adversarial behavior: scope, restart, provenance and bounded controls."""
from dataclasses import replace
from datetime import datetime,timezone
import json
import uuid

from starlette.testclient import TestClient
from agentic_rag import db,store
from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS
from .test_dashboard import login,ORIGIN


def test_readonly_user_no_admin_or_queued_review(service_store,tmp_path):
    cfg,docs=service_store;app,path=app_fixture(tmp_path,cfg)
    path.write_text(path.read_text().replace('write_domains = ["alpha"]','write_domains = []').replace('write_projects = ["/projects/a"]','write_projects = []'))
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client,'alice','correct horse synthetic password')
        assert client.get('/dashboard/api/me').json()['readonly'] is True
        envelope={'tool':'memory_review_claim','arguments':{'id_or_slug':docs['allowed'],'state':'confirmed','reason':'Synthetic review'},'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat()}
        assert client.post('/dashboard/api/tools',headers=csrf,json=envelope).status_code==403
        assert client.get('/dashboard/api/setup').status_code==403
        assert client.get('/dashboard/api/memories?project=/projects/b').json()['total']==0


def test_reported_presence_offline_never_revokes_and_revocation_sticks(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/v1/capabilities',headers={**headers(KEYS[0]),'x-rag-client-version':'0.6.11','x-rag-client-capabilities':'protocol1,queued_tools1,arbitrary-secret-shaped-data'}).status_code==200
        csrf=login(client)
        admin=client.get('/dashboard/api/admin').json();vm=next(x for x in admin['machines'] if x['id']=='vm1')
        assert vm['connection']['freshness']=='online' and vm['connection']['reported_version']=='0.6.11'
        assert vm['connection']['reported_capabilities']=='protocol1,queued_tools1'
        with db.connect(cfg) as conn:conn.execute("UPDATE dashboard_presence SET seen_at=now()-interval '1 day' WHERE principal_id='machine:vm1'")
        vm=next(x for x in client.get('/dashboard/api/admin').json()['machines'] if x['id']=='vm1')
        assert vm['connection']['freshness']=='stale' and vm['access_state']=='enabled'
        rev=client.get('/dashboard/api/policy').json()['revision']
        changed=client.post('/dashboard/api/policy/apply',headers=csrf,json={'revision':rev,'change':{'kind':'revoke','id':'vm1','key_id':'one'},'operation_id':str(uuid.uuid4())})
        assert changed.status_code==200
        assert client.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==401
        vm=next(x for x in client.get('/dashboard/api/admin').json()['machines'] if x['id']=='vm1')
        assert vm['access_state']=='revoked' and vm['connection']['freshness']=='stale'


def test_setup_completion_idempotent_and_file_change_invalidates_checks(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    from agentic_rag.service import dashboard_views as views
    monkeypatch.setattr(views,'_probe',lambda cfg,kind:('verified',kind+'_access_verified'))
    from .http_server import server
    from agentic_rag.service.api import create_app
    token=tmp_path/'discovery.key';token.write_text(KEYS[0]);token.chmod(0o600)
    app.allowed_hosts.append('127.0.0.1')
    with server(app) as target:
        configured=replace(cfg,service_auth_file=path,service_url=target,service_token_file=token)
        dashboard=create_app(configured,path,allowed_hosts=['testserver'])
        with TestClient(dashboard,base_url='https://testserver') as client:
            csrf=login(client)
            assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'central'}).status_code==200
            for check in ['database','permissions','compatibility','provider','embedding']:
                response=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':check})
                assert response.status_code==200,response.text
            one=client.post('/dashboard/api/setup/complete',headers=csrf,json={})
            two=client.post('/dashboard/api/setup/complete',headers=csrf,json={})
            assert one.json()['completed'] and one.json()==two.json()
            path.write_text(path.read_text()+'\n# external operator edit\n')
            changed=client.get('/dashboard/api/setup').json()
            assert not changed['completed'] and all(row['state']=='stale' for row in changed['checks'].values())

def test_browser_body_limits_login_rate_and_unsafe_file_policy(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.post('/dashboard/api/login',headers=ORIGIN,content=b'x'*65537).status_code==415
        assert client.post('/dashboard/api/login',headers={**ORIGIN,'content-type':'application/json'},content=b'x'*65537).status_code==413
        for _ in range(5):assert client.post('/dashboard/api/login',headers=ORIGIN,json={'username':'missing','password':'synthetic wrong password'}).status_code==401
        assert client.post('/dashboard/api/login',headers=ORIGIN,json={'username':'admin','password':'synthetic administrator password'}).status_code==429
        path.chmod(0o644)
        assert client.get('/dashboard/api/bootstrap').status_code==400


def test_control_tables_cannot_be_exposed_to_knowledge_roles(service_store,tmp_path):
    from agentic_rag.service.schema import validate_schema,ServiceSchemaError
    import pytest
    cfg,_=service_store
    with db.connect(cfg) as conn:
        conn.execute('GRANT SELECT ON dashboard_changes TO rag_reader')
        with pytest.raises(ServiceSchemaError):validate_schema(conn)
        conn.rollback()


def test_disabled_owner_does_not_hide_administrator_inventory(service_store,tmp_path):
    from .test_dashboard_policy import apply
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        assert apply(client,csrf,{'kind':'user','id':'alice','fields':{'enabled':False}}).status_code==200
        result=client.get('/dashboard/api/admin')
        assert result.status_code==200,result.text
        vm=next(row for row in result.json()['machines'] if row['id']=='vm1')
        assert vm['access_state']=='owner-disabled' and vm['effective_permissions']=={}
        assert client.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==401
