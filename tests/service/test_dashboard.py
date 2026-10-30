"""Browser contracts: no implicit login, takeover, CSRF or foreign metadata."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import os

from starlette.testclient import TestClient

from agentic_rag import db
from agentic_rag.service.api import create_app
from agentic_rag.service.auth import Policy
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS

ORIGIN={'origin':'https://testserver','x-rag-browser':'1'}


def login(client,user='admin',password='synthetic administrator password'):
    response=client.post('/dashboard/api/login',headers=ORIGIN,json={'username':user,'password':password})
    assert response.status_code==200,response.text
    me=client.get('/dashboard/api/me').json()
    return {**ORIGIN,'x-rag-csrf':me['csrf']}


def test_browser_shell_and_cookie_authority_isolation(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        page=client.get('/dashboard/')
        assert page.status_code==200
        assert 'Content-Security-Policy' in page.headers and 'no-store' in page.headers['cache-control']
        assert client.get('/dashboard/api/me').status_code==401
        csrf=login(client)
        cookie=client.cookies.get('__Host-rag_dashboard')
        assert cookie and 'session.' not in client.get('/dashboard/api/me').text
        assert client.get('/v1/capabilities',headers={'x-rag-protocol':'1'}).status_code==401
        assert client.post('/dashboard/api/logout',headers=ORIGIN,json={}).status_code==403
        assert client.post('/dashboard/api/logout',headers={**csrf,'origin':'https://evil.example'},json={}).status_code==403
        assert client.post('/dashboard/api/logout',headers=csrf,json={}).status_code==200
        assert client.get('/dashboard/api/me').status_code==401


def test_bootstrap_one_claim_and_existing_policy_never_reopens(service_store,tmp_path):
    cfg,_=service_store
    from agentic_rag.service.dashboard_policy import arm_bootstrap
    path=tmp_path/'empty.toml'; token_file=tmp_path/'bootstrap.key'
    arm_bootstrap(path,token_file)
    token=token_file.read_text().strip()
    cfg=replace(cfg,service_auth_file=path)
    app=create_app(cfg,path,allowed_hosts=['testserver'])
    with TestClient(app,base_url='https://testserver') as client:
        payload={'token':token,'username':'first_admin','password':'synthetic first admin password'}
        def claim(_):return client.post('/dashboard/api/bootstrap',headers=ORIGIN,json=payload).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(claim,range(2)))
        assert sorted(codes)==[200,409]
        assert list(Policy.load(path).users)==['first_admin']
        assert client.get('/dashboard/api/bootstrap').json()=={'available':False}
        assert client.post('/dashboard/api/bootstrap',headers=ORIGIN,json=payload).status_code==409
        assert os.stat(path).st_mode&0o077==0


def test_expired_sessions_and_no_machine_dashboard_login(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/dashboard/api/me',headers=headers(KEYS[0])).status_code==401
        csrf=login(client)
        with db.connect(cfg) as conn:conn.execute("UPDATE service_sessions SET expires_at=now()-interval '1 second' WHERE user_id='admin'")
        assert client.get('/dashboard/api/me').status_code==401
        assert client.post('/dashboard/api/logout',headers=csrf,json={}).status_code==401
