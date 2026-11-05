"""Archived production027 -> actual028: interruption, preserved originals and restores."""
from collections import Counter
from dataclasses import replace
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid

from agentic_rag import db,feedback,query_cache
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade

SOURCE='289b8bcecb3ad02fa7c4d4d13a2a70efcb51d520'
ROOT=Path(__file__).resolve().parents[2]
SEED=r'''
from agentic_rag import store,query_cache,pins,jobs,domains
query_cache.model_digest=lambda cfg:'a'*64
def vectors(texts,cfg):return [[((i+len(text))%17)/32 for i in range(1024)] for text in texts]
store.try_embed_texts=vectors
db.init_db(cfg)
with db.connect(cfg) as conn:
 domains.add_domain(conn,'finance')
 documents=[]
 for domain,project,user in [('general','/projects/alpha','alice'),('finance','/projects/beta','bob')]:
  body='Original synthetic feedback upgrade evidence '+domain
  saved=store.save_claim(conn,cfg,title=body,body=body,domain=domain,project=project,dtype='memory',
    claim_kind='stated',evidence=[{'namespace':'upgrade71:'+user,'source_id':domain,'role':'user','quote':body,'complete':True}],actor=user)
  documents.append(saved.doc_id)
 plain=store.save_document(conn,cfg,title='Plain legacy expected',body='Original plain legacy expected body',
                           domain='general',project='/projects/alpha',dtype='memory',actor='alice')
 pins.add_pin(conn,body='Original preserved feedback pin',scope='global')
 jobs.enqueue_mine(conn,cfg,session_id='preserved-feedback-job',transcript_path='/synthetic/preserved.jsonl',project='/projects/alpha')
print(json.dumps({'documents':documents,'plain':plain.doc_id}))
'''
READ=r'''
from agentic_rag.search import search
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope
with db.connect(cfg,role='reader') as conn:
 local=sorted(h.document_id for h in search(conn,cfg,'Original synthetic feedback upgrade',strategy='lexical')[0])
out={'local':local,'scoped':{}}
for user,domain,project in [('alice','general','/projects/alpha'),('bob','finance','/projects/beta')]:
 p=Principal(user,'synthetic','old',frozenset({domain}),frozenset(),frozenset({project}),frozenset())
 with request_scope(p,cfg,read_only=True):
  with db.connect(cfg,role='reader') as conn:
   out['scoped'][user]=sorted(h.document_id for h in search(conn,cfg,'Original synthetic feedback upgrade',strategy='lexical')[0])
print(json.dumps(out))
'''


def run_code(source,cfg,code,*,expected=0):
    prefix="import os,json\nfrom agentic_rag import db\nfrom agentic_rag.config import Config\nassert db.__file__.startswith(os.getcwd())\ncfg=Config(db_name=os.environ['FEEDBACK_DB'],db_host='127.0.0.1',ollama_url='http://127.0.0.1:1')\n"
    result=subprocess.run([sys.executable,'-c',prefix+code],cwd=source,env={**os.environ,'PYTHONPATH':str(source),
        'FEEDBACK_DB':cfg.db_name,'AGENTIC_RAG_HOOKS_DISABLE':'1'},capture_output=True,text=True,timeout=120)
    assert result.returncode==expected,result.stderr[-2000:]
    return json.loads(result.stdout.splitlines()[-1]) if result.stdout.strip() else None


def rows(cfg):
    with db.connect(cfg) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename") if r['tablename']!='benchmark_ownership']
        return {table:[hashlib.sha256(r['row'].encode()).hexdigest() for r in conn.execute(
                    f'SELECT to_jsonb(t)::text row FROM "{table}" t ORDER BY to_jsonb(t)::text')] for table in tables}


def originals(before,after):
    for table,hashes in before.items():assert not Counter(hashes)-Counter(after[table]),table


def test_populated_archived027_upgrade_and_independent_restores(tmp_path,monkeypatch):
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    assert version('agentic-rag')=='0.6.34'
    source=tmp_path/'027';source.mkdir()
    archive=tmp_path/'027.tar'
    with archive.open('wb') as stream:subprocess.run(['git','archive',SOURCE,'agentic_rag','sql','pyproject.toml'],cwd=ROOT,stdout=stream,check=True)
    with tarfile.open(archive) as stream:stream.extractall(source,filter='data')
    assert 'version = "0.6.27"' in (source/'pyproject.toml').read_text()
    with isolated_database(Config(),initialize=False) as cfg:
        seeded=run_code(source,cfg,SEED)
        old_reads=run_code(source,cfg,READ)
        assert len(old_reads['local'])==2 and old_reads['scoped']=={'alice':[seeded['documents'][0]],'bob':[seeded['documents'][1]]}
        before=rows(cfg)
        original=upgrade.inventory(cfg,'0.6.27')
        assert len(original['migrations'])==36
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM chunks WHERE embedding IS NOT NULL').fetchone()['n']>=3
            assert conn.execute('SELECT count(DISTINCT actor) n FROM audit_log').fetchone()['n']>=2
            assert conn.execute("SELECT count(*) n FROM mining_queue WHERE status='pending'").fetchone()['n']==1
        source_backup=upgrade.verified_backup(cfg,'0.6.27',tmp_path/'source.dump')
        # Death after037 DDL, before its transaction commit, must retain exactly036.
        run_code(ROOT,cfg,"with db.connect(cfg) as conn:\n applied=db.apply_migrations(conn,db.SQL_DIR,commit=False)\n assert applied==['037_retrieval_feedback.sql', '038_webhooks.sql', '039_metadata_filters.sql']\n os._exit(9)\n",expected=9)
        assert rows(cfg)==before
        assert upgrade.verify_preserved(cfg,source_backup['manifest'])['unchanged']
        migrated=upgrade.local_upgrade(cfg,'0.6.27',tmp_path/'upgrade.dump',apply=True,writers_stopped=True)
        assert migrated['migrations_applied']==['037_retrieval_feedback.sql', '038_webhooks.sql', '039_metadata_filters.sql'] and migrated['restore_verified']
        assert upgrade.verify_preserved(cfg,source_backup['manifest'])['unchanged']
        assert upgrade.local_upgrade(cfg,'0.6.30',tmp_path/'retry.dump',apply=True,writers_stopped=True)['migrations_applied']==[]
        assert run_code(source,cfg,READ)==old_reads
        originals(before,rows(cfg))
        enabled=replace(cfg,feedback_enabled=True)
        with db.connect(enabled,role='writer') as conn:
            event=feedback.capture(conn,enabled,query='absent lexical selector',domain='general',project='/projects/alpha',idempotency_key=str(uuid.uuid4()))
            signal=feedback.submit(conn,enabled,event_id=event['event']['id'],kind='missing_evidence',expected_id=seeded['plain'],idempotency_key=str(uuid.uuid4()))
        from agentic_rag.benchmark.feedback import approve
        approve(enabled,feedback_id=signal['id'],expected_revision=1,query='absent lexical selector')
        with db.connect(cfg) as conn:token=feedback.document_snapshot(conn,seeded['plain'])['version']
        after=rows(cfg)
        originals(before,after)
        for table in before:
            if table not in ('audit_log','schema_migrations'):assert after[table]==before[table],table
        target_backup=upgrade.verified_backup(cfg,'0.6.30',tmp_path/'target.dump')
        assert target_backup['restore_verified']
        with isolated_database(Config(),initialize=False) as restored:
            proof=upgrade.restore_target(restored,tmp_path/'target.dump',target_backup['manifest'],apply=True)
            assert proof['migrations_applied']==[] and proof['restore_verified']
            assert rows(restored)==after
            with db.connect(restored) as conn:
                assert feedback.document_snapshot(conn,seeded['plain'])['version']==token
                assert conn.execute('SELECT expected_version FROM retrieval_feedback_approvals WHERE feedback_id=%s',(signal['id'],)).fetchone()['expected_version']==token
            assert run_code(source,restored,READ)==old_reads
        with isolated_database(Config(),initialize=False) as restored_source:
            proof=upgrade.restore_target(restored_source,tmp_path/'source.dump',source_backup['manifest'],apply=True)
            assert proof['migrations_applied']==['037_retrieval_feedback.sql', '038_webhooks.sql', '039_metadata_filters.sql'] and proof['restore_verified']
            originals(before,rows(restored_source))
            assert run_code(source,restored_source,READ)==old_reads
        # Code rollback retains037 and its data while old readers remain useful.
        assert run_code(source,cfg,READ)==old_reads
        refusal=run_code(source,cfg,"from agentic_rag.service import upgrade\ntry:\n upgrade.inventory(cfg,'0.6.27')\nexcept ValueError as e: print(json.dumps(str(e)))\n")
        assert refusal=='unsupported_source_schema'
        with db.connect(cfg,role='reader') as conn:
            assert feedback.get(conn,cfg,feedback_id=signal['id'])['id']==signal['id']
        print('FEEDBACK_UPGRADE_PROOF',json.dumps({'source':SOURCE,'source_schema':36,'target':'0.6.30','target_schema':39,
            'original_tables':len(before),'original_rows':sum(map(len,before.values())),'restored_tables':len(after),
            'fb1':token,'old_read_counts':{k:len(v) for k,v in old_reads['scoped'].items()},'interrupted_exit':9,
            'source_restore':True,'target_restore':True,'rollback_refusal':refusal},sort_keys=True))
