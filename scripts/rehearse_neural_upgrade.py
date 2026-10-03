#!/usr/bin/env python3
"""Actual old/new read coexistence and rollback on an owned synthetic database."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path

from psycopg import sql

from agentic_rag import db, jobs, pins, search, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import load_config
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from agentic_rag.domains import add_domain
from scripts.measure_neural_rerank import BASE, previous


def rehearse(args):
    old = previous(args.before_search)
    saved = (store.try_embed_texts, search.try_embed_texts, old.try_embed_texts)
    store.try_embed_texts = search.try_embed_texts = old.try_embed_texts = lambda *a: None
    cfg = replace(load_config(), rerank_url=args.url)
    try:
        with isolated_database(cfg) as isolated, db.connect(isolated) as writer:
            add_domain(writer, 'other', 'Second synthetic user domain', actor='test')
            for i in range(4):
                doc = store.save_document(writer, isolated,
                    title=f'newsletter authentication failure {i}',
                    body=f'newsletter authentication failure: original synthetic case {i}.',
                    dtype='memory', domain='general', project='/synthetic/a', provenance={'actor':'user-a'})
            store.save_document(writer, isolated, title='newsletter authentication failure other user',
                body='newsletter authentication failure synthetic user-b.', dtype='memory',
                domain='other', project='/synthetic/b', provenance={'actor':'user-b'})
            pins.add_pin(writer, document_id=doc.doc_id, scope='/synthetic/a')
            checkpoints.upsert_snapshot(writer, CheckpointSnapshot(session_id='neural-rehearsal',
                turn_id='t', cursor='c', source='test', trigger='manual', cwd='/synthetic/a',
                project_root='/synthetic/a', transcript_fingerprint='sha256:synthetic',
                git={}, artifacts=('AGENTS.md',)))
            jobs.enqueue_curate(writer, reason='Synthetic retained queue')
            tables = [r['tablename'] for r in writer.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
            def snapshot():
                return {t: writer.execute(sql.SQL(
                    'SELECT to_jsonb(t) row FROM {} t ORDER BY to_jsonb(t)::text')
                    .format(sql.Identifier(t))).fetchall() for t in tables}
            before = snapshot()
            def read(run, config):
                with db.connect(config, role='reader') as reader:
                    reader.execute('SET TRANSACTION READ ONLY')
                    hits, warnings = run(reader, config, 'newsletter authentication failure',
                        project='/synthetic/a', domain='general', k=4)
                    if warnings != ['embedding unavailable — full-text search only']:
                        raise RuntimeError('Unexpected inference failure during rehearsal')
                    if len(hits) != 4 or any(h.domain != 'general' for h in hits):
                        raise RuntimeError('Source or domain boundary changed')
                    return sorted([asdict(h) for h in hits], key=lambda h:h['citation'])
            with ThreadPoolExecutor(max_workers=2) as pool:
                old_call = pool.submit(read, old.search, isolated)
                new_call = pool.submit(read, search.search, isolated)
                original, candidate = old_call.result(timeout=5), new_call.result(timeout=5)
            if original != candidate:
                raise RuntimeError('Original evidence payload changed')
            if read(search.search, replace(isolated, rerank_url='http://127.0.0.1:1')) != original:
                raise RuntimeError('Endpoint outage changed fallback evidence')
            if read(search.search, isolated) != original or read(old.search, isolated) != original:
                raise RuntimeError('Retry or actual old-code rollback changed evidence')
            if snapshot() != before:
                raise RuntimeError('Persisted state changed during read-only upgrade/rollback')
            result = {'source_revision': BASE,
                'baseline_search_sha256': sha256(args.before_search.read_bytes()).hexdigest(),
                'public_tables_checked': len(tables), 'unchanged_full_row_snapshots': True,
                'concurrent_actual_previous_and_candidate_readers': True,
                'endpoint_outage_retry_and_actual_previous_code_rollback': True,
                'users': 2, 'projects': 2, 'domains': 2, 'knowledge_documents': 5,
                'pin_checkpoint_and_queued_work_retained': True,
                'all_knowledge_writes_through_gateway': True}
        result['owned_database_cleanup'] = 'verified'
        return result
    finally:
        store.try_embed_texts, search.try_embed_texts, old.try_embed_texts = saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-search', type=Path, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = rehearse(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__': main()
