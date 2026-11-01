"""Real populated 0.6.21 upgrade: originals, privileges, queued work and retry."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from agentic_rag import db, query_cache
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service import upgrade
from agentic_rag.service.schema import validate_schema

SOURCE = '64f2104d7e8b542dbfb72c6fbb40196364afdc95'
POPULATE = r'''
import json, os
from agentic_rag import db, domains, jobs, pins, store
from agentic_rag.config import Config
assert db.__file__.startswith(os.getcwd())
cfg=Config(db_name=os.environ['LEXICAL_UPGRADE_DB'], db_host='127.0.0.1', ollama_url='http://127.0.0.1:1')
store.try_embed_texts=lambda *a,**k:None
db.init_db(cfg)
with db.connect(cfg) as c:
    domains.add_domain(c,'operations')
    ids=[]
    for i,(domain,project) in enumerate([('general','/synthetic/a'),('operations','/synthetic/b')]):
        ids.append(store.save_claim(c,cfg,title='Original '+domain,body='Original blue '+domain,
            domain=domain,dtype='memory',project=project,claim_kind='stated',evidence=[{
                'namespace':'session:lexical-'+domain,'source_id':'original','role':'user',
                'quote':'Original blue '+domain,'complete':True}]).doc_id)
        store.save_assertion(c,cfg,entity=domain,attribute='mode',value='blue',
            domain=domain,project=project,event_at='2026-01-01T00:00:00Z',
            evidence={'source_id':domain,'role':'user','quote':'blue'})
    pins.add_pin(c,body='Keep original pin',scope='global')
    jobs.enqueue_mine(c,cfg,session_id='pending-lexical',transcript_path='/synthetic/preserved.jsonl',project='/synthetic/a')
    n=c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']
    assert n==33
print(json.dumps({'schema':n,'ids':ids}))
'''

READ_OLD = r'''
import json,os
from agentic_rag import db
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope,apply_connection
assert db.__file__.startswith(os.getcwd())
cfg=Config(db_name=os.environ['LEXICAL_UPGRADE_DB'],db_host='127.0.0.1')
out=[]
for domain,project in [('general','/synthetic/a'),('operations','/synthetic/b')]:
    p=Principal('archived-reader','owned','test',frozenset({domain}),frozenset(),frozenset({project}),frozenset())
    with db.connect(cfg,role='reader') as c:
        apply_connection(c,RequestScope(p,cfg,True))
        rows=c.execute("SELECT * FROM hybrid_search_candidates('blue',NULL,NULL,150,NULL,'2026-11-01',false)").fetchall()
        assert rows and all(r['domain']==domain for r in rows)
        out.append(rows)
print(json.dumps(out,sort_keys=True,default=str))
'''


def function_privileges(cfg):
    with db.connect(cfg) as c:
        return c.execute("""SELECT oid,proname,proowner,proacl::text,prosecdef,proleakproof,proconfig,provolatile,
            pg_get_function_identity_arguments(oid) arguments
            FROM pg_proc WHERE proname=ANY(%s) ORDER BY proname""", ([
                'hybrid_search_candidates', 'hybrid_search_candidates_planned',
                'contextual_search_candidates', 'contextual_search_candidates_planned'],)).fetchall()


def test_populated_0_6_21_lexical_upgrade_retry_and_independent_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    root = Path(__file__).resolve().parents[2]
    archive = tmp_path / 'old.tar'
    old = tmp_path / 'old-0.6.21'
    old.mkdir()
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'],
                       cwd=root, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(old, filter='data')
    assert 'version = "0.6.21"' in (old / 'pyproject.toml').read_text()
    with isolated_database(Config(), initialize=False) as cfg:
        env = {**os.environ, 'PYTHONPATH': str(old), 'LEXICAL_UPGRADE_DB': cfg.db_name,
               'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-c', POPULATE], cwd=old, env=env,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['schema'] == 33
        def old_read():
            result = subprocess.run([sys.executable, '-c', READ_OLD], cwd=old, env=env,
                                    text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        old_results = old_read()
        privileges = function_privileges(cfg)
        assert len(privileges) == 4 and not any(row['prosecdef'] or row['proleakproof'] for row in privileges)
        before = upgrade.inventory(cfg, '0.6.21', identities=True)
        real_apply = db.apply_migrations
        def interrupted(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('interrupted034')
        monkeypatch.setattr(db, 'apply_migrations', interrupted)
        with pytest.raises(RuntimeError, match='interrupted034'):
            upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'interrupted.dump',
                                  apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as c:
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 33
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        changed = upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'upgrade.dump',
                                        apply=True, writers_stopped=True)
        assert changed['migrations_applied'] == ['034_lexical_eligibility_work.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert function_privileges(cfg) == privileges
        assert old_read() == old_results  # Genuine archived0.6.21 with schema034.
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        with db.connect(cfg) as c:
            validate_schema(c)
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 34
            assert c.execute("SELECT count(*) n FROM mining_queue WHERE kind='mine' AND session_id='pending-lexical'").fetchone()['n'] == 1
        retry = upgrade.local_upgrade(cfg, '0.6.21', tmp_path / 'retry.dump',
                                      apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        # The target release must support its own truthful backup label, with a
        # real independent restore; accepting only its predecessor breaks recovery.
        after = upgrade.verified_backup(cfg, '0.6.22', tmp_path / 'after.dump')
        assert after['restore_verified']
        assert after['manifest']['source_version'] == '0.6.22'
        assert upgrade.verify_preserved(cfg, after['manifest'])['unchanged']
