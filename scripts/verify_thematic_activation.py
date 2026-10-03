#!/usr/bin/env python3
"""Execute the exact PB activation/rollback snippets on owned Git/DB/lock fixtures."""
from pathlib import Path
from hashlib import sha256
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch

from agentic_rag import db, worker
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from scripts.verify_thematic_summaries import BASE, ROOT, PROJECT, seed, cli_call
from scripts.verify_contextual_indexing import snapshot
from scripts.verify_filter_aware_search import table_names


def main():
    playbook=ROOT/'docs/playbooks/thematic-summaries.md'
    snippets=re.findall(r'```python\n(.*?)```',playbook.read_text(),re.S)
    assert len(snippets)==3
    with tempfile.TemporaryDirectory(prefix='thematic-activation-') as name:
        temp=Path(name);clone=temp/'canonical';lockfile=temp/'worker.lock'
        def git(*args):
            return subprocess.check_output(['git',*args],cwd=clone,stderr=subprocess.DEVNULL,text=True).strip()
        subprocess.run(['git','clone','--quiet','--no-hardlinks','--no-checkout',str(ROOT),str(clone)],check=True)
        git('switch','-c','rehearsal-source',BASE)
        git('switch','-c','rehearsal-candidate')
        for relative in ('agentic_rag/thematic.py','agentic_rag/profiles.py','agentic_rag/context.py',
                         'agentic_rag/store.py','agentic_rag/cli.py','agentic_rag/mcp_server.py','sql/017_thematic_summaries.sql'):
            target=clone/relative;target.write_bytes((ROOT/relative).read_bytes())
        git('add','agentic_rag','sql')
        git('-c','commit.gpgsign=false','-c','user.name=Rehearsal','-c','user.email=rehearsal@example.invalid',
            'commit','-m','Owned activation fixture only')
        target=git('rev-parse','HEAD');git('switch','rehearsal-source')
        with isolated_database(Config(ollama_url='http://localhost:1')) as cfg:
            with db.connect(cfg,role='writer') as conn,patch('agentic_rag.store.try_embed_texts',return_value=None): seed(conn,cfg)
            config=temp/'config.toml';config.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[ollama]\nurl="http://localhost:1"\n')
            with db.connect(cfg,role='reader') as conn:
                tables=table_names(conn);before=snapshot(conn,tables)
            args=['search','provider outage','--project',PROJECT,'--domain','infrastructure','--strategy','lexical','--json']
            source=cli_call(clone,config,args)
            original_lock=worker.acquire_lock
            with patch.dict(os.environ,{'RAG_CANONICAL_PATH':str(clone),'RAG_APPROVED_TARGET_REVISION':target,'RAG_SOURCE_REVISION':BASE}), \
                    patch('agentic_rag.config.load_config',return_value=cfg), \
                    patch.object(worker,'acquire_lock',lambda:original_lock(lockfile)):
                held=original_lock(lockfile)
                assert held is not None
                try:
                    try: exec(snippets[1],{})
                    except SystemExit as exc: assert 'lock unavailable' in str(exc).lower()
                    else: raise AssertionError('Busy lock must stop activation')
                    assert git('rev-parse','HEAD')==BASE
                finally: held.close()
                exec(snippets[1],{})
                assert git('rev-parse','HEAD')==target
                candidate=cli_call(clone,config,args)
                exec(snippets[2],{})
                assert git('rev-parse','HEAD')==BASE and git('branch','--show-current')==''
                assert git('rev-parse','rehearsal-source')==target
                rollback=cli_call(clone,config,args)
                reacquired=original_lock(lockfile);assert reacquired is not None;reacquired.close()
            assert [e['citation'] for e in source['results']]==[e['citation'] for e in candidate['results']]==[e['citation'] for e in rollback['results']]
            with db.connect(cfg,role='reader') as conn:
                assert before==snapshot(conn,tables)
                assert len(conn.execute('SELECT filename FROM schema_migrations').fetchall())==17
    output=dict(playbook_sha256=sha256(playbook.read_bytes()).hexdigest(),
        source_revision=BASE,approved_target_fixture_revision=target,busy_lock_stops_without_changes=True,
        exact_activation_and_rollback_snippets_passed=True,old_new_rollback_citation_parity=True,
        protected_rows_preserved=True,schema017_retained=True,prior_branch_tip_preserved=True,
        lock_released=True,owned_resources_cleaned=True,
        limits='Owned local fixture only; no production Git/database/worker lock changes or service operations.')
    destination=Path(sys.argv[1]);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output))


if __name__=='__main__': main()
