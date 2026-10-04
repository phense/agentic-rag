#!/usr/bin/env python3
"""Separately authorized source019 code-only activation/recovery; never migrates."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from agentic_rag import db,worker
from agentic_rag.config import load_config
from scripts.activate_incremental_ingestion import source_identity

SOURCE='d5e2ce49a4a48554b5d9de58c3beb3b5a4d43d9d'


def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()


def guard(canonical,candidate,target):
    if not re.fullmatch('[0-9a-f]{40}',target):raise ValueError('exact approved commit required')
    canonical,candidate=Path(canonical).resolve(),Path(candidate).resolve()
    if canonical==candidate:raise ValueError('separate source/candidate checkouts required')
    if git(candidate,'rev-parse','HEAD')!=target or git(candidate,'status','--porcelain'):
        raise ValueError('candidate checkout drift')
    current=git(canonical,'rev-parse','HEAD')
    if git(canonical,'status','--porcelain') or (current!=target and
        git(canonical,'rev-parse','HEAD^{tree}')!=git(candidate,'rev-parse',SOURCE+'^{tree}')):
        raise ValueError('source checkout drift or unsupported source019 tree')
    if Path(db.__file__).resolve()!=candidate/'agentic_rag/db.py' or db.SQL_DIR.resolve()!=candidate/'sql':
        raise ValueError('imported modules or SQL path differ from candidate')
    for root in (canonical,candidate):
        if git(root,'rev-parse',target)!=target:raise ValueError('approved target unavailable')
    result=subprocess.run(['git','merge-base','--is-ancestor',SOURCE,target],cwd=candidate,capture_output=True)
    if result.returncode:raise ValueError('target does not extend supported source019')


def schema(cfg,candidate):
    expected=[p.name for p in sorted((Path(candidate)/'sql').glob('*.sql'))]
    if len(expected)!=19 or expected[-1]!='019_embedding_reuse.sql':raise ValueError('unchanged019 target required')
    for name in expected:
        original=subprocess.check_output(['git','show',SOURCE+':sql/'+name],cwd=candidate)
        if sha256(original).digest()!=sha256((Path(candidate)/'sql'/name).read_bytes()).digest():
            raise ValueError('code-only target changed existing SQL; migration review required')
    # This helper has no DDL/write path, and uses the existing reader role.
    with db.connect(cfg,role='reader') as connection:
        actual=[r['filename'] for r in connection.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
    if actual!=expected:raise ValueError('code-only activation requires exact019 ledger')
    return 19


def backup_guard(cfg,dump,report):
    manifest=json.loads(Path(report).read_text())
    flags=('strict_restore_exit_zero','all_public_table_rows_match','application_table_privileges_match','consistent_exported_snapshot')
    if any(manifest.get(f) is not True for f in flags) or manifest.get('owned_database_cleanup')!='verified':
        raise ValueError('strict verified source019 backup required')
    if manifest.get('source_db_name')!=cfg.db_name or manifest.get('tables',{}).get('schema_migrations',{}).get('rows')!=19:
        raise ValueError('backup source does not match installed019')
    for path in (Path(dump),Path(report)):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o777!=0o600:
            raise ValueError('new private0600 backup/report required')
    if manifest.get('dump_sha256')!=sha256(Path(dump).read_bytes()).hexdigest():raise ValueError('backup checksum mismatch')
    try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(manifest['verified_at'])).total_seconds()
    except (KeyError,ValueError,TypeError):raise ValueError('fresh verified backup date required') from None
    if not 0<=age<=3600:raise ValueError('verified source019 backup must be fresh within one hour')
    with db.connect(cfg,role='owner') as connection:
        if manifest.get('source_identity')!=source_identity(connection):raise ValueError('backup server/database identity mismatch')


def activate(canonical,candidate,target,*,cfg=None,dump=None,report=None,recover=False):
    canonical,candidate=Path(canonical),Path(candidate)
    cfg=cfg or load_config()
    guard(canonical,candidate,target)
    if not recover:
        if dump is None or report is None:raise ValueError('strict source019 backup/report required')
        backup_guard(cfg,dump,report)
    schema(cfg,candidate);guard(canonical,candidate,target)
    lock=worker.acquire_lock(worker.LOCK_PATH)
    if lock is None:raise ValueError('worker lock busy or unavailable')
    try:
        guard(canonical,candidate,target)
        if not recover:backup_guard(cfg,dump,report)
        schema(cfg,candidate)
        guard(canonical,candidate,target)  # Check immediately after schema and before Git.
        if recover:
            subprocess.run(['git','switch','--detach',SOURCE],cwd=canonical,check=True,capture_output=True)
            expected=SOURCE
        else:
            subprocess.run(['git','merge','--ff-only',target],cwd=canonical,check=True,capture_output=True)
            expected=target
        guard(canonical,candidate,target)
        if git(canonical,'rev-parse','HEAD')!=expected:raise ValueError('code switch did not reach exact revision')
        return dict(revision=expected,schema=19,recovery=recover,worker_lock_released_on_return=True)
    finally:lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--canonical',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--approved-target',required=True);p.add_argument('--verified-dump',type=Path)
    p.add_argument('--backup-report',type=Path);p.add_argument('--recover',action='store_true')
    a=p.parse_args()
    print(json.dumps(activate(a.canonical,a.candidate,a.approved_target,dump=a.verified_dump,
        report=a.backup_report,recover=a.recover),indent=2))


if __name__=='__main__':main()
