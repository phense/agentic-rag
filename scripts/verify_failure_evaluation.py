#!/usr/bin/env python3
"""Public failure measurements and owned existing-installation recovery.

Only snapshot/Trading controls read canonical storage. All model prompts are public
fixtures; all application writes, cloning and migration/recovery happen on owned copies.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from agentic_rag import db,store,worker
from agentic_rag.benchmark import mining_optimization,optimization
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.benchmark.identity import local_model,model_guard
from agentic_rag.config import Config,load_config
from scripts import verify_incremental_ingestion as ingestion
from scripts import activate_failure_evaluation as code_activation
from scripts.verify_contextual_indexing import verified_backup
from scripts.verify_entity_identities import assert_originals,inventories
from scripts.verify_filter_aware_search import privileges,table_names

ROOT=Path(__file__).resolve().parents[1]
SOURCE9='d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d'
SOURCE18=ingestion.BASE


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()


def source9():
    return git('rev-parse',SOURCE9+'^{commit}')


def archive(revision,path):
    path.mkdir()
    data=subprocess.check_output(['git','archive',revision],cwd=ROOT)
    subprocess.run(['tar','-xf','-','-C',str(path)],input=data,check=True)


def code_only(temp,private):
    """Actual source019→target019→source019 Git/CLI roundtrip with overlapping writers."""
    source=temp/'source9';archive(source9(),source)
    clone=temp/'code-only-clone'
    subprocess.run(['git','clone','--quiet','--no-hardlinks',str(ROOT),str(clone)],check=True,capture_output=True)
    subprocess.run(['git','switch','--detach',source9()],cwd=clone,check=True,capture_output=True)
    target=git('rev-parse','HEAD')
    def clone_git(*args):return subprocess.check_output(['git',*args],cwd=clone,text=True).strip()
    cfg=Config(ollama_url='http://localhost:1')
    with isolated_database(cfg) as owned:
        with db.connect(owned,role='writer') as writer:
            store.save_document(writer,owned,title='Public legacy',body='Preserved original user-a knowledge',
                domain='general',dtype='memory',project='/synthetic/ingestion/a')
        with db.connect(owned,role='reader') as reader:
            tables=table_names(reader);originals=inventories(reader,tables);grants=privileges(reader)
        dump=private/'code-only-source019.dump'
        backup=verified_backup(owned,dump);backup.pop('dump')
        backup['source_db_name']=owned.db_name
        with db.connect(owned,role='owner') as owner:backup['source_identity']=code_activation.source_identity(owner)
        backup['verified_at']=datetime.now(timezone.utc).isoformat()
        report_path=private/'code-only-source019-report.json'
        import os
        fd=os.open(report_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as file:json.dump(backup,file,indent=2)
        config=ingestion.config_file(owned,temp/'code-only.toml')
        import os
        env=dict(os.environ,PYTHONPATH=str(clone),AGENTIC_RAG_CONFIG=str(config),AGENTIC_RAG_HOOKS_DISABLE='1')
        def new_command_available():
            result=subprocess.run([sys.executable,'-m','agentic_rag.cli','benchmark','optimize','--help'],
                cwd=clone,env=env,capture_output=True,timeout=30)
            return result.returncode==0
        def activate(recover=False):
            with patch.object(worker,'LOCK_PATH',temp/'code-only.lock'):
                return code_activation.activate(clone,ROOT,target,cfg=owned,dump=dump,
                    report=report_path,recover=recover)
        assert not new_command_available()
        rejections=[]
        dirty=clone/'.drift';dirty.write_text('public owned fixture')
        try:
            try:activate()
            except ValueError:rejections.append('dirty-owned-checkout')
            else:raise AssertionError('dirty checkout must reject')
        finally:dirty.unlink()
        with patch.object(worker,'LOCK_PATH',temp/'code-only.lock'):
            held=worker.acquire_lock(worker.LOCK_PATH);assert held is not None
            try:
                try:activate()
                except ValueError:rejections.append('busy-owned-worker-lock')
                else:raise AssertionError('busy worker lock must reject')
            finally:held.close()
        schema_check=code_activation.schema;schema_calls=0
        def drift_after_schema(*args):
            nonlocal schema_calls
            result=schema_check(*args);schema_calls+=1
            if schema_calls==2:dirty.write_text('public schema-time drift')
            return result
        try:
            with patch.object(code_activation,'schema',drift_after_schema):
                try:activate()
                except ValueError:rejections.append('post-schema-pre-switch-drift')
                else:raise AssertionError('schema-time drift must reject before Git switch')
            assert clone_git('rev-parse','HEAD')==source9()
        finally:dirty.unlink(missing_ok=True)
        with ingestion.overlapping_clients(source,owned,temp) as (advance,observations):
            advance(19)
            adopted=activate();assert adopted['revision']==target and new_command_available()
            retried=activate();assert retried['revision']==target
            advance(19)
            contracts=ingestion.clients(source,owned,temp)
            refs=clone_git('for-each-ref','--format=%(refname) %(objectname)','refs/heads')
            recovered=activate(recover=True);assert recovered['revision']==source9() and not new_command_available()
            assert clone_git('for-each-ref','--format=%(refname) %(objectname)','refs/heads')==refs
        with db.connect(owned,role='reader') as reader:
            assert_originals(reader,originals);assert privileges(reader)==grants
            retained=len(reader.execute('SELECT * FROM schema_migrations').fetchall());assert retained==19
        lock=worker.acquire_lock(temp/'code-only.lock');assert lock is not None;lock.close()
    return dict(source_revision=source9(),target_revision=target,strict_source019_restore=backup,
        adopted=adopted,idempotent_retry=retried,code_recovery=recovered,retained_schema=19,
        original_rows_grants_preserved=True,overlapping_clients=observations,clients=contracts,
        guard_rejections=rejections,worker_lock_reacquired=True,branch_refs_preserved=True,cleanup='verified')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--private-dir',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=20)
    parser.add_argument('--mine-model',action='store_true')
    parser.add_argument('--production-copy',action='store_true')
    parser.add_argument('--trading',action='store_true')
    args=parser.parse_args()
    if not 1<=args.repeats<=30:parser.error('repetitions1–30 required')
    common=Path(git('rev-parse','--git-common-dir'));common=common.resolve() if common.is_absolute() else (ROOT/common).resolve()
    if args.private_dir.resolve().is_relative_to(common.parent):raise ValueError('private artifacts must stay outside repository')
    if args.output.exists() or args.private_dir.exists():raise ValueError('choose new output/private directories')
    if git('status','--porcelain'):raise ValueError('clean committed measured candidate required')
    args.private_dir.mkdir(parents=True,mode=0o700);args.output.mkdir(parents=True)
    paths=[p for directory in ('agentic_rag','sql','scripts') for p in (ROOT/directory).rglob('*')
           if p.suffix in ('.py','.sql','.json') and '__pycache__' not in p.parts]
    frozen={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in paths}
    cfg=load_config();expected_model=local_model(cfg);result=dict(revision=git('rev-parse','HEAD'),source9_revision=source9(),live_source_revision=SOURCE18,
        source_sha256=optimization.source_hash(),embedding_identity=expected_model,production_application_writes=0)
    with tempfile.TemporaryDirectory(prefix='failure-evaluation-rehearsal-') as name:
        temp=Path(name);source=temp/'source18';archive(SOURCE18,source)
        model_guard(cfg,expected_model)
        result['combined018_to019']=ingestion.rehearsal(source,temp,args.private_dir)
        model_guard(cfg,expected_model)
        result['code_only019']=code_only(temp,args.private_dir)
        model_guard(cfg,expected_model)
        candidate=None
        if args.mine_model:
            result['mining']=mining_optimization.run(cfg,output=args.output/'mining',model=True,progress=print)
            candidate=json.loads((args.output/'mining/candidate.json').read_text())
        model_guard(cfg,expected_model)
        result['evaluation']=optimization.run(cfg,output=args.output/'evaluation',context_chars=4000,
            repeats=args.repeats,mining_candidate=candidate,progress=print)
        model_guard(cfg,expected_model)
        if args.production_copy:result['populated_private_recovery']=ingestion.private_recovery(args.private_dir)
        if args.trading:
            result['trading_reader']=ingestion.trading(args.repeats)
            result['trading_reader']['source_revision']=SOURCE18
            result['trading_reader']['limits']='Live018 read-only lexical controls; no Feature10 live policy or semantic quality gain measured.'
    model_guard(cfg,expected_model)
    assert {str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in paths}==frozen
    result['measured_files_sha256']=frozen;result['measured_hashes_unchanged']=True
    (args.output/'results.json').write_text(json.dumps(result,indent=2,default=str)+'\n')


if __name__=='__main__':main()
