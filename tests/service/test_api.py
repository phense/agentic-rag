"""HTTP contracts exercise the same engine, including adversarial identity input."""
from concurrent.futures import ThreadPoolExecutor
import json

from starlette.testclient import TestClient

from .test_scope import service_store
from .test_auth import policy_file


def app_fixture(tmp_path,cfg):
    from agentic_rag.service.api import create_app
    p=policy_file(tmp_path)
    from agentic_rag.service.auth import hash_key
    with p.open('a') as f:
        f.write(f'''\n[users.bob]
read_domains=["beta"]
write_domains=["beta"]
read_projects=["/projects/b"]
write_projects=["/projects/b"]
[machines.vm3]
user="bob"
read_domains=["beta"]
write_domains=["beta"]
read_projects=["/projects/b"]
write_projects=["/projects/b"]
keys={{three="{hash_key('three.synthetic-third-machine-secret')}"}}
[machines.vm4]
user="alice"
read_domains=["alpha"]
write_domains=[]
read_projects=["/projects/a"]
write_projects=[]
keys={{four="{hash_key('four.synthetic-fourth-machine-secret')}"}}
''')
    return create_app(cfg,p,allowed_hosts=['testserver']),p


def headers(token):
    return {'authorization':'Bearer '+token,'x-rag-protocol':'1'}


KEYS=['one.synthetic-long-random-machine-secret','two.synthetic-different-machine-secret','three.synthetic-third-machine-secret','four.synthetic-fourth-machine-secret']


def test_protocol_auth_four_clients_and_counts(service_store,tmp_path):
    cfg,docs=service_store
    app,p=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get('/health').json()=={'status':'ok'}
        assert client.get('/v1/capabilities').status_code==401
        assert client.get('/v1/capabilities',headers={'authorization':'Bearer '+KEYS[0],'x-rag-protocol':'2'}).status_code==426
        def domains(token):
            return client.post('/v1/tools/memory_domains',headers=headers(token),json={}).json()['domains']
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(domains,KEYS))
        assert results==[[{'name':'alpha','description':'','docs':1}],[{'name':'general','description':'Uncategorized knowledge','docs':0}],[{'name':'beta','description':'','docs':1}],[{'name':'alpha','description':'','docs':1}]]
        for token in (KEYS[0],KEYS[3]):
            assert client.post('/v1/tools/memory_get',headers=headers(token),json={'id_or_slug':docs['foreign']}).json().get('document') is None
        assert client.post('/v1/tools/memory_save',headers=headers(KEYS[3]),json={'domain':'alpha','title':'No','body':'Denied','project':'/projects/a'}).status_code==403
        spoof=client.post('/v1/tools/memory_get',headers=headers(KEYS[0]),json={'id_or_slug':'foreign','machine_id':'vm3'})
        assert spoof.status_code==400 and 'foreign' not in spoof.text
        p.write_text(p.read_text().replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
        assert client.get('/v1/capabilities',headers=headers(KEYS[0])).status_code==401


def test_human_login_admin_logout_and_password_rotation(service_store,tmp_path):
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        denied=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'admin','password':'bad'})
        assert denied.status_code==401 and denied.json()=={'error':'invalid_credentials'}
        login=client.post('/v1/login',headers={'x-rag-protocol':'1'},json={'username':'admin','password':'synthetic administrator password'})
        assert login.status_code==200
        token=login.json()['access_token']
        assert client.get('/v1/admin/status',headers=headers(KEYS[0])).status_code==403
        status=client.get('/v1/admin/status',headers=headers(token))
        assert status.status_code==200 and 'password' not in status.text and 'sha256$' not in status.text
        assert client.post('/v1/logout',headers=headers(token)).status_code==200
        assert client.get('/v1/capabilities',headers=headers(token)).status_code==401


def test_openapi_body_limit_and_plain_remote_refusal(service_store,tmp_path):
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        spec=client.get('/v1/openapi.json',headers=headers(KEYS[0])).json()
        assert spec['openapi'].startswith('3.') and '/v1/tools/memory_search' in spec['paths']
        assert client.post('/v1/tools/memory_get',headers=headers(KEYS[0]),content=b'x'*1048577).status_code==413
        assert client.get('http://testserver/v1/capabilities',headers=headers(KEYS[0])).status_code==400


def test_remote_mcp_ro_surface_and_request_identity(service_store,tmp_path):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        def rpc(token,path,method,params=None):
            return client.post(path,headers={**headers(token),'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':method,**({'params':params} if params is not None else {})})
        names={t['name'] for t in rpc(KEYS[3],'/mcp/ro/','tools/list').json()['result']['tools']}
        assert len(names)==10 and 'memory_save' not in names
        assert rpc(KEYS[3],'/mcp/rw/','tools/list').status_code==403
        first=rpc(KEYS[0],'/mcp/rw/','tools/call',{'name':'memory_domains','arguments':{}}).json()['result']
        second=rpc(KEYS[2],'/mcp/ro/','tools/call',{'name':'memory_domains','arguments':{}}).json()['result']
        first_data=json.loads(first['content'][0]['text'])
        second_data=json.loads(second['content'][0]['text'])
        assert first_data['domains']==[{'name':'alpha','description':'','docs':1}]
        assert second_data['domains']==[{'name':'beta','description':'','docs':1}]
        assert 'beta' not in json.dumps(first) and 'alpha' not in json.dumps(second)


def test_scoped_research_subprocess_and_audited_write(service_store,tmp_path):
    from agentic_rag import db
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        result=client.post('/v1/tools/memory_research',headers=headers(KEYS[0]),json={'question':'Synthetic protected evidence','strategy':'lexical','seconds':10.0,'min_sources':2}).json()
        assert 'termination' in result, result
        assert result['termination']!='worker_failure'
        assert 'foreign' not in json.dumps(result)
        saved=client.post('/v1/tools/memory_save',headers=headers(KEYS[0]),json={'title':'Owned new example','body':'New synthetic evidence','domain':'alpha','project':'/projects/a'})
        assert saved.status_code==200 and saved.json()['created']
        with db.connect(cfg) as conn:
            actor=conn.execute("SELECT actor FROM audit_log WHERE document_id=%s AND op='save_document'",(saved.json()['doc_id'],)).fetchone()['actor']
            assert actor=='service:machine:alice:vm1'
        denied=client.post('/v1/tools/memory_save',headers=headers(KEYS[0]),json={'title':'Forbidden','body':'No changes','domain':'beta','project':'/projects/b'})
        assert denied.status_code==403 and denied.json()=={'error':'scope_denied'}
