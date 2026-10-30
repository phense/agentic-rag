"""A new login can explicitly authorize its own blocked receipt; never silently."""
from dataclasses import replace
import uuid
from starlette.testclient import TestClient
from agentic_rag import db
from .test_worker_fencing import owned,window
from .test_api import app_fixture,headers,KEYS


def test_logout_relogin_requires_explicit_owned_job_retry(owned,tmp_path):
    cfg,_=owned;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        uploader=str(uuid.uuid4())
        def login():
            return client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'alice','password':'correct horse synthetic password','uploader_id':uploader}).json()['access_token']
        old=login();receipt=client.post('/v1/windows',headers=headers(old),json=window()).json()['receipt']
        with db.connect(cfg) as conn:
            original=conn.execute('SELECT payload FROM service_windows WHERE id=%s',(receipt,)).fetchone()['payload']['_principal']
            conn.execute("UPDATE service_windows SET state='blocked' WHERE id=%s",(receipt,))
        assert client.post('/v1/logout',headers=headers(old),json={}).status_code==200
        new=login()
        assert client.post('/v1/jobs/'+receipt+'/retry',headers=headers(old),json={}).status_code==401
        # Machine and human namespaces never share a receipt even for one user.
        assert client.post('/v1/jobs/'+receipt+'/retry',headers=headers(KEYS[0]),json={}).status_code==404
        result=client.post('/v1/jobs/'+receipt+'/retry',headers=headers(new),json={})
        assert result.status_code==200,result.text
        assert result.json()['state']=='queued'
        with db.connect(cfg) as conn:
            payload=conn.execute('SELECT payload FROM service_windows WHERE id=%s',(receipt,)).fetchone()['payload']
            assert payload['_original_principal']==original
            assert payload['_principal']['session']!=original['session']
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='source_window_reauthorize'").fetchone()['n']==1
        assert client.post('/v1/jobs/'+receipt+'/retry',headers=headers(new),json={}).status_code==409
        assert client.post('/v1/jobs/'+receipt+'/cancel',headers=headers(new),json={}).status_code==200
        assert client.post('/v1/jobs/'+receipt+'/retry',headers=headers(new),json={}).status_code==409
