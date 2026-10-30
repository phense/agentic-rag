"""Setup and scoped browsing retain data boundaries across application restart."""
import json
from dataclasses import replace

from starlette.testclient import TestClient
from agentic_rag import db
from .test_scope import service_store
from .test_api import app_fixture
from .test_dashboard import login


def test_browse_counts_previews_and_pending_are_scoped(service_store,tmp_path):
    cfg,docs=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client,'alice','correct horse synthetic password')
        result=client.get('/dashboard/api/memories').json()
        assert result['total']==1 and [d['slug'] for d in result['documents']]==['allowed']
        assert 'foreign' not in json.dumps(result)
        assert client.get('/dashboard/api/memories?domain=beta').json()['total']==0
        assert client.get('/dashboard/api/overview').status_code==200
        assert client.get('/dashboard/api/admin').status_code==403


def test_existing_store_modes_resume_and_idempotent_completion(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client)
        state=client.get('/dashboard/api/setup').json()
        assert state['discovery']['existing_data'] is True
        assert client.post('/dashboard/api/setup',headers=csrf,json={'mode':'new-local'}).status_code==409
        selected=client.post('/dashboard/api/setup',headers=csrf,json={'mode':'existing-local'})
        assert selected.status_code==200 and not selected.json()['completed']
        checks=client.post('/dashboard/api/setup/check',headers=csrf,json={'check':'database'})
        assert checks.status_code==200 and checks.json()['checks']['database']['state']=='verified'
    from agentic_rag.service.api import create_app
    with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as client:
        csrf=login(client)
        state=client.get('/dashboard/api/setup').json()
        assert state['mode']=='existing-local' and state['checks']['database']['state']=='verified'
        # Completion refuses missing model/provider checks, instead of a false green.
        assert client.post('/dashboard/api/setup/complete',headers=csrf,json={}).status_code==409
        exported=client.get('/dashboard/api/setup/export')
        assert exported.status_code==200
        assert exported.json()['runtime_settings']=='file-owned-read-only'
        assert 'password' not in exported.text and 'sha256$' not in exported.text
