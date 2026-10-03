#!/usr/bin/env python3
"""Read-only paired measurement. Never export corpus text, queries or identities."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import statistics
import time

from agentic_rag import db, search
from agentic_rag.config import load_config
from agentic_rag.retrieval import strong_symbols
from agentic_rag.scope import selection


def measure(before_path, project, repetitions):
    spec = importlib.util.spec_from_file_location('agentic_rag._previous_search', before_path)
    before = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module while evaluating annotations.
    import sys
    sys.modules[spec.name] = before
    spec.loader.exec_module(before)
    cfg = load_config()
    calls = Counter()
    for name, module in [('before', before), ('after', search)]:
        original = module.try_embed_texts
        def counted(*args, _name=name, _original=original):
            calls[_name] += 1
            return _original(*args)
        module.try_embed_texts = counted
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        counts = conn.execute('SELECT (SELECT count(*) FROM documents) documents, '
            '(SELECT count(*) FROM chunks) chunks, (SELECT count(*) FROM pins) pins, '
            '(SELECT count(*) FROM audit_log) audit').fetchone()
        source = conn.execute("""SELECT d.id,d.slug,c.content FROM documents d
            JOIN chunks c ON c.document_id=d.id WHERE d.status='active'
            AND assertion_eligible(d.id,now(),false) AND d.project_scope=ANY(%s)
            AND d.slug ~ '^[a-z0-9]+(-[a-z0-9]+)+$'
            AND c.content ~ '(Error|Exception|ERR_)'
            ORDER BY d.id,c.idx LIMIT 250""", (selection(project),)).fetchall()
        target = None
        for row in source:
            for symbol in strong_symbols(row['content']):
                if not 10 <= len(symbol) < 70:
                    continue
                hits, _ = search.search(conn, cfg, symbol, project=project, strategy='lexical')
                if str(row['id']) in {h.document_id for h in hits}:
                    target = (row, symbol)
                    break
            if target:
                break
        if not target:
            raise RuntimeError('No eligible scoped symbol example; do not invent one')
        row, symbol = target
        cases = [('document_uuid', str(row['id'])), ('document_slug', row['slug']),
                 ('standalone_error', symbol),
                 ('ordinary_question_control', 'Wie werden OAuth-Probleme bei der Newsletter-Erstellung behandelt?')]
        result = {'store_counts': counts, 'project': project, 'read_only': True,
            'model': cfg.embed_model, 'repetitions_per_route': repetitions,
            'before_file_sha256': sha256(Path(before_path).read_bytes()).hexdigest(),
            'after_file_sha256': sha256(Path(search.__file__).read_bytes()).hexdigest(),
            'method': 'same snapshot/connection; alternating paired order; first-call separate; no server cold-cache claim',
            'cases': {}}
        for label, query in cases:
            samples = {'before': [], 'after': []}
            first = {}
            expected = Counter()
            citations = Counter()
            matching_results = 0
            calls.clear()
            for iteration in range(repetitions + 1):
                signatures = {}
                routes = [('before', before), ('after', search)]
                if iteration % 2:
                    routes.reverse()
                for name, module in routes:
                    start = time.perf_counter()
                    hits, warnings = module.search(conn, cfg, query, project=project)
                    elapsed = (time.perf_counter() - start) * 1000
                    if warnings:
                        raise RuntimeError('Embedding or retrieval unavailable; invalidate measurement')
                    signatures[name] = [h.citation for h in hits]
                    for hit in hits:
                        original = conn.execute('SELECT content FROM chunks WHERE id=%s',
                                                (hit.chunk_id,)).fetchone()['content']
                        if original[hit.snippet_start:hit.snippet_end] != hit.snippet:
                            raise RuntimeError('Invalid original citation')
                    if iteration == 0:
                        first[name] = elapsed
                    else:
                        samples[name].append(elapsed)
                        expected[name] += str(row['id']) in {h.document_id for h in hits}
                        citations[name] += len(hits)
                if iteration and signatures['before'] == signatures['after']:
                    matching_results += 1
            metrics = {}
            for name, values in samples.items():
                ordered = sorted(values)
                metrics[name] = {'first_call_ms': round(first[name], 3),
                    'p50_ms': round(statistics.median(values), 3),
                    'p95_ms': round(ordered[max(0, int(len(values)*.95 + .999)-1)], 3),
                    'embedding_calls_including_first': calls[name],
                    'expected_document_hits': expected[name] if label != 'ordinary_question_control' else None,
                    'validated_citations': citations[name]}
            result['cases'][label] = {'routes': metrics,
                'equal_citation_lists': matching_results,
                'p50_speedup': round(metrics['before']['p50_ms']/metrics['after']['p50_ms'], 3)}
            print(json.dumps({'finished_case': label, **result['cases'][label]}), flush=True)
        conn.rollback()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-search', type=Path, required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--repetitions', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 20:
        parser.error('at least 20 paired repetitions are required')
    result = measure(args.before_search, args.project, args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
