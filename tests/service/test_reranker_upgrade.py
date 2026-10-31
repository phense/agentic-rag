"""Actual0.6.14/schema027 ->028, verified restore, selection and old-binary rollback."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
from starlette.testclient import TestClient

from agentic_rag import db,store
from agentic_rag.benchmark.rerank_evaluation import BASE,_snapshot
from agentic_rag.service import upgrade
from test_maintenance_restore import owned_source
from .test_api import headers,KEYS
from .test_auth import policy_file
from .test_dashboard import login
from .test_reranker_settings import runtime,payload


def test_populated027_upgrade_restore_retry_settings_and_real014_rollback(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest',lambda cfg:'a'*64)
    with owned_source(tmp_path,27) as cfg:
        path=policy_file(tmp_path)
        import tomlkit
        authority=tomlkit.parse(path.read_text())
        for row in [authority['users']['alice'],authority['machines']['vm1']]:
            row['read_domains']=['general'];row['write_domains']=['general']
            row['read_projects']=['/synthetic/backup'];row['write_projects']=['/synthetic/backup']
        path.write_text(tomlkit.dumps(authority))
        with db.connect(cfg) as conn:
            for i in range(3):
                store.save_document(conn,cfg,title='Synthetic model selection '+str(i),
                    body='Synthetic model selection original evidence '+str(i),
                    domain='general',dtype='memory',project='/synthetic/backup')
            store.save_document(conn,cfg,title='Synthetic model selection foreign',
                body='Synthetic model selection foreign evidence',domain='programming',
                dtype='memory',project='/synthetic/backup')
        old=tmp_path/'before';old.mkdir();archive=tmp_path/'before.tar'
        with archive.open('wb') as out:subprocess.run(['git','archive',BASE,'agentic_rag','sql','pyproject.toml'],stdout=out,check=True)
        with tarfile.open(archive) as content:content.extractall(old,filter='data')
        config=tmp_path/'rollback.toml'
        from agentic_rag.benchmark.rerank_evaluation import BASELINE_MODEL,BASELINE_REVISION
        config.write_text('[db]\nname="'+cfg.db_name+'"\n[ollama]\nurl="http://127.0.0.1:1"\n[rerank]\nurl="http://127.0.0.1:1"\nmodel="'+BASELINE_MODEL+'"\nrevision="'+BASELINE_REVISION+'"\npolicy="legacy-v1"\n')
        env={**os.environ,'PYTHONPATH':str(old),'AGENTIC_RAG_CONFIG':str(config),'RAG_TEST_POLICY':str(path)}
        code='''
from pathlib import Path
import os,json
from agentic_rag.config import load_config
from agentic_rag.service.api import create_app
from agentic_rag import db,search
from starlette.testclient import TestClient
cfg=load_config()
assert Path(search.__file__).resolve().is_relative_to(Path.cwd())
with db.connect(cfg,role='reader') as conn:
 hits,_=search.search(conn,cfg,'Synthetic model selection',domain='general',project='/synthetic/backup',context_mode='off',rerank_mode='off')
 local=[h.document_id for h in hits]
app=create_app(cfg,Path(os.environ['RAG_TEST_POLICY']),allowed_hosts=['testserver'])
with TestClient(app,base_url='https://testserver') as client:
 headers={'authorization':'Bearer one.synthetic-long-random-machine-secret','x-rag-protocol':'1'}
 arguments={'query':'Synthetic model selection','domain':'general','project':'/synthetic/backup','rerank':'off','context':'off'}
 response=client.post('/v1/tools/memory_search',headers=headers,json=arguments);assert response.status_code==200,response.text
 assert len(response.json()['results'])==3,response.text
 rpc=client.post('/mcp/ro/',headers={**headers,'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'memory_search','arguments':arguments}})
 assert rpc.status_code==200,rpc.text
 assert not rpc.json().get('error') and not rpc.json()['result'].get('isError'),rpc.text
 print(json.dumps({'local':local,'http':response.json(),'mcp':rpc.json()['result']}))
'''
        previous=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=old,env=env,text=True,timeout=20))
        original_policy=path.read_bytes()
        before=upgrade.inventory(cfg,'0.6.14',identities=True)
        assert len(before['migrations'])==27
        result=upgrade.local_upgrade(cfg,'0.6.14',tmp_path/'upgrade028.dump',apply=True,writers_stopped=True)
        assert result['migrations_applied']==['028_reranker_settings.sql']
        assert result['restore_verified'] and result['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg,before)['unchanged']
        assert path.read_bytes()==original_policy
        retry=upgrade.local_upgrade(cfg,'0.6.14',tmp_path/'retry028.dump',apply=True,writers_stopped=True)
        assert retry['migrations_applied']==[] and retry['restore_verified']
        from agentic_rag.service.api import create_app
        calls=runtime(monkeypatch)
        with db.connect(cfg) as conn:canonical=_snapshot(conn)
        with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as client:
            csrf=login(client)
            from agentic_rag.service import dashboard_policy as policies
            original_replace=policies._replace
            interrupted=payload(client,'jina-tiny')
            def crash(target,data):
                original_replace(target,data)
                raise RuntimeError('synthetic interrupted setting')
            with monkeypatch.context() as scoped:
                scoped.setattr(policies,'_replace',crash)
                assert client.post('/dashboard/api/settings/apply',headers=csrf,json=interrupted).status_code==503
        # Recreate the process boundary before reconciliation and fallback search.
        with TestClient(create_app(cfg,path,allowed_hosts=['testserver']),base_url='https://testserver') as client:
            csrf=login(client)
            for profile in ['minilm-l6','jina-tiny','mmarco']:
                saved=client.post('/dashboard/api/settings/apply',headers=csrf,json=payload(client,profile))
                assert saved.status_code==200,saved.text
                assert client.get('/dashboard/api/settings').json()['selected']==profile
            current=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={'query':'Synthetic model selection','domain':'general','project':'/synthetic/backup','rerank':'off','context':'off'})
            assert current.status_code==200 and current.json()==previous['http']
            with monkeypatch.context() as scoped:
                wrong_calls=runtime(scoped,wrong_revision=True)
                fallback=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={'query':'Synthetic model selection','domain':'general','project':'/synthetic/backup','context':'off'})
                assert fallback.status_code==200 and fallback.json()['results']==previous['http']['results']
                assert wrong_calls and all(call.method=='GET' for call in wrong_calls)
            with db.connect(cfg) as conn:
                rows=conn.execute('SELECT state FROM dashboard_changes WHERE operation_id=%s',(interrupted['operation_id'],)).fetchall()
                assert rows==[{'state':'applied'}]
        after_rollback=json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=old,env=env,text=True,timeout=20))
        assert after_rollback==previous
        with db.connect(cfg) as conn:
            after=_snapshot(conn)
            assert conn.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']==28
        operational={'service_sessions','dashboard_changes','dashboard_presence','request_traces','service_foreground','service_requests'}
        unchanged={k:v for k,v in canonical.items() if k not in operational}
        assert all(after[k]==v for k,v in unchanged.items())
        report={'source_version':'0.6.14','source_commit':BASE,'source_schema':27,'target_version':'0.6.15','target_schema':28,
                'applied':result['migrations_applied'],'restore_verified':True,'retry_migrations':[],
                'old_binary_local_rest_mcp_before_and_after_equal':True,'three_settings_applied':True,'interrupted_setting_reconciled_after_restart':True,'wrong_sha_fallback_without_passage_post':True,
                'preserved_tables':unchanged,'old_audit_rows_preserved':True,'private_or_production_data':False}
        if destination:=os.environ.get('RAG_SETTINGS_EVIDENCE_DIR'):
            out=Path(destination);out.mkdir(parents=True,exist_ok=True)
            (out/'upgrade-summary.json').write_text(json.dumps(report,indent=2,default=str)+'\n')


def test_027_interruption_rolls_back_constraint_and_marker_then_retries(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr('agentic_rag.query_cache.model_digest',lambda cfg:'a'*64)
    with owned_source(tmp_path,27) as cfg:
        before=upgrade.inventory(cfg,'0.6.14')
        real=db.apply_migrations
        def interrupt(*args,**kwargs):real(*args,**kwargs);raise RuntimeError('synthetic before commit')
        with monkeypatch.context() as scoped:
            scoped.setattr(db,'apply_migrations',interrupt)
            with pytest.raises(RuntimeError,match='synthetic before commit'):
                upgrade.local_upgrade(cfg,'0.6.14',tmp_path/'interrupted028.dump',apply=True,writers_stopped=True)
        assert upgrade.inventory(cfg,'0.6.14')['tables']==before['tables']
        with db.connect(cfg) as conn:
            constraint=conn.execute("SELECT pg_get_constraintdef(oid) value FROM pg_constraint WHERE conrelid='dashboard_changes'::regclass AND conname='dashboard_changes_kind_check'").fetchone()['value']
            assert 'reranker' not in constraint
        result=upgrade.local_upgrade(cfg,'0.6.14',tmp_path/'retried028.dump',apply=True,writers_stopped=True)
        assert result['migrations_applied']==['028_reranker_settings.sql'] and result['restore_verified']
