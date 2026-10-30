"""Storage pressure rejects new work without losing acknowledged input or replay."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from agentic_rag import db
from .test_worker_fencing import owned, window
from .test_api import app_fixture, headers, KEYS


def test_pending_quota_preserves_replay_cancel_and_reads(owned,tmp_path):
    cfg,_=owned
    cfg=replace(cfg,service_max_pending_per_owner=1)
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        data=window()
        first=client.post('/v1/windows',headers=headers(KEYS[0]),json=data)
        assert first.status_code==202,first.text
        receipt=first.json()['receipt']
        other=window();other['session_id']='additional'
        rejected=client.post('/v1/windows',headers=headers(KEYS[0]),json=other)
        assert rejected.status_code==429 and rejected.json()['error']=='owner_backlog_full'
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=data).json()['receipt']==receipt
        assert client.get('/v1/jobs/'+receipt,headers=headers(KEYS[0])).status_code==200
        assert client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(KEYS[0]),json={}).status_code==200
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=other).status_code==202
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM service_windows').fetchone()['n']==2


@pytest.mark.parametrize('pressure,expected',[('disk','storage_low'),('database','database_budget_exceeded'),('pending','backlog_full'),('bytes','backlog_bytes_exceeded')])
def test_pressure_rejects_new_writes_but_not_reads_or_ack_replay(owned,tmp_path,monkeypatch,pressure,expected):
    from agentic_rag.service import resources
    cfg,_=owned
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        packet=window();first=client.post('/v1/windows',headers=headers(KEYS[0]),json=packet)
        assert first.status_code==202
        if pressure=='disk':monkeypatch.setattr(resources.shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
        elif pressure=='database':cfg=replace(cfg,service_max_database_bytes=1)
        elif pressure=='pending':cfg=replace(cfg,service_max_pending=1)
        else:cfg=replace(cfg,service_max_pending_bytes=1)
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=packet).json()['receipt']==first.json()['receipt']
        packet['session_id']='new'
        response=client.post('/v1/windows',headers=headers(KEYS[0]),json=packet)
        assert response.status_code in {429,507} and response.json()['error']==expected,response.text
        assert client.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==200
        assert client.get('/v1/jobs/'+first.json()['receipt'],headers=headers(KEYS[0])).status_code==200
        if pressure in {'disk','database'}:
            response=client.post('/v1/tools/memory_save',headers=headers(KEYS[0]),json={'title':'quota','body':'must not commit','domain':'alpha','project':'/projects/a'})
            assert response.status_code==507 and response.json()['error']==expected,response.text
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM service_windows').fetchone()['n']==1
        assert conn.execute("SELECT count(*) n FROM documents WHERE title='quota'").fetchone()['n']==0
