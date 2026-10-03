#!/usr/bin/env python3
"""Execute exact PB-5.8 upgrade/code-recovery snippets on owned fixtures."""
from pathlib import Path
from hashlib import sha256
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch

from agentic_rag import db, worker, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from scripts.verify_entity_identities import BASE, ROOT, PROJECT, NEW_TABLES, seed, cli_call, config_file, inventories, assert_originals
from scripts.verify_filter_aware_search import table_names, privileges


def main():
    playbook=ROOT/'docs/playbooks/entity-identities.md'
    snippets=re.findall(r'```python\n(.*?)```',playbook.read_text(),re.S)
    assert len(snippets)==3
    target=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert target!=BASE, 'Commit reviewed candidate before activation rehearsal'
    with tempfile.TemporaryDirectory(prefix='entity-activation-') as name:
        temp=Path(name);clone=temp/'canonical';lockfile=temp/'worker.lock'
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=clone,stderr=subprocess.DEVNULL,text=True).strip()
        subprocess.run(['git','clone','--quiet','--no-hardlinks','--no-checkout',str(ROOT),str(clone)],check=True)
        git('switch','-c','rehearsal-source',BASE)
        for path in (ROOT/'agentic_rag').glob('*.py'):
            assert subprocess.check_output(['git','show',f'{target}:agentic_rag/{path.name}'],cwd=ROOT)==path.read_bytes()
        assert subprocess.check_output(['git','show',f'{target}:sql/018_entity_identities.sql'],cwd=ROOT)==(ROOT/'sql/018_entity_identities.sql').read_bytes()
        initial=db.init_db
        with patch.object(db,'init_db',lambda c:initial(c,sql_dir=clone/'sql')),isolated_database(Config(ollama_url='http://localhost:1')) as cfg:
            config=config_file(cfg,temp/'config.toml');seed(cfg,clone,config)
            with db.connect(cfg,role='owner') as c:
                tables=table_names(c);originals=inventories(c,tables);grants=privileges(c)
                assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==17
            args=['search','orion-old','--project',PROJECT,'--domain','general','--strategy','lexical','--json']
            source=cli_call(clone,config,args)
            original_lock=worker.acquire_lock
            with patch.dict(os.environ,{'RAG_CANONICAL_PATH':str(clone),'RAG_APPROVED_TARGET_REVISION':target,'RAG_SOURCE_REVISION':BASE,'RAG_CANDIDATE_PATH':str(ROOT)}), \
                    patch('agentic_rag.config.load_config',return_value=cfg), \
                    patch.object(worker,'acquire_lock',lambda:original_lock(lockfile)):
                rejects=[]
                def reject(expected,code=snippets[1]):
                    try:exec(code,{})
                    except SystemExit as exc:assert expected in str(exc),str(exc)
                    else:raise AssertionError('Unsafe preflight must reject')
                    with db.connect(cfg,role='reader') as c:
                        assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==17
                        assert_originals(c,originals)
                    assert git('rev-parse','HEAD')==BASE
                    rejects.append(expected)
                with patch.dict(os.environ,{'RAG_SOURCE_REVISION':'unsupported'}):reject('Unsupported source')
                with patch.dict(os.environ,{'RAG_APPROVED_TARGET_REVISION':target[:12]}):reject('exact approved commit')
                with patch.dict(os.environ,{'RAG_CANDIDATE_PATH':str(clone)}):reject('not the approved target')
                marker=ROOT/'.entity-activation-owned-dirty-marker'
                assert not marker.exists()
                try:
                    marker.write_text('Owned rejection fixture')
                    reject('Candidate checkout drift')
                finally:marker.unlink()
                with patch.object(db,'__file__',str(clone/'agentic_rag/db.py')):reject('Imported modules')
                with patch.object(db,'SQL_DIR',clone/'sql'):reject('Migration path')
                clone_marker=clone/'.owned-dirty-marker';clone_marker.write_text('Owned fixture')
                try:reject('Source checkout drift')
                finally:clone_marker.unlink()
                with patch.dict(os.environ,{'RAG_SOURCE_REVISION':'unsupported'}):reject('Unsupported recovery source',snippets[2])
                with patch.dict(os.environ,{'RAG_APPROVED_TARGET_REVISION':target[:12]}):reject('exact approved commit',snippets[2])
                clone_marker.write_text('Owned fixture')
                try:reject('Recovery checkout drift',snippets[2])
                finally:clone_marker.unlink()
                # Drift after lock acquisition must be caught by the second guard.
                def changed_after_lock():
                    result=original_lock(lockfile)
                    clone_marker.write_text('Owned post-lock drift')
                    return result
                for code in snippets[1:]:
                    try:
                        with patch.object(worker,'acquire_lock',changed_after_lock):
                            reject('checkout drift',code)
                    finally:clone_marker.unlink()
                    released=original_lock(lockfile);assert released is not None;released.close()
                held=original_lock(lockfile);assert held is not None
                try:
                    for code in snippets[1:]:
                        try:exec(code,{})
                        except SystemExit as exc:assert 'lock busy' in str(exc).lower()
                        else:raise AssertionError('Busy lock must stop activation/recovery')
                    assert git('rev-parse','HEAD')==BASE
                    with db.connect(cfg,role='reader') as c:
                        assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==17
                        assert_originals(c,originals)
                finally:held.close()
                with contextlib.redirect_stdout(io.StringIO()):exec(snippets[1],{})
                assert git('rev-parse','HEAD')==target
                candidate=cli_call(clone,config,args)
                # Retry after a successful DB commit but before acknowledged code
                # activation: move owned checkout back, retaining completed018.
                git('switch','--detach',BASE)
                with contextlib.redirect_stdout(io.StringIO()):exec(snippets[1],{})
                assert git('rev-parse','HEAD')==target
                with contextlib.redirect_stdout(io.StringIO()):exec(snippets[2],{})
                assert git('rev-parse','HEAD')==BASE and git('branch','--show-current')==''
                assert git('rev-parse','rehearsal-source')==target
                rollback=cli_call(clone,config,args)
                reacquired=original_lock(lockfile);assert reacquired is not None;reacquired.close()
            assert [e['citation'] for e in source['results']]==[e['citation'] for e in candidate['results']]==[e['citation'] for e in rollback['results']]
            with db.connect(cfg,role='owner') as c:
                assert_originals(c,originals)
                assert len(c.execute('SELECT * FROM schema_migrations').fetchall())==18
                assert [r for r in privileges(c) if r['table_name'] not in NEW_TABLES]==grants
            with db.connect(cfg,role='writer') as c:
                assert store.backfill_entity_identities(c)['mapped']==0
    output=dict(playbook_sha256=sha256(playbook.read_bytes()).hexdigest(),source_revision=BASE,
        candidate_revision=target,busy_lock_stops_upgrade_and_recovery_without_changes=True,
        exact_activation_and_recovery_snippets_passed=True,preflight_rejection_checks=rejects,post_migration_activation_retry_passed=True,
        old_new_rollback_citation_parity=True,original_rows_and_grants_preserved=True,schema018_retained=True,
        prior_branch_tip_preserved=True,lock_released=True,owned_resources_cleaned=True,
        limits='Owned local clone/database/worker lock and temporary owned candidate dirty marker only. No production deployment or service operation. Backup/full restore/MCP evidence is separate.')
    destination=Path(sys.argv[1]);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output))


if __name__=='__main__':main()
