"""RAG-065 frozen-fixture evaluation of opt-in pattern synthesis.

Runs the real preview, scheduler, existing worker drain, validation, audited
application and guarded reads on an owned, automatically dropped PostgreSQL
database. The structured-provider boundary is replaced by the frozen scripted
responses (fixtures/responses.json): this measures the pipeline's handling of
honest and adversarial model output, NOT the quality of any real model.

Usage (owned local PostgreSQL only; never a live store):
    env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
        .venv/bin/python docs/benchmarks/2026-10-31-pattern-synthesis/measure.py \
        --repetitions 3 --output docs/benchmarks/2026-10-31-pattern-synthesis/results.json
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path

from agentic_rag import db, llm, store, synthesis, worker
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.domains import seed_defaults

ROOT = Path(__file__).resolve().parents[3]


def _ms(start):
    return round((time.perf_counter() - start) * 1000, 1)


def _counts(conn):
    row = conn.execute("""SELECT (SELECT count(*) FROM synthesis_patterns) patterns,
        (SELECT COALESCE(sum(jsonb_array_length(parts)),0) FROM synthesis_patterns) parts,
        (SELECT count(*) FROM synthesis_dependencies) dependencies,
        (SELECT count(*) FROM audit_log WHERE op='synthesis_apply') audits""").fetchone()
    conn.commit()
    return dict(row)


def _last_run(conn, project):
    row = conn.execute('SELECT state,code,usage,result FROM synthesis_runs WHERE project_scope=%s'
                       ' ORDER BY created_at DESC LIMIT 1', (project,)).fetchone()
    conn.commit()
    return row


def evaluate(cfg, variant):
    """One owned database per variant group; cases run one after another."""
    labels = fx.cases()
    rows, examples = [], {}
    with isolated_database(cfg) as owned:
        on = replace(owned, synthesis_enabled=True)
        with db.connect(on) as conn:
            seed_defaults(conn)
            conn.commit()
            for case, label in sorted(labels.items()):
                if variant not in label:
                    continue
                project = fx.project(case)
                expected = label[variant]
                provider = fx.ScriptedProvider(case, variant) if variant != 'worker' else fx.ForbiddenProvider()
                fx.ForbiddenProvider.calls = 0
                llm.run_structured = provider
                before = _counts(conn)
                record = {'case': case, 'split': label['split'], 'variant': variant, 'expected': expected}
                if variant == 'worker' or not label['preview']['sufficient']:
                    fx.ingest(conn, on, {case})
                    policy = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='measure',
                                                        project=project)
                    started = time.perf_counter()
                    view = synthesis.preview(conn, on, domain='general', project=project)
                    record['preview_ms'] = _ms(started)
                    if variant != 'worker':
                        # Below the floor no provider is called; measure the validator
                        # on the frozen over-claiming answer instead.
                        selection = synthesis.candidates(conn, 'general', project)
                        offered = synthesis.offered(selection)
                        response = fx.resolve(provider.template, [{'id': i, 'quote': c['quote']}
                                                                  for i, c in offered.items()])
                        started = time.perf_counter()
                        outcome = synthesis.validate(response, offered)
                        record['validate_ms'] = _ms(started)
                        record['actual'] = {'outcome': 'non_conclusion', 'reason': outcome['rejected'][0]['code'],
                                            'applied': 0, 'provider_calls': 0, 'path': 'validator'}
                        conn.commit()
                    else:
                        end = datetime.fromisoformat(policy['forward_from'])
                        store.request_synthesis_backfill(conn, on, domain='general', project=project, reason='measure',
                                                         start=(end - timedelta(days=1)).isoformat(),
                                                         end=policy['forward_from'])
                        started = time.perf_counter()
                        synthesis.schedule(conn, on)
                        record['schedule_ms'] = _ms(started)
                        started = time.perf_counter()
                        worker.drain(conn, on)
                        record['drain_ms'] = _ms(started)
                        run = _last_run(conn, project)
                        record['actual'] = {'outcome': run['state'], 'reason': run['code'], 'applied': 0,
                                            'provider_calls': fx.ForbiddenProvider.calls, 'path': 'backfill'}
                else:
                    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='measure',
                                               project=project)
                    fx.ingest(conn, on, {case})
                    started = time.perf_counter()
                    view = synthesis.preview(conn, on, domain='general', project=project)
                    record['preview_ms'] = _ms(started)
                    started = time.perf_counter()
                    synthesis.schedule(conn, on)
                    record['schedule_ms'] = _ms(started)
                    started = time.perf_counter()
                    worker.drain(conn, on)
                    record['drain_ms'] = _ms(started)
                    run = _last_run(conn, project)
                    after = _counts(conn)
                    record['actual'] = {'outcome': run['state'], 'reason': run['code'],
                                        'applied': after['patterns'] - before['patterns'],
                                        'provider_calls': len(provider.calls), 'path': 'forward',
                                        'supported_parts': after['parts'] - before['parts'],
                                        'rejected_suggestions': len((run['result'] or {}).get('rejected', [])),
                                        'input_chars': (run['usage'] or {}).get('input_chars')}
                    if run['state'] == 'applied':
                        pattern = (run['result'] or {})['patterns'][0]
                        started = time.perf_counter()
                        shown = synthesis.inspect(conn, pattern)
                        record['inspect_ms'] = _ms(started)
                        record['actual']['cited_events'] = shown['support']['events']
                        record['actual']['cited_memories'] = shown['support']['memories']
                        examples.setdefault(f'{case}-{variant}', json.loads(json.dumps(shown, default=str)))
                        conn.commit()
                    elif case in ('C1', 'I1'):
                        examples.setdefault(f'{case}-{variant}', {'state': run['state'], 'code': run['code'],
                                                                   'result': run['result']})
                record['preview'] = {'eligible_memories': view['candidates']['memories'],
                                     'independent_events': view['candidates']['independent_events'],
                                     'sufficient': view['candidates']['sufficient'],
                                     'excluded': {k: v for k, v in view['excluded'].items() if v}}
                conn.commit()
                checks = [record['preview'] == label['preview'],
                          record['actual']['outcome'] == expected['outcome'],
                          record['actual']['applied'] == expected['applied'],
                          record['actual']['provider_calls'] == expected['provider_calls']]
                if expected['outcome'] != 'applied':
                    checks.append(record['actual']['reason'] == expected['reason'])
                for key in ('supported_parts', 'cited_events', 'cited_memories'):
                    if key in expected:
                        checks.append(record['actual'].get(key) == expected[key])
                record['matches_label'] = all(checks)
                rows.append(record)
    return rows, examples


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    synthesis.SETTLE_SECONDS = 0  # fixture rows are ingested immediately before scheduling
    store.try_embed_texts = lambda *a, **k: None  # no embedding model; queued retries are irrelevant here
    real = llm.run_structured
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    repetitions, examples = [], {}
    started = time.perf_counter()
    try:
        for _ in range(args.repetitions):
            rows = []
            for variant in ('worker', 'oracle', 'adversarial'):
                found, sample = evaluate(cfg, variant)
                rows.extend(found)
                for key, value in sample.items():
                    examples.setdefault(key, value)
            repetitions.append(rows)
    finally:
        llm.run_structured = real
    first = repetitions[0]
    stable = all([{k: r[k] for k in ('case', 'variant', 'actual', 'preview')} for r in rows] ==
                 [{k: r[k] for k in ('case', 'variant', 'actual', 'preview')} for r in first] for rows in repetitions)
    timing = {}
    for key in ('preview_ms', 'schedule_ms', 'drain_ms', 'inspect_ms', 'validate_ms'):
        values = [r[key] for rows in repetitions for r in rows if key in r]
        if values:
            timing[key] = {'n': len(values), 'median': round(statistics.median(values), 1), 'max': max(values)}
    summary = {
        'cases': len({r['case'] for r in first}), 'evaluations': len(first),
        'dev_evaluations': sum(r['split'] == 'dev' for r in first),
        'held_out_evaluations': sum(r['split'] == 'held_out' for r in first),
        'matches_label': sum(r['matches_label'] for r in first),
        'mismatches': [f"{r['case']}-{r['variant']}" for r in first if not r['matches_label']],
        'applied_patterns': sum(r['actual']['applied'] for r in first),
        'supported_parts': sum(r['actual'].get('supported_parts', 0) for r in first),
        'rejected_suggestions': sum(r['actual'].get('rejected_suggestions', 0) for r in first)
                                + sum(r['actual'].get('path') == 'validator' for r in first),
        'non_conclusions': sum(r['actual']['outcome'] == 'non_conclusion' for r in first),
        'provider_calls': sum(r['actual']['provider_calls'] for r in first),
        'repetitions': args.repetitions, 'outcomes_identical_across_repetitions': stable,
        'wall_seconds': round(time.perf_counter() - started, 1),
    }
    result = {
        'source_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                          text=True).stdout.strip(),
        'fixtures': fx.FROZEN, 'provider': 'scripted (fixtures/responses.json); no real model',
        'environment': {'python': platform.python_version(), 'machine': platform.machine(),
                        'processor': _cpu(), 'postgresql': _pg(cfg)},
        'summary': summary, 'timing_ms': timing, 'evaluations': first, 'examples': examples,
    }
    text = json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + '\n')
    print(json.dumps(summary, indent=1))
    return 0 if not summary['mismatches'] and stable else 1


def _cpu():
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or 'unknown'


def _pg(cfg):
    with db.connect(replace(cfg, db_name='postgres')) as conn:
        return conn.execute('SHOW server_version').fetchone()['server_version']


if __name__ == '__main__':
    raise SystemExit(main())
