"""Durable source acceptance, not merely successful HTTP delivery."""
from copy import deepcopy

from starlette.testclient import TestClient

from agentic_rag import db
from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS


def envelope(*,session='same-session',before='',after='cursor-1',project='/projects/a'):
    text='[user] server port is now 9000'
    return {'version':1,'session_id':session,'input_cursor':before,'output_cursor':after,'project':project,
        'window':{'text':text,'events':[{'source_id':'event-1','role':'user','timestamp':'2026-10-29T10:00:00Z',
            'text':text,'offset':0,'complete':True}],'warnings':[],'synthetic':False,'has_more':False}}


def test_commit_before_ack_replay_and_cursor_conflict(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        data=envelope()
        first=client.post('/v1/windows',headers=headers(KEYS[0]),json=data)
        assert first.status_code==202,first.text
        receipt=first.json()['receipt']
        assert first.json()['durable'] is True
        # A second connection observes the durable source and job before ACK is useful.
        with db.connect(cfg) as conn:
            row=conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone()
            assert row['state']=='queued' and row['payload']['window']['events'][0]['source_id']=='event-1'
            assert conn.execute('SELECT kind,status FROM mining_queue WHERE id=%s',(row['queue_id'],)).fetchone()=={'kind':'source_window','status':'pending'}
        repeat=client.post('/v1/windows',headers=headers(KEYS[0]),json=data)
        assert repeat.status_code==202 and repeat.json()['receipt']==receipt
        changed=deepcopy(data);changed['window']['text']='[user] changed';changed['window']['events'][0]['text']='[user] changed'
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=changed).status_code==409
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=envelope(before='gap',after='cursor-2')).status_code==409
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=envelope(before='cursor-1',after='cursor-2')).status_code==202
        assert client.get('/v1/jobs/'+receipt,headers=headers(KEYS[2])).status_code==404
        assert client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(KEYS[2]),json={}).status_code==404
        assert client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(KEYS[0]),json={}).json()['state']=='cancelled'
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT payload FROM service_windows WHERE id=%s',(receipt,)).fetchone()['payload']['window']['text']==data['window']['text']


def test_window_boundaries_identity_and_evidence_are_validated(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.post('/v1/windows',headers=headers(KEYS[3]),json=envelope()).status_code==403
        assert client.post('/v1/windows',headers=headers(KEYS[0]),json=envelope(project='/projects/b')).status_code==403
        for mutate in (lambda x:x.update(machine_id='vm3'),lambda x:x['window'].update(text='Unmatched quote'),
                       lambda x:x['window']['events'][0].update(timestamp='yesterday'),
                       lambda x:x['window'].update(events=x['window']['events']*65)):
            data=envelope();mutate(data)
            assert client.post('/v1/windows',headers=headers(KEYS[0]),json=data).status_code==400
        first=client.post('/v1/windows',headers=headers(KEYS[0]),json=envelope(session='validation')).json()['receipt']
        second=client.post('/v1/windows',headers=headers(KEYS[2]),json=envelope(project='/projects/b')).json()['receipt']
        assert first != second
        status=client.get('/v1/jobs/'+first,headers=headers(KEYS[0]))
        assert status.status_code==200 and status.json()['state']=='queued'
        assert 'payload' not in status.json()


def test_invalid_evidence_and_boolean_version_are_rejected_before_persistence():
    from copy import deepcopy
    import pytest
    from agentic_rag.service.engine import ServiceError
    from agentic_rag.service.ingest import normalize
    cases=[]
    item=envelope();item['version']=True;cases.append(item)
    item=envelope();item['window']['events'][0]['offset']=1;cases.append(item)
    item=envelope();item['window']['events'][0]['source_id']='bad\x00id';cases.append(item)
    for item in cases:
        with pytest.raises(ServiceError,match='invalid_window'):normalize(item)
