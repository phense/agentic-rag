"""Reviewer-derived whole-feature success and crash/recovery integrations."""
from dataclasses import replace
from datetime import datetime,timezone
import json,subprocess,sys,time,uuid
import pytest
from starlette.testclient import TestClient
from agentic_rag import db,store
from agentic_rag.service.api import create_app
from agentic_rag.service.auth import Policy,hash_key
from agentic_rag.service import dashboard_policy as dp
from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS
from .test_dashboard import login,ORIGIN
from .test_dashboard_policy import apply


def queued(client,csrf,tool,args):
    response=client.post('/dashboard/api/tools',headers=csrf,json={'tool':tool,'arguments':args,'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat()})
    assert response.status_code==200,response.text
    identity=response.json()['request_id']
    for _ in range(100):
        row=client.get('/dashboard/api/requests/'+identity)
        assert row.status_code==200,row.text
        data=row.json()
        if data['state'] not in {'pending','running'}:
            assert data['state']=='completed',data
            return data['result']
        time.sleep(.05)
    pytest.fail('synthetic queue did not finish')


def test_success_bootstrap_enrollment_scoped_sources_and_ro(service_store,tmp_path):
    cfg,docs=service_store
    # Seed source-backed synthetic knowledge through the existing audited gateway.
    with db.connect(cfg) as conn:
        source=store.save_claim(conn,cfg,title='Review synthetic source',body='Exact synthetic source claim',domain='alpha',dtype='memory',project='/projects/a',claim_kind='stated',evidence=[{'namespace':'synthetic-review','source_id':'original-1','role':'user','quote':'Exact synthetic source claim','complete':True}])
    path=tmp_path/'new-policy.toml';tokenfile=tmp_path/'bootstrap-token'
    dp.arm_bootstrap(path,tokenfile)
    cfg=replace(cfg,service_auth_file=path,service_mode='server')
    app=create_app(cfg,path,allowed_hosts=['testserver'])
    with TestClient(app,base_url='https://testserver') as admin:
        payload={'token':tokenfile.read_text().strip(),'username':'first','password':'synthetic first administrator'}
        assert admin.post('/dashboard/api/bootstrap',headers=ORIGIN,json=payload).status_code==200
        assert admin.post('/dashboard/api/bootstrap',headers=ORIGIN,json=payload).status_code==409
        csrf=login(admin,'first','synthetic first administrator')
        assert admin.get('/dashboard/api/memories').json()['total']==0
        rights={'read_domains':['alpha'],'read_projects':['/projects/a'],'write_domains':[],'write_projects':[]}
        assert apply(admin,csrf,{'kind':'user','id':'reader','password':'synthetic restricted reader','fields':rights}).status_code==200
        assert apply(admin,csrf,{'kind':'machine','id':'reader_vm','user':'reader','fields':rights}).status_code==200
        credential=apply(admin,csrf,{'kind':'rotate','id':'reader_vm','key_id':'reader_key'}).json()['secret_once']
        assert admin.get('/v1/capabilities',headers=headers(credential)).status_code==200
        assert credential not in admin.get('/dashboard/api/policy').text
        with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as reader:
            readercsrf=login(reader,'reader','synthetic restricted reader')
            listing=reader.get('/dashboard/api/memories').json()
            assert listing['total']==2 and 'foreign' not in json.dumps(listing)
            detail=queued(reader,readercsrf,'memory_get',{'id_or_slug':source.doc_id})
            assert detail['document']['claim_sources'][0]['quote']=='Exact synthetic source claim'
            foreign=queued(reader,readercsrf,'memory_get',{'id_or_slug':docs['foreign']})
            assert 'document' not in foreign and 'Synthetic protected evidence foreign' not in json.dumps(foreign)
            assert reader.get('/dashboard/api/admin').status_code==403
            denied=reader.post('/dashboard/api/tools',headers=readercsrf,json={'tool':'memory_review_claim','arguments':{'id_or_slug':source.doc_id,'state':'confirmed','reason':'Synthetic test'},'idempotency_key':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat()})
            assert denied.status_code==403
            assert reader.get('/v1/capabilities',headers={'x-rag-protocol':'1'}).status_code==401
        print('I1 bootstrap closed; admin total0; reader total2; actual source quote; foreign absent; RO review403; cookie v1=401')


def test_process_crash_after_file_replace_restart_and_revocation(service_store,tmp_path):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    cfg=replace(cfg,service_auth_file=path)
    with TestClient(app,base_url='https://testserver') as client:
        login(client);token=client.cookies.get('__Host-rag_dashboard')
    op=str(uuid.uuid4())
    child=r'''
import json,os,sys
from pathlib import Path
from agentic_rag.config import Config
from agentic_rag.service import dashboard_policy as dp
from agentic_rag.service.auth import Policy
from agentic_rag.service.api import authenticate
value=json.load(sys.stdin)
path=Path(value['path']);cfg=Config(db_name=value['db'],db_host='127.0.0.1',service_auth_file=path,ollama_url='http://127.0.0.1:1')
p=authenticate(Policy.load(path),cfg,value['token'])
real=dp._replace
def crash(path,data):
    real(path,data)
    os._exit(73)
dp._replace=crash
dp.change_policy(cfg,path,p,{'revision':dp.revision(path.read_bytes()),'change':{'kind':'rotate','id':'vm1','key_id':'one'},'operation_id':value['operation']},apply=True)
'''
    child_result=subprocess.run([sys.executable,'-c',child],input=json.dumps({'db':cfg.db_name,'path':str(path),'token':token,'operation':op}),text=True,capture_output=True,timeout=20)
    assert child_result.returncode==73,child_result.stderr
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(op,)).fetchone()['state']=='prepared'
    with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as restarted:
        csrf=login(restarted)
        assert restarted.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==401
        assert apply(restarted,csrf,{'kind':'machine','id':'vm2','fields':{'label':'post-process-crash'}}).status_code==200
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(op,)).fetchone()['state']=='applied'
        assert apply(restarted,csrf,{'kind':'rotate','id':'vm1','key_id':'one'},operation=op).status_code==409
        new=apply(restarted,csrf,{'kind':'rotate','id':'vm1','key_id':'one'}).json()['secret_once']
        assert restarted.get('/v1/capabilities',headers=headers(new)).status_code==200
        assert apply(restarted,csrf,{'kind':'revoke','id':'vm1','key_id':'one'}).status_code==200
        assert restarted.get('/v1/capabilities',headers=headers(new)).status_code==401
    print('I2 child exit73; prepared durable; restarted API; old key401; recovered applied; replay409; new rotation200; revoke401')


def test_prepared_old_revision_and_unknown_drift_fail_closed(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);old=path.read_bytes();op=str(uuid.uuid4());real=dp._replace
        def crash(*args):raise OSError('synthetic crash before replace')
        monkeypatch.setattr(dp,'_replace',crash)
        assert apply(client,csrf,{'kind':'machine','id':'vm2','fields':{'label':'not-applied'}},operation=op).status_code==503
        monkeypatch.setattr(dp,'_replace',real)
        path.write_bytes(old+b'\n# unknown external drift\n')
        failed=apply(client,csrf,{'kind':'machine','id':'vm2','fields':{'label':'must-fail'}})
        assert failed.status_code==503 and failed.json()['error']=='policy_recovery_required'
        path.write_bytes(old)
        assert apply(client,csrf,{'kind':'machine','id':'vm2','fields':{'label':'recovered-old'}}).status_code==200
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(op,)).fetchone()['state']=='not_applied'
    print('Recovery extra: unknown drift503; restored known old digest -> not_applied, next mutation200')
