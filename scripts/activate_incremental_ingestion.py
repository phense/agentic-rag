#!/usr/bin/env python3
"""Explicitly approved local018→019 adoption or code recovery.

Never call this as part of implementation verification on the canonical checkout.
The rehearsal uses an owned clone/config/worker lock. Verified backup is mandatory
for adoption; recovery retains019 and all later knowledge rather than restoring.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from agentic_rag import db, worker
from agentic_rag.config import load_config

BASE = '1294d6c44fd02b66715692f12791bfa2fd4c8856'


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def guard(canonical, candidate, target):
    if not re.fullmatch('[0-9a-f]{40}', target):
        raise ValueError('exact approved commit required')
    if canonical.resolve()==candidate.resolve():
        raise ValueError('source and candidate must be separate checkouts')
    if git(candidate,'rev-parse','HEAD')!=target or git(candidate,'status','--porcelain'):
        raise ValueError('candidate checkout drift')
    if git(canonical,'rev-parse','HEAD') not in (BASE,target) or git(canonical,'status','--porcelain'):
        raise ValueError('source checkout drift or unsupported source')
    if Path(db.__file__).resolve()!=candidate.resolve()/'agentic_rag/db.py' or db.SQL_DIR.resolve()!=candidate.resolve()/'sql':
        raise ValueError('imported modules or migration path differ from candidate')
    subprocess.run(['git','merge-base','--is-ancestor',BASE,target],cwd=candidate,check=True,capture_output=True)
    for root in (canonical,candidate):
        if git(root,'rev-parse',target)!=target:
            raise ValueError('approved target is unavailable')


def schema(conn, candidate):
    expected=[p.name for p in sorted((candidate/'sql').glob('*.sql'))]
    if len(expected)!=19 or expected[-1]!='019_embedding_reuse.sql':
        raise ValueError('unsupported target schema')
    actual=[r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
    if actual not in (expected[:-1],expected):
        raise ValueError('unsupported installed schema')
    return len(actual)


def backup_guard(cfg, dump, report):
    manifest=json.loads(report.read_text())
    flags=('strict_restore_exit_zero','all_public_table_rows_match','application_table_privileges_match','consistent_exported_snapshot')
    if any(manifest.get(flag) is not True for flag in flags) or manifest.get('owned_database_cleanup')!='verified':
        raise ValueError('strict verified backup required')
    if manifest.get('source_db_name')!=cfg.db_name or manifest.get('tables',{}).get('schema_migrations',{}).get('rows')!=18:
        raise ValueError('backup source does not match installed018')
    if dump.stat().st_mode & 0o077 or sha256(dump.read_bytes()).hexdigest()!=manifest.get('dump_sha256'):
        raise ValueError('backup permission or checksum mismatch')


def activate(canonical, candidate, target, *, recover=False, dump=None, report=None, cfg=None):
    canonical,candidate=Path(canonical),Path(candidate)
    guard(canonical,candidate,target)
    cfg=cfg or load_config()
    if not recover:
        if dump is None or report is None:raise ValueError('verified backup paths required')
        backup_guard(cfg,Path(dump),Path(report))
    lock=worker.acquire_lock(worker.LOCK_PATH)
    if lock is None:raise ValueError('worker lock busy or unavailable')
    try:
        # Catch changes between preflight and worker exclusion.
        guard(canonical,candidate,target)
        with db.connect(cfg,role='owner') as conn:
            installed=schema(conn,candidate)
            conn.rollback()
            if not recover:
                applied=db.apply_migrations(conn,candidate/'sql')
                if applied not in ([],['019_embedding_reuse.sql']):raise ValueError('unexpected migrations')
                if schema(conn,candidate)!=19:raise ValueError('target schema verification failed')
                conn.rollback()
            elif installed!=19:
                raise ValueError('code recovery requires retained019')
        revision=BASE if recover else target
        head=git(canonical,'rev-parse','HEAD')
        if head!=revision:
            if recover:
                subprocess.run(['git','switch','--detach',revision],cwd=canonical,check=True,capture_output=True)
            else:
                subprocess.run(['git','merge','--ff-only',revision],cwd=canonical,check=True,capture_output=True)
        if git(canonical,'rev-parse','HEAD')!=revision or git(canonical,'status','--porcelain'):
            raise ValueError('code activation verification failed')
        return dict(revision=revision,schema=19,recovery=recover,worker_lock_released_on_return=True)
    finally:
        lock.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--canonical',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--approved-target',required=True);p.add_argument('--recover',action='store_true')
    p.add_argument('--verified-dump',type=Path);p.add_argument('--backup-report',type=Path)
    args=p.parse_args()
    print(json.dumps(activate(args.canonical,args.candidate,args.approved_target,recover=args.recover,
        dump=args.verified_dump,report=args.backup_report)))


if __name__=='__main__':main()
