"""Final review regressions: current cancel authority and human uploader profiles."""
import pytest
from starlette.testclient import TestClient
from agentic_rag import db
from .test_worker_fencing import owned, window
from .test_api import app_fixture, headers, KEYS
from .test_checkpoint_api import packet
from agentic_rag.service.auth import AuthenticationError,Policy,hash_key,resolve_reference
from agentic_rag.service.api import authenticate
from agentic_rag.service.ingest import credential_reference
from dataclasses import replace


@pytest.mark.parametrize('revocation',['target_project','all_writes'])
def test_cancel_requires_current_target_write_authority(owned,tmp_path,revocation):
    cfg,_=owned
    app,policy=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver',raise_server_exceptions=False) as client:
        first=client.post('/v1/windows',headers=headers(KEYS[0]),json=window())
        assert first.status_code==202,first.text
        receipt=first.json()['receipt']
        text=policy.read_text()
        if revocation=='all_writes':
            text=text.replace('write_domains = ["alpha"]','write_domains = []')
        else:
            text=text.replace('read_projects = ["global", "/projects/a"]','read_projects = ["global", "/projects/a", "/projects/other"]')
            text=text.replace('read_projects = ["/projects/a"]','read_projects = ["/projects/a", "/projects/other"]')
            text=text.replace('write_projects = ["/projects/a"]','write_projects = ["/projects/other"]')
        policy.write_text(text)
        response=client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(KEYS[0]))
        with db.connect(cfg) as conn:
            actual=dict(conn.execute('SELECT w.state,q.status,q.payload FROM service_windows w JOIN mining_queue q ON q.id=w.queue_id WHERE w.id=%s',(receipt,)).fetchone())
        print('CANCEL_AUTHORITY',revocation,response.status_code,response.text,actual)
        assert response.status_code in {403,404},'Cancellation must explicitly deny missing current target write authority'
        assert actual['state']=='queued' and actual['status']=='pending' and not actual['payload'].get('cancelled')


def test_documented_human_uploader_profiles_preserve_cross_vm_cursor_isolation(owned,tmp_path):
    cfg,_=owned
    app,policy=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        profiles=[];uploaders=[]
        for _ in range(2):
            login=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'alice','password':'correct horse synthetic password'})
            assert login.status_code==200
            profiles.append(login.json()['access_token'])
            uploaders.append(login.json()['uploader_id'])
        assert profiles[0]!=profiles[1]
        assert uploaders[0]!=uploaders[1]
        first=client.post('/v1/windows',headers=headers(profiles[0]),json=window())
        assert first.status_code==202
        other=window();other['window']['text']='[user] Second VM task';other['window']['events'][0]['text']=other['window']['text']
        second=client.post('/v1/windows',headers=headers(profiles[1]),json=other)
        checkpoint=packet();checkpoint['session_id']='probe';checkpoint['handoff']='First VM continuation'
        a=client.post('/v1/checkpoints',headers=headers(profiles[0]),json=checkpoint)
        assert a.status_code==200
        checkpoint['handoff']='Second VM continuation'
        b=client.post('/v1/checkpoints',headers=headers(profiles[1]),json=checkpoint)
        assert b.status_code==200
        current=client.get('/v1/checkpoints/probe',headers=headers(profiles[0])).json()['checkpoint']
        print('HUMAN_UPLOADER_COLLISION',{'second_window_status':second.status_code,'second_window':second.json(),'checkpoint_id_collides':a.json()['checkpoint']['id']==b.json()['checkpoint']['id'],'first_profile_handoff':current['handoff']})
        assert second.status_code==202,'FR-003A/AC-003: same raw session ID on separate VM profiles must not share a cursor'
        assert a.json()['checkpoint']['id']!=b.json()['checkpoint']['id']
        assert current['handoff']=='First VM continuation'
        # Token renewal reuses the stable uploader profile, never its expired
        # bearer authority. This retains exact replay and owned explicit retry.
        assert client.post('/v1/logout',headers=headers(profiles[0])).status_code==200
        renewed=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={
            'username':'alice','password':'correct horse synthetic password','uploader_id':uploaders[0]})
        assert renewed.status_code==200 and renewed.json()['access_token']!=profiles[0]
        replay=client.post('/v1/windows',headers=headers(renewed.json()['access_token']),json=window())
        assert replay.status_code==202 and replay.json()['receipt']==first.json()['receipt']
        assert client.get('/v1/checkpoints/probe',headers=headers(renewed.json()['access_token'])).json()['checkpoint']['handoff']=='First VM continuation'


def test_cancel_confirms_window_transition_before_changing_queue(owned,tmp_path):
    cfg,_=owned;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        receipt=client.post('/v1/windows',headers=headers(KEYS[0]),json=window()).json()['receipt']
        with db.connect(cfg) as conn:
            conn.execute('CREATE POLICY service_probe_cancel_guard ON service_windows AS RESTRICTIVE FOR UPDATE USING(false)')
        denied=client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(KEYS[0]))
        assert denied.status_code==403,denied.text
        with db.connect(cfg) as conn:
            row=conn.execute('SELECT w.state,q.status FROM service_windows w JOIN mining_queue q ON w.queue_id=q.id WHERE w.id=%s',(receipt,)).fetchone()
            assert row=={'state':'queued','status':'pending'}
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='source_window_cancel'").fetchone()['n']==0


def test_unbound_legacy_human_session_cannot_reuse_shared_namespace(owned,tmp_path):
    cfg,_=owned;app,path=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=path)
    with TestClient(app,base_url='https://testserver') as client:
        login=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={
            'username':'alice','password':'correct horse synthetic password'})
        token=login.json()['access_token'];principal=authenticate(Policy.load(path),cfg,token)
        reference=credential_reference(principal,None)
        assert resolve_reference(cfg,reference)==principal
        tampered={**reference,'uploader':'00000000-0000-0000-0000-000000000000'}
        with pytest.raises(AuthenticationError):resolve_reference(cfg,tampered)
        with db.connect(cfg) as conn:
            conn.execute('UPDATE service_sessions SET uploader_id=NULL WHERE token_hash=%s',(hash_key(token),))
        assert client.get('/v1/capabilities',headers=headers(token)).status_code==401
        with pytest.raises(AuthenticationError):resolve_reference(cfg,reference)
