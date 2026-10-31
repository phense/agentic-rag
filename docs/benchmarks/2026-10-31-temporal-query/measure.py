"""RAG-064 temporal search measurement on the frozen synthetic corpus.

Feature off versus on over the same disposable database, development and
held-out cases reported separately. Lexical retrieval only: embeddings and the
neural reranker are deliberately unavailable, so no provider or model is called.
Run from the repository root:
  env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=<port> \
    .venv/bin/python docs/benchmarks/2026-10-31-temporal-query/measure.py > results.json
"""
from dataclasses import replace
import json
import os
import platform
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.getcwd())
from agentic_rag import db, search, store, temporal  # noqa: E402
from agentic_rag.benchmark import temporal_query as fixture  # noqa: E402
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402
from agentic_rag.domains import seed_defaults  # noqa: E402

REPEATS, WARMUP = 15, 3


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def parser_quality(cases):
    correct, failures = 0, []
    for case in cases:
        expected = case['expected']
        try:
            got = temporal.interpret(case['query'], reference=case['reference'], timezone=case['timezone'])
            ok = ('error' not in expected and got.status == expected['status'] and (
                expected['status'] != 'interval' or (got.start.isoformat(), got.end.isoformat()) == (
                    expected['start'].replace('Z', '+00:00'), expected['end'].replace('Z', '+00:00'))))
            observed = {'status': got.status, 'start': got.start and got.start.isoformat(),
                        'end': got.end and got.end.isoformat(), 'reasons': list(got.reasons)}
        except ValueError as error:
            ok = 'error' in expected and str(error).startswith(expected['error'])
            observed = {'error': str(error).split(':')[0]}
        correct += ok
        if not ok:
            failures.append({'id': case['id'], 'expected': expected, 'observed': observed})
    return {'cases': len(cases), 'correct': correct, 'accuracy': round(correct / len(cases), 4), 'failures': failures}


def run(conn, cfg, case, mode, keys):
    started = time.perf_counter()
    diagnostics = {}
    try:
        hits, warnings = search.search(conn, cfg, case['query'], **fixture.options(case, mode=mode),
                                       diagnostics=diagnostics)
        error = None
    except ValueError as exc:
        hits, warnings, error = [], [], str(exc).split(':')[0]
    elapsed = (time.perf_counter() - started) * 1000
    conn.rollback()
    return {'order': fixture.ranked_keys(hits, keys), 'hits': hits, 'warnings': warnings, 'error': error,
            'report': diagnostics.get('temporal'), 'ms': elapsed}


def quality(order, expected, k):
    top = order[:k]
    rank = next((i + 1 for i, key in enumerate(top) if key in expected), None)
    return {'top1': int(bool(top) and top[0] in expected), 'mrr': 0 if rank is None else 1 / rank,
            'recall': len(set(top) & set(expected)) / len(expected)}


def summarize(rows):
    if not rows:
        return None
    return {metric: round(statistics.mean(r[metric] for r in rows), 4) for metric in ('top1', 'mrr', 'recall')}


def stripped(case):
    """Post-hoc arm (added after the first run): feature off, but the query text
    without the recognized time expression, separating query rewriting from ordering."""
    residual = temporal.interpret(case['query'], reference=case['reference'], timezone=case['timezone']).residual
    return dict(case, query=residual or case['query'])


def measure_split(conn, cfg, enabled, cases, keys, k):
    ranked, filters, unchanged, errors, controls, per_case = [], [], [], [], [], []
    forbidden = {'off': 0, 'on': 0}
    unknown_hits = 0
    latency = {'off': [], 'on': [], 'paired_delta': []}
    control_latency = {'off': [], 'on': [], 'paired_delta': []}
    for case in cases:
        mode = case['mode']
        config = enabled if mode == 'auto' else cfg
        off, on = run(conn, cfg, case, None, keys), run(conn, config, case, mode, keys)
        forbidden['off'] += len(set(case['forbidden']) & set(off['order']))
        forbidden['on'] += len(set(case['forbidden']) & set(on['order']))
        unknown_hits += sum(1 for h in on['hits'] if h.evidence.get('temporal', {}).get('basis') == 'unknown')
        row = {'id': case['id'], 'query': case['query'], 'mode': mode, 'expected': case['expected'],
               'off': off['order'], 'on': on['order'], 'error': on['error'],
               'interval': (on['report'] or {}).get('interval'), 'status': (on['report'] or {}).get('status'),
               'effect': (on['report'] or {}).get('effect')}
        if case['control']:
            row['identical'] = (off['hits'], off['warnings']) == (on['hits'], on['warnings'])
            controls.append(row['identical'])
        elif case['expect'] == 'error':
            row['failed_closed'] = on['error'] == 'temporal_filter_requires_interval'
            errors.append(row['failed_closed'])
        elif case['expect'] == 'unchanged':
            row['unchanged'] = [h.chunk_id for h in off['hits']] == [h.chunk_id for h in on['hits']]
            unchanged.append(row['unchanged'])
        elif case['expect'] == 'empty':
            row['empty'] = on['order'] == []
            filters.append({'exact': row['empty'], 'precision': 1.0 if row['empty'] else 0.0, 'case': case['id']})
        else:
            plain = run(conn, cfg, stripped(case), None, keys)
            row['off_stripped'] = plain['order']
            if mode == 'filter':
                inside = [h.evidence['temporal']['match'] == 'inside' for h in on['hits']]
                row['exact'] = set(on['order']) == set(case['expected'])
                filters.append({'exact': row['exact'], 'case': case['id'],
                                'precision': (sum(inside) / len(inside)) if inside else 0.0})
            ranked.append({'id': case['id'], 'off': quality(off['order'], case['expected'], k),
                           'off_stripped': quality(plain['order'], case['expected'], k),
                           'on': quality(on['order'], case['expected'], k)})
        per_case.append(row)
        if on['error'] is None:
            target = control_latency if case['control'] else latency
            for _ in range(WARMUP):
                run(conn, cfg, case, None, keys), run(conn, config, case, mode, keys)
            for i in range(REPEATS):
                # Alternate the order of each pair to cancel cache/drift effects.
                first, second = ((None, cfg), (mode, config)) if i % 2 == 0 else ((mode, config), (None, cfg))
                a = run(conn, first[1], case, first[0], keys)['ms']
                b = run(conn, second[1], case, second[0], keys)['ms']
                off_ms, on_ms = (a, b) if first[0] is None else (b, a)
                target['off'].append(off_ms)
                target['on'].append(on_ms)
                target['paired_delta'].append(on_ms - off_ms)
    def stats(values):
        return None if not values else {'samples': len(values), 'median_ms': round(statistics.median(values), 3),
                                        'p95_ms': round(percentile(values, .95), 3)}
    return {
        'quality_cases': len(ranked),
        'feature_off': summarize([r['off'] for r in ranked]),
        'feature_off_time_words_removed': summarize([r['off_stripped'] for r in ranked]),
        'feature_on': summarize([r['on'] for r in ranked]),
        'improved_top1': sum(r['on']['top1'] > r['off']['top1'] for r in ranked),
        'worse_top1': sum(r['on']['top1'] < r['off']['top1'] for r in ranked),
        'unchanged_top1': sum(r['on']['top1'] == r['off']['top1'] for r in ranked),
        'ordering_only_improved_top1': sum(r['on']['top1'] > r['off_stripped']['top1'] for r in ranked),
        'ordering_only_worse_top1': sum(r['on']['top1'] < r['off_stripped']['top1'] for r in ranked),
        'zero_candidate_cases': [r['id'] for r in per_case if not r['off'] and not r['on'] and r['expected']],
        'filter_cases': len(filters), 'filter_exact': sum(f['exact'] for f in filters),
        'filter_precision_mean': round(statistics.mean(f['precision'] for f in filters), 4) if filters else None,
        'ambiguous_soft_unchanged': f'{sum(unchanged)}/{len(unchanged)}',
        'hard_failed_closed': f'{sum(errors)}/{len(errors)}',
        'no_intent_controls_identical': f'{sum(controls)}/{len(controls)}',
        'forbidden_returned': forbidden, 'unknown_basis_hits_returned_on': unknown_hits,
        'latency_temporal_cases': {k2: stats(v) for k2, v in latency.items()},
        'latency_no_intent_controls': {k2: stats(v) for k2, v in control_latency.items()},
        'per_case_quality': ranked, 'cases': per_case,
    }


def main():
    started = time.time()
    parser_cases = fixture.load('parser-cases.json')
    cases = fixture.load('ranking-cases.json')
    base = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    store.try_embed_texts = search.try_embed_texts = lambda *a: None  # lexical only, disclosed
    with isolated_database(base) as cfg:
        with db.connect(cfg) as conn:
            seed_defaults(conn)
            conn.commit()
            keys = fixture.ingest(conn, cfg)
            version = conn.execute('SHOW server_version').fetchone()['server_version']
            migrations = conn.execute('SELECT max(filename) m FROM schema_migrations').fetchone()['m']
        enabled = replace(cfg, temporal_enabled=True)
        reader = db.connect(cfg, role='reader')
        try:
            ranking = {split: measure_split(reader, cfg, enabled, cases[split], keys, cases['parameters']['k'])
                       for split in ('dev', 'heldout')}
        finally:
            reader.close()
    result = {
        'work': 'RAG-064', 'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain', '--', 'agentic_rag'],
                                                   text=True).strip()),
        'fixtures': fixture.FROZEN, 'python': platform.python_version(), 'postgresql': version,
        'schema_head': migrations, 'parameters': cases['parameters'], 'repeats': REPEATS, 'warmup': WARMUP,
        'parser': {split: parser_quality(parser_cases[split]) for split in ('dev', 'heldout')},
        'ranking': ranking, 'elapsed_seconds': round(time.time() - started, 1),
        'limits': ('Synthetic 36-document corpus, lexical full-text retrieval only (no embeddings, no neural '
                   'reranker, no provider call); candidate-limited preference/filter over at most 150 retrieval '
                   'candidates; single local PostgreSQL in-process reader; not a production or private-corpus '
                   'quality claim.'),
    }
    print(json.dumps(result, indent=1, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
