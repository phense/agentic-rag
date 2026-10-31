"""Populated local/HTTP/old-binary readers retain eligible original knowledge."""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import subprocess
import tarfile

import httpx
from starlette.testclient import TestClient

from agentic_rag import db,search,store
from agentic_rag.benchmark.rerank_evaluation import BASE,_snapshot
from agentic_rag.config import Config
from agentic_rag.domains import seed_defaults,add_domain
from agentic_rag.evidence import sources
from .test_api import app_fixture,headers,KEYS


def test_populated_focused_local_http_withdrawal_and_real_code_config_rollback(conn,cfg,tmp_path,monkeypatch):
    seed_defaults(conn);conn.commit()
    add_domain(conn,'alpha','Synthetic allowed domain',actor='test')
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    query='newsletter authentication failure'
    allowed=[];slugs=[]
    for i in range(5):
        text=query+' original dated receipt '+str(i)+(' EXPECTED' if i==4 else '')
        saved=store.save_claim(conn,cfg,title=query+' '+str(i),body=text,
            dtype='memory',domain='alpha',project='/projects/a',claim_kind='stated',
            evidence=[dict(namespace='synthetic',source_id='focused-'+str(i),role='user',quote=text,complete=True)])
        allowed.append(saved.doc_id)
        slugs.append(saved.slug)
    foreign=store.save_document(conn,cfg,title='FOREIGN '+query,body='FOREIGN '+query,
        slug='focused-foreign',dtype='memory',domain='alpha',project='/projects/b')
    calls=[];real=httpx.AsyncClient
    def handler(request):
        calls.append(request)
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'local-alternative'}]})
        body=json.loads(request.content)
        assert all('FOREIGN' not in value for value in body['documents'])
        return httpx.Response(200,json={'model':'local-alternative','results':[
            {'index':i,'relevance_score':.9 if 'EXPECTED' in value else .1,'document':{'text':'FORGED'}}
            for i,value in enumerate(body['documents'])]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    focused=replace(cfg,rerank_policy='focused-v1',rerank_model='local-alternative',rerank_revision='a'*64,
        rerank_diagnostics=True,ollama_url='http://127.0.0.1:1',service_storage_path=tmp_path)
    before=_snapshot(conn);conn.rollback()
    local,warnings=search.search(conn,focused,query,domain='alpha',project='/projects/a',context_mode='off',k=5)
    assert local[0].document_id==allowed[4] and {h.document_id for h in local}==set(allowed)
    assert any('route=focused-v1' in w and 'outcome=ranked' in w for w in warnings)
    assert all('FOREIGN' not in w and query not in w for w in warnings)
    conn.rollback()
    app,policy=app_fixture(tmp_path,focused)
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={
            'query':query,'domain':'alpha','project':'/projects/a','k':5,'context':'off'})
        assert response.status_code==200,response.text
        result=response.json()
        assert result['results'][0]['document_id']==allowed[4]
        serialized=json.loads(json.dumps([asdict(h) for h in local],default=str))
        assert sorted(result['results'],key=lambda h:h['chunk_id'])==sorted(serialized,key=lambda h:h['chunk_id'])
        assert foreign.doc_id not in response.text and 'FORGED' not in response.text
    after=_snapshot(conn);conn.rollback()
    # Authorized reads create bounded tracing/admission records, not knowledge edits.
    for name,digest in before.items():
        if name not in ('request_traces','service_requests','service_foreground','dashboard_presence'):
            assert after[name]==digest,name
    count=len(calls)
    exact,_=search.search(conn,focused,slugs[4],domain='alpha',project='/projects/a')
    assert [h.document_id for h in exact]==[allowed[4]] and len(calls)==count
    conn.rollback()
    # Withdraw current support; neither local nor HTTP inference may see it again.
    key=sources(conn,allowed[4])[0]['source_key']
    store.set_source_state(conn,key,state='refuted',reason='Synthetic withdrawal')
    calls.clear()
    withdrawn,_=search.search(conn,focused,query,domain='alpha',project='/projects/a',context_mode='off')
    assert allowed[4] not in {h.document_id for h in withdrawn}
    assert all('EXPECTED' not in text for req in calls if req.method=='POST'
        for text in json.loads(req.content)['documents'])
    conn.rollback()
    from agentic_rag.service.api import create_app
    restarted=create_app(focused,policy,allowed_hosts=['testserver'])
    with TestClient(restarted,base_url='https://testserver') as client:
        withdrawn_http=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={
            'query':query,'domain':'alpha','project':'/projects/a','context':'off'})
        assert withdrawn_http.status_code==200 and allowed[4] not in withdrawn_http.text
    # Run the actual complete0.6.14 engine in a fresh interpreter, not a stub callback.
    archive=tmp_path/'before.tar';old=tmp_path/'before';old.mkdir()
    with archive.open('wb') as out:
        subprocess.run(['git','archive',BASE,'agentic_rag','sql','pyproject.toml'],stdout=out,check=True)
    with tarfile.open(archive) as content:content.extractall(old,filter='data')
    config=tmp_path/'rollback.toml'
    config.write_text('[db]\nname="'+cfg.db_name+'"\n[ollama]\nurl="http://127.0.0.1:1"\n[rerank]\nurl="http://127.0.0.1:1"\n')
    env={**os.environ,'PYTHONPATH':str(old),'AGENTIC_RAG_CONFIG':str(config),
        'RAG_TEST_POLICY':str(policy),'RAG_TEST_STORAGE':str(tmp_path/'rollback-service')}
    import sys
    code='''
import json
from dataclasses import asdict,replace
from pathlib import Path
import os
from starlette.testclient import TestClient
from agentic_rag.service.api import create_app
from agentic_rag import db,search
from agentic_rag.config import load_config
assert str(Path(search.__file__).resolve()).startswith(str(Path.cwd()))
cfg=load_config()
with db.connect(cfg,role='reader') as conn:
 hits,warnings=search.search(conn,cfg,"newsletter authentication failure",domain="alpha",project="/projects/a",context_mode="off",rerank_mode="off",k=5)
 local=[asdict(h) for h in hits]
server=replace(cfg,service_storage_path=Path(os.environ['RAG_TEST_STORAGE']))
app=create_app(server,Path(os.environ['RAG_TEST_POLICY']),allowed_hosts=['testserver'])
with TestClient(app,base_url='https://testserver') as client:
 response=client.post('/v1/tools/memory_search',headers={'authorization':'Bearer one.synthetic-long-random-machine-secret','x-rag-protocol':'1'},json={'query':'newsletter authentication failure','domain':'alpha','project':'/projects/a','context':'off','rerank':'off','k':5})
 assert response.status_code==200,response.text
 print(json.dumps({'local':local,'http':response.json()['results']},default=str))
'''
    rollback_before=_snapshot(conn);conn.rollback()
    prior=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=old,env=env,text=True,timeout=15))
    restored,_=search.search(conn,replace(cfg,ollama_url='http://127.0.0.1:1'),query,
        domain='alpha',project='/projects/a',context_mode='off',rerank_mode='off',k=5)
    current=json.loads(json.dumps([asdict(h) for h in restored],default=str));conn.rollback()
    assert prior['local']==current and prior['http']==current
    after_rollback=_snapshot(conn);conn.rollback()
    for name,digest in rollback_before.items():
        if name not in ('request_traces','service_requests','service_foreground','dashboard_presence'):
            assert after_rollback[name]==digest,name
