"""Settings use real cookie authority, durable file/audit and old-client search."""
from dataclasses import replace
import json
import uuid

import httpx
import pytest
from starlette.testclient import TestClient

from agentic_rag import db,neural_rerank
from .test_scope import service_store
from .test_api import app_fixture,headers,KEYS
from .test_dashboard import login,ORIGIN

REAL_ASYNC_CLIENT=httpx.AsyncClient


def runtime(monkeypatch, *, available=True, wrong_revision=False):
    from agentic_rag.reranker_profiles import catalogue
    calls=[];real=REAL_ASYNC_CLIENT
    def handle(req):
        calls.append(req)
        if req.method=='GET':
            return httpx.Response(200,json={'data':[{'id':p['alias'],'revision':'0'*64 if wrong_revision else p['files']['model.onnx']['sha256']} for p in catalogue()] if available else []})
        body=json.loads(req.content)
        return httpx.Response(200,json={'model':body['model'],'results':[{'index':i,'relevance_score':.9 if i==0 else .1} for i in range(len(body['documents']))]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    return calls


def payload(client,profile='minilm-l6',revision=None):
    return {'revision':revision or client.get('/dashboard/api/settings').json()['revision'],'profile':profile,'operation_id':str(uuid.uuid4())}


def test_admin_selection_preview_apply_restart_and_canonical_preservation(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg);calls=runtime(monkeypatch)
    from agentic_rag.service.api import create_app
    before=path.read_bytes()
    with db.connect(cfg) as conn:
        canonical=conn.execute('SELECT row_to_json(d)::text value FROM documents d ORDER BY id').fetchall()
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);state=client.get('/dashboard/api/settings')
        assert state.status_code==200,state.text
        assert state.json()['selected']=='mmarco'
        assert [r['id'] for r in state.json()['options']]==['minilm-l6','mmarco','jina-tiny']
        assert state.json()['options'][2]['languages']==['en']
        data=payload(client)
        preview=client.post('/dashboard/api/settings/preview',headers=csrf,json=data)
        assert preview.status_code==200,preview.text
        assert path.read_bytes()==before
        saved=client.post('/dashboard/api/settings/apply',headers=csrf,json=data)
        assert saved.status_code==200,saved.text
        assert client.get('/dashboard/api/settings').json()['selected']=='minilm-l6'
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json=data).status_code==409
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT row_to_json(d)::text value FROM documents d ORDER BY id').fetchall()==canonical
            audit=conn.execute('SELECT kind,subject,state FROM dashboard_changes WHERE operation_id=%s',(data['operation_id'],)).fetchone()
            assert audit=={'kind':'reranker','subject':'minilm-l6','state':'applied'}
    with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as client:
        login(client)
        assert client.get('/dashboard/api/settings').json()['selected']=='minilm-l6'
        selected=__import__('agentic_rag.reranker_profiles',fromlist=['effective']).effective(replace(cfg,service_auth_file=path))
        assert selected.rerank_model=='agentic-rag-minilm-l6-en-de-int8'


def test_member_csrf_stale_unknown_unavailable_and_identity_rejected(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg);runtime(monkeypatch)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client,'alice','correct horse synthetic password')
        assert client.get('/dashboard/api/settings').status_code==403
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json={'profile':'mmarco'}).status_code==403
        client.post('/dashboard/api/logout',headers=csrf,json={})
        csrf=login(client);data=payload(client);before=path.read_bytes()
        assert client.post('/dashboard/api/settings/apply',headers=ORIGIN,json=data).status_code==403
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json={**data,'profile':'evil'}).status_code==400
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json={**data,'revision':'0'*64}).status_code==409
        runtime(monkeypatch,available=False)
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json=data).status_code==409
        assert path.read_bytes()==before


def test_changed_model_hash_sends_no_passages(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg);calls=runtime(monkeypatch,wrong_revision=True)
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=path.read_bytes();data=payload(client)
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json=data).status_code==409
        assert path.read_bytes()==before and all(r.method=='GET' for r in calls)


def test_crash_after_replace_recovers_and_old_settings_do_not_erase_users(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg);runtime(monkeypatch)
    from agentic_rag.service import dashboard_policy as policies
    from agentic_rag.service.auth import Policy
    original=policies._replace
    def crash(path,data):original(path,data);raise RuntimeError('synthetic process failure after replace')
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);before=Policy.load(path);data=payload(client,'jina-tiny')
        with monkeypatch.context() as scoped:
            scoped.setattr(policies,'_replace',crash)
            assert client.post('/dashboard/api/settings/apply',headers=csrf,json=data).status_code==503
        assert client.get('/dashboard/api/settings').json()['selected']=='jina-tiny'
        assert Policy.load(path).users==before.users and Policy.load(path).machines==before.machines
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json=payload(client,'mmarco')).status_code==200
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(data['operation_id'],)).fetchone()['state']=='applied'


def test_session_revocation_after_runtime_probe_cannot_commit(service_store,tmp_path,monkeypatch):
    cfg,_=service_store;app,path=app_fixture(tmp_path,cfg);runtime(monkeypatch)
    from agentic_rag.service import dashboard_settings as setting
    from agentic_rag.service.dashboard_policy import change_policy
    old=setting.probe
    def revoke(*args):
        old(*args)
        with db.connect(cfg) as conn:conn.execute("DELETE FROM service_sessions WHERE user_id='admin'")
    with TestClient(app,base_url='https://testserver') as client:
        csrf=login(client);data=payload(client);before=path.read_bytes()
        monkeypatch.setattr(setting,'probe',revoke)
        assert client.post('/dashboard/api/settings/apply',headers=csrf,json=data).status_code==401
        assert path.read_bytes()==before


def test_settings_to_rest_mcp_search_snapshot_and_restart(service_store,tmp_path,monkeypatch):
    """IT062-SUCCESS: switch during scoring; first search keeps A, next uses B."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from agentic_rag import store,search
    from agentic_rag.service.api import create_app
    from agentic_rag.reranker_profiles import catalogue
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a,**k:None)
    cfg,_=service_store
    query='newsletter authentication failure'
    with db.connect(cfg) as conn:
        ids=[]
        for i in range(4):
            ids.append(store.save_document(conn,cfg,title=query+' '+str(i),body=query+' original '+str(i),
                domain='alpha',dtype='memory',project='/projects/a').doc_id)
        foreign=store.save_document(conn,cfg,title=query+' FOREIGN',body=query+' FOREIGN',domain='beta',dtype='memory',project='/projects/b').doc_id
    cfg=replace(cfg,rerank_diagnostics=True)
    app,path=app_fixture(tmp_path,cfg)
    real=httpx.AsyncClient;entered=threading.Event();release=threading.Event();calls=[]
    def handle(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':r['alias'],'revision':r['files']['model.onnx']['sha256']} for r in catalogue()]})
        body=json.loads(req.content);calls.append(body)
        assert all('FOREIGN' not in d for d in body['documents'])
        if body['query']==query and body['model']=='agentic-rag-mmarco-int8':
            entered.set();assert release.wait(2)
        return httpx.Response(200,json={'model':body['model'],'results':[{'index':i,'relevance_score':.9 if i==(len(body['documents'])-1 if body['query']==query else 0) else .1} for i in range(len(body['documents']))]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handle),**kw))
    arguments={'query':query,'domain':'alpha','project':'/projects/a','context':'off','k':5}
    with TestClient(app,base_url='https://testserver') as client,ThreadPoolExecutor(max_workers=1) as pool:
        csrf=login(client)
        before=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={**arguments,'rerank':'off'}).json()
        pending=pool.submit(client.post,'/v1/tools/memory_search',headers=headers(KEYS[0]),json=arguments)
        try:
            assert entered.wait(1)
            applied=client.post('/dashboard/api/settings/apply',headers=csrf,json=payload(client,'minilm-l6'))
            assert applied.status_code==200,applied.text
        finally:release.set()
        first=pending.result(timeout=5);assert first.status_code==200,first.text
        assert any('model=agentic-rag-mmarco-int8' in w and 'outcome=ranked' in w for w in first.json()['warnings'])
        rest=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json=arguments)
        assert rest.status_code==200 and any('model=agentic-rag-minilm-l6-en-de-int8' in w and 'outcome=ranked' in w for w in rest.json()['warnings'])
        assert sorted(first.json()['results'],key=lambda h:h['chunk_id'])==sorted(before['results'],key=lambda h:h['chunk_id'])
        assert sorted(rest.json()['results'],key=lambda h:h['chunk_id'])==sorted(before['results'],key=lambda h:h['chunk_id'])
        assert foreign not in first.text and foreign not in rest.text
    restarted=create_app(cfg,path,allowed_hosts=['testserver'])
    with TestClient(restarted,base_url='https://testserver') as client:
        response=client.post('/mcp/ro/',headers={**headers(KEYS[0]),'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'memory_search','arguments':arguments}})
        assert response.status_code==200,response.text
        assert not response.json().get('error') and not response.json()['result'].get('isError'),response.text
        assert 'outcome=ranked' in response.text and 'agentic-rag-minilm-l6-en-de-int8' in response.text
    searches=[c for c in calls if c['query']==query]
    assert [c['model'] for c in searches]==['agentic-rag-mmarco-int8','agentic-rag-minilm-l6-en-de-int8','agentic-rag-minilm-l6-en-de-int8']
