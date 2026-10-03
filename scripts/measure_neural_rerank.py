#!/usr/bin/env python3
"""Paired reader-only measurement; private queries/labels stay outside exports."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

from agentic_rag import db, neural_rerank, search
from agentic_rag.config import load_config

BASE = '342bccf6fce51213b7bac1560e41e7554b2e989c'
BASE_SEARCH_SHA256 = '41a373960bc52bcfd579e8b7e89d0b7f376674dad52369dc027e7c9385ced9b4'


def previous(path):
    if sha256(path.read_bytes()).hexdigest() != BASE_SEARCH_SHA256:
        raise ValueError('baseline source does not match the supported previous revision')
    spec = importlib.util.spec_from_file_location('agentic_rag._before_neural', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stats(values):
    return {'raw_ms': [round(v, 3) for v in values],
            'p50_ms': round(statistics.median(values), 3),
            'p95_ms': round(sorted(values)[max(0, int(len(values)*.95+.999)-1)], 3)}


def measure(args):
    old = previous(args.before_search)
    cfg = replace(load_config(), rerank_url=args.url)
    cases = json.loads(args.cases.read_text())
    output = {'source_revision': BASE, 'baseline_search_sha256': sha256(args.before_search.read_bytes()).hexdigest(),
        'candidate_sha256': {name: sha256(Path('agentic_rag', name+'.py').read_bytes()).hexdigest()
            for name in ['search','neural_rerank','config','cli','mcp_server']},
        'method': 'actual previous search module; fixed reader-only repeatable-read snapshot/as_of; alternating pairs; k=3; context<=1200 chars; connection/stdio excluded; uncached embeddings on both routes',
        'model_alias': neural_rerank.MODEL, 'embedding_model': cfg.embed_model,
        'repetitions_per_route': args.repetitions, 'cases': {}}
    original = neural_rerank.order
    stage = []
    def timed(*a):
        start = time.perf_counter()
        try: return original(*a)
        finally: stage.append((time.perf_counter()-start)*1000)
    neural_rerank.order = timed
    try:
        with db.connect(cfg, role='reader') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            output['store_counts'] = conn.execute('SELECT (SELECT count(*) FROM documents) documents,'
                '(SELECT count(*) FROM chunks) chunks').fetchone()
            at = datetime.now(timezone.utc).isoformat()
            for case in cases:
                samples = {'before': [], 'after': []}; first = {}; counts = Counter(); covered = Counter()
                per_call = {'before': [], 'after': []}; stage.clear(); changed = 0
                for iteration in range(args.repetitions+1):
                    results = {}
                    routes = [('before', old.search), ('after', search.search)]
                    if iteration % 2: routes.reverse()
                    for label, run in routes:
                        start = time.perf_counter()
                        hits, warnings = run(conn, cfg, case['query'], project=args.project, k=3, as_of=at)
                        elapsed = (time.perf_counter()-start)*1000
                        if warnings: raise RuntimeError('Inference failed; measurement invalid')
                        if len(hits) != 3 or sum(len(h.snippet) for h in hits) > 1200:
                            raise RuntimeError('Changed result/context budget')
                        for hit in hits:
                            raw = conn.execute('SELECT content FROM chunks WHERE id=%s', (hit.chunk_id,)).fetchone()['content']
                            if raw[hit.snippet_start:hit.snippet_end] != hit.snippet:
                                raise RuntimeError('Invalid original-source span')
                        results[label] = hits
                        coverage = len(set(case['expected']) & {h.slug for h in hits})
                        if iteration == 0: first[label] = round(elapsed, 3)
                        else:
                            samples[label].append(elapsed); covered[label] += coverage
                            per_call[label].append(coverage); counts[label] += len(hits)
                    if iteration:
                        changed += [h.citation for h in results['before']] != [h.citation for h in results['after']]
                        common = {h.citation:h for h in results['before']}
                        if any(asdict(h) != asdict(common[h.citation]) for h in results['after'] if h.citation in common):
                            raise RuntimeError('Payload changed for common source')
                output['cases'][case['label']] = {
                    'expected_sources_per_call': len(case['expected']),
                    'first_call_ms': first,
                    'routes': {label: {**stats(values), 'validated_citations': counts[label],
                        'expected_source_hits': covered[label],
                        'expected_source_denominator': args.repetitions*len(case['expected']),
                        'source_hits_per_call': per_call[label]} for label,values in samples.items()},
                    'changed_citation_lists': changed,
                    'reranker_stage_including_first': stats(stage)}
                print(json.dumps({'finished_case': case['label'],
                    'before_p50': output['cases'][case['label']]['routes']['before']['p50_ms'],
                    'after_p50': output['cases'][case['label']]['routes']['after']['p50_ms'],
                    'source_hits': dict(covered)}), flush=True)
            conn.rollback()
        return output
    finally:
        neural_rerank.order = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-search', type=Path, required=True)
    parser.add_argument('--cases', type=Path, required=True, help='private query and independently read source labels')
    parser.add_argument('--project', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--repetitions', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 20: parser.error('at least20 paired repetitions required')
    result = measure(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__': main()
