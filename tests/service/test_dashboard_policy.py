"""Exercise file authority and durable audit with real sessions, never real secrets."""
import json
import uuid

import pytest
from starlette.testclient import TestClient

from agentic_rag import db
from agentic_rag.service.auth import Policy, AuthenticationError
from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS
from .test_dashboard import login,ORIGIN


def apply(client,csrf,change,revision=None,operation=None):
    revision=revision or client.get('/dashboard/api/policy').json()['revision']
    return client.post('/dashboard/api/policy/apply',headers=csrf,json={'revision':revision,'change':change,'operation_id':operation or str(uuid.uuid4())})


def test_rotation_preview_conflict_and_secret_once(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=path.read_bytes()
        policy=client.get('/dashboard/api/policy').json();rev=policy['revision']
        assert 'scrypt$' not in json.dumps(policy) and 'sha256$' not in json.dumps(policy)
        change={'kind':'rotate','id':'vm1','key_id':'one'}
        preview=client.post('/dashboard/api/policy/preview',headers=csrf,json={'revision':rev,'change':change})
        assert preview.status_code==200 and preview.json()['requires_explicit_apply'] and path.read_bytes()==before
        operation=str(uuid.uuid4());saved=apply(client,csrf,change,rev,operation)
        assert saved.status_code==200,saved.text
        secret=saved.json()['secret_once']
        assert Policy.load(path).authenticate_key(secret).machine_id=='vm1'
        assert client.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==401
        assert apply(client,csrf,change,rev,operation).status_code==409
        assert secret not in client.get('/dashboard/api/policy').text
        with db.connect(cfg) as conn:
            rows=conn.execute('SELECT * FROM dashboard_changes WHERE operation_id=%s',(operation,)).fetchall()
            assert len(rows)==1 and rows[0]['state']=='applied' and secret not in str(rows)


def test_last_admin_scope_and_denied_actions(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        for fields in [{'enabled':False},{'admin':False}]:
            assert apply(client,csrf,{'kind':'user','id':'admin','fields':fields}).json()=={'error':'last_administrator_required'}
        assert client.post('/dashboard/api/logout',headers=csrf,json={}).status_code==200
        csrf=login(client,'alice','correct horse synthetic password')
        assert client.get('/dashboard/api/policy').status_code==403
        assert apply(client,csrf,{'kind':'user','id':'alice','fields':{'admin':True}},revision='0'*64).status_code==403


def test_prepared_audit_reconciles_after_file_commit_crash(service_store,tmp_path,monkeypatch):
    from agentic_rag.service import dashboard_policy as policy
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        original=policy._replace
        def crash(path,data):original(path,data);raise OSError('synthetic interruption')
        monkeypatch.setattr(policy,'_replace',crash)
        op=str(uuid.uuid4())
        assert apply(client,csrf,{'kind':'machine','id':'vm1','fields':{'label':'After interruption'}},operation=op).status_code==503
        assert Policy.load(path).machines['vm1']['label']=='After interruption'
        monkeypatch.setattr(policy,'_replace',original)
        assert apply(client,csrf,{'kind':'machine','id':'vm2','fields':{'label':'Next operation'}}).status_code==200
        with db.connect(cfg) as conn:assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(op,)).fetchone()['state']=='applied'


def test_new_user_and_machine_enrollment_retains_requested_fields(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        user={'kind':'user','id':'new_owner','fields':{'label':'New synthetic owner','enabled':True,'admin':False,'read_domains':['alpha'],'write_domains':[],'read_projects':['/projects/a'],'write_projects':[],'session_teams':[]}}
        assert apply(client,csrf,user).status_code==200
        machine={'kind':'machine','id':'new_vm','user':'new_owner','fields':{'label':'New synthetic VM','enabled':True,'read_domains':['alpha'],'write_domains':[],'read_projects':['/projects/a'],'write_projects':[],'session_teams':[]}}
        rev=client.get('/dashboard/api/policy').json()['revision']
        preview=client.post('/dashboard/api/policy/preview',headers=csrf,json={'revision':rev,'change':machine})
        assert preview.status_code==200,preview.text
        assert apply(client,csrf,machine).status_code==200
        policy=Policy.load(path)
        assert policy.users['new_owner']['label']=='New synthetic owner'
        assert policy.machines['new_vm']['user']=='new_owner'
        assert policy.principal('new_owner',machine_id='new_vm').read_domains==frozenset({'alpha'})
