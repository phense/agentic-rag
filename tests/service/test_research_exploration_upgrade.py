"""Code-only 0.6.23 adoption and rollback on a genuinely populated source."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from agentic_rag import db, query_cache
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.research import research
from agentic_rag.service import upgrade

SOURCE='c33e11fd5ccc4fa1e11c92fbcd16e9fee0cbdcd9'
SEED=r'''
from agentic_rag import domains, store, pins, jobs
assert db.__file__.startswith(os.getcwd())
store.try_embed_texts=lambda *a,**k:None
db.init_db(cfg)
with db.connect(cfg) as conn:
    domains.add_domain(conn,'operations')
    docs=[]
    for domain,project in [('general','/projects/alpha'),('operations','/projects/beta')]:
        body='Original protected evidence '+domain
        saved=store.save_claim(conn,cfg,title=body,body=body,domain=domain,project=project,
            dtype='memory',claim_kind='stated',evidence=[{'namespace':'upgrade69','source_id':domain+str(n),
            'role':'user','quote':body,'complete':True} for n in range(2)])
        store.review_claim(conn,saved.doc_id,state='confirmed',reason='original synthetic source reviewed')
        docs.append(saved.doc_id)
    fact=store.save_assertion(conn,cfg,entity='lyra',attribute='port',value='8766',domain='general',
        project='/projects/alpha',event_at='2026-01-01T00:00:00Z',evidence={'namespace':'upgrade69',
        'source_id':'port','role':'user','quote':'lyra port 8766','complete':True})
    alias=store.save_entity_alias(conn,cfg,alias='lyra-retired',target='lyra',domain='general',
        project='/projects/alpha',effective_at='2026-02-01T00:00:00Z',confirm=True,
        evidence={'namespace':'upgrade69','source_id':'alias','role':'user',
        'quote':'lyra-retired is another name for lyra.','complete':True})
    pins.add_pin(conn,body='Original preserved pin',scope='global')
    jobs.enqueue_mine(conn,cfg,session_id='pending-research-upgrade',
        transcript_path='/synthetic/preserved.jsonl',project='/projects/alpha')
print(json.dumps({'documents':docs,'fact':fact.doc_id,'alias':alias['document_id']}))
'''
READ=r'''
from agentic_rag.research import research
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope
assert db.__file__.startswith(os.getcwd())
p=Principal('reader','synthetic','upgrade69',frozenset({'general'}),frozenset(),
            frozenset({'/projects/alpha'}),frozenset())
with request_scope(p,cfg,read_only=True):
    result=research(cfg,'Original',strategy='lexical')
assert result['termination']!='worker_failure',result
print(json.dumps(sorted(e['document_id'] for e in result['evidence'])))
'''


def old_run(source,cfg,code):
    env=dict(os.environ,RESEARCH_UPGRADE_DB=cfg.db_name,PYTHONPATH=str(source),AGENTIC_RAG_HOOKS_DISABLE='1')
    prefix="import json,os\nfrom agentic_rag import db\nfrom agentic_rag.config import Config\ncfg=Config(db_name=os.environ['RESEARCH_UPGRADE_DB'],db_host='127.0.0.1',ollama_url='http://127.0.0.1:1')\n"
    run=subprocess.run([sys.executable,'-c',prefix+code],cwd=source,env=env,capture_output=True,text=True,timeout=45)
    assert run.returncode==0,run.stderr
    return json.loads(run.stdout.splitlines()[-1])


def test_populated_0_6_23_research_adoption_restore_and_old_reader_rollback(tmp_path,monkeypatch):
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    source=tmp_path/'source';source.mkdir()
    archive=tmp_path/'source.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git','archive',SOURCE,'agentic_rag','sql','pyproject.toml'],stdout=stream,check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source,filter='data')
    assert 'version = "0.6.23"' in (source/'pyproject.toml').read_text()
    with isolated_database(Config(),initialize=False) as cfg:
        original=old_run(source,cfg,SEED)
        old_results=old_run(source,cfg,READ)
        assert old_results==[original['documents'][0]]
        before=upgrade.inventory(cfg,'0.6.23')
        assert len(before['migrations'])==35
        verified=upgrade.verified_backup(cfg,'0.6.23',tmp_path/'before.dump')
        assert verified['restore_verified']
        result=research(cfg,'lyra-retired port',domain='general',project='/projects/alpha',strategy='lexical')
        assert result['termination']!='worker_failure',result
        assert original['fact'] in {e['document_id'] for e in result['evidence']}
        assert original['documents'][1] not in json.dumps(result)
        assert result['abstained'] and result['usage']['provider_calls']==0
        assert upgrade.inventory(cfg,'0.6.24')['tables']==before['tables']
        assert old_run(source,cfg,READ)==old_results
        assert upgrade.verify_preserved(cfg,verified['manifest'])['unchanged']
        after=upgrade.verified_backup(cfg,'0.6.24',tmp_path/'after.dump')
        assert after['restore_verified'] and after['manifest']['source_version']=='0.6.24'
        assert upgrade.inventory(cfg,'0.6.24')['tables']==before['tables']
