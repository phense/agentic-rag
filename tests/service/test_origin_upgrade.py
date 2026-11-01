"""Actual archived 0.6.20 on a populated schema032; additive033 and recovery."""
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

SOURCE = '29a2f44e86502cedcedf8bdea945d0efa2b88f5d'
POPULATE = r'''
import json, os
from agentic_rag import db, domains, jobs, pins, store
from agentic_rag.config import Config
assert db.__file__.startswith(os.getcwd())
cfg=Config(db_name=os.environ['ORIGIN_TEST_DB'], db_host='127.0.0.1', ollama_url='http://127.0.0.1:1')
store.try_embed_texts=lambda *a,**k:None
db.init_db(cfg)
with db.connect(cfg) as c:
    domains.add_domain(c,'operations')
    ids=[]
    for i,(domain,project) in enumerate([('general','/synthetic/a'),('operations','/synthetic/b')]):
        ids.append(store.save_claim(c,cfg,title='Original '+domain,body='Original blue '+domain,
            domain=domain,dtype='memory',project=project,claim_kind='stated',evidence=[{
                'namespace':'session:old-'+domain,'source_id':'original','role':'user',
                'quote':'Original blue '+domain,'complete':True}]).doc_id)
        store.save_assertion(c,cfg,entity=domain,attribute='mode',value='blue',
            domain=domain,project=project,event_at='2026-01-01T00:00:00Z',
            evidence={'source_id':domain,'role':'user','quote':'blue'})
    pins.add_pin(c,body='Keep original pin',scope='global')
    jobs.enqueue_mine(c,cfg,session_id='pending-origin',transcript_path='/synthetic/preserved.jsonl',project='/synthetic/a')
    n=c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']
    assert n==32
print(json.dumps({'schema':n,'ids':ids}))
'''


def test_populated_0_6_20_origin_migration_retry_and_independent_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    root = Path(__file__).resolve().parents[2]
    archive = tmp_path / 'old.tar'
    old = tmp_path / 'old-0.6.20'
    old.mkdir()
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'],
                       cwd=root, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(old, filter='data')
    assert 'version = "0.6.20"' in (old / 'pyproject.toml').read_text()
    with isolated_database(Config(), initialize=False) as cfg:
        env = {**os.environ, 'PYTHONPATH': str(old), 'ORIGIN_TEST_DB': cfg.db_name,
               'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-c', POPULATE], cwd=old, env=env,
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['schema'] == 32
        before = upgrade.inventory(cfg, '0.6.20', identities=True)
        real_apply = db.apply_migrations
        def interrupted(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise RuntimeError('interrupted033')
        monkeypatch.setattr(db, 'apply_migrations', interrupted)
        with pytest.raises(RuntimeError, match='interrupted033'):
            upgrade.local_upgrade(cfg, '0.6.20', tmp_path / 'interrupted.dump',
                                  apply=True, writers_stopped=True)
        monkeypatch.setattr(db, 'apply_migrations', real_apply)
        with db.connect(cfg) as c:
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 32
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        changed = upgrade.local_upgrade(cfg, '0.6.20', tmp_path / 'upgrade.dump',
                                        apply=True, writers_stopped=True)
        assert changed['migrations_applied'] == ['033_trusted_replacements.sql']
        assert changed['restore_verified'] and changed['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg, before)['unchanged']
        with db.connect(cfg) as c:
            validate_schema(c)
            assert c.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n'] == 33
            assert c.execute("SELECT count(*) n FROM mining_queue WHERE kind='mine' AND session_id='pending-origin'").fetchone()['n'] == 1
        retry = upgrade.local_upgrade(cfg, '0.6.20', tmp_path / 'retry.dump',
                                      apply=True, writers_stopped=True)
        assert retry['migrations_applied'] == [] and retry['restore_verified']
        # Post-migration dump is independently restored too; no source-version
        # label is inferred from a schema marker. Release21 bump is a later gate.
        after = upgrade.verified_backup(cfg, '0.6.20', tmp_path / 'after.dump')
        assert after['restore_verified']
        assert upgrade.verify_preserved(cfg, after['manifest'])['unchanged']
