"""RAG-067 extraction-policy measurement on owned disposable databases.

Runs every frozen case through actual mining (transcript file, read_window, real
prompt, mock provider, unchanged grounding, enforcement, audited gateways) three
times, each repetition in a new owned PostgreSQL database that is dropped after
use. No model is called: the mock provider returns each case's predetermined
output, so the figures show enforcement, retry and replay, not model quality.

Usage: python docs/benchmarks/2026-11-01-extraction-policy/measure.py OUTPUT.json
"""
from __future__ import annotations

from dataclasses import replace
import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agentic_rag import domains, extraction_policy as ep, jobs, llm, mining, store, worker
from agentic_rag.benchmark import extraction_policy as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config

REPETITIONS = 3


def queued(conn, session):
    row = dict(conn.execute("SELECT id,kind,session_id,transcript_path,payload,last_uuid,attempts FROM mining_queue"
                            " WHERE session_id=%s ORDER BY id DESC LIMIT 1", (session,)).fetchone())
    conn.commit()
    return row


def admit(conn, cfg, case, tmp, session=None):
    session = session or case['session']
    path = fx.write_transcript(Path(tmp) / f'{session}.jsonl', case['events'])
    jobs.enqueue_mine(conn, cfg, session_id=session, transcript_path=path, project=case['project'])
    return queued(conn, session)


def process(conn, cfg, job, attempts=1):
    started = time.perf_counter()
    result = worker.process_job(conn, cfg, {**job, 'attempts': attempts})
    worker._complete(conn, job['id'], result)
    return result, round((time.perf_counter() - started) * 1000, 2)


def documents(conn, session):
    return {r['title']: r for r in conn.execute(
        "SELECT d.title,c.kind,(SELECT json_agg(e.quote ORDER BY e.quote) FROM claim_evidence e WHERE e.document_id=d.id) quotes,"
        " d.body,d.project_scope,d.domain FROM documents d JOIN claim_records c ON c.document_id=d.id"
        " WHERE d.provenance->>'session_id'=%s", (session,))}


def kept(conn, session):
    """Item counts per channel in the accepted batch (claim reuse cannot hide them)."""
    row = conn.execute("SELECT extraction FROM mining_batches WHERE session_id=%s", (session,)).fetchone()
    return {k: len(v) for k, v in row['extraction'].items() if isinstance(v, list) and v}


def checks(conn, case, label):
    docs = documents(conn, case['session'])
    out = {'retained': fx.retained(conn, case['session']),
           'rejected': (fx.batch_policy(conn, case['session']) or {}).get('rejected')}
    out['exact_quotes'] = all(docs[t]['quotes'] == [q] and any(q in e['text'] for e in case['events'])
                              for t, q in label.get('exact_quotes', {}).items())
    out['claim_kinds'] = all(docs[t]['kind'] == k for t, k in label.get('claim_kinds', {}).items())
    out['evidence_links'] = all(len(docs[t]['quotes'] or []) == n for t, n in label.get('evidence_links', {}).items())
    out['secret_absent'] = all(label.get('secret_absent', '\x00') not in json.dumps(d, default=str) for d in docs.values())
    out['foreign_writes'] = sum(1 for d in docs.values() if d['project_scope'] != case['project']
                                or d['domain'] not in ('programming', 'operations'))
    return out


def repetition(base):
    labels = fx.load('labels.json')['cases']
    results = {}
    with isolated_database(base) as cfg, tempfile.TemporaryDirectory() as tmp:
        from agentic_rag import db
        cfg = replace(cfg, ollama_url='http://127.0.0.1:1', mine_debounce_seconds=0)
        with db.connect(cfg) as conn:
            for name in ('programming', 'operations'):
                domains.add_domain(conn, name)
            for case_id in ('R1', 'L1', 'D1', 'S1'):
                case, label = fx.case(case_id), labels[case_id]
                policy_cfg = replace(cfg, mine_policy_file=fx.policy_path(case['policy']))
                job = admit(conn, policy_cfg, case, tmp)
                mock = fx.MockProvider(case['provider'], case['events'])
                mining.run_structured = mock
                _, ms = process(conn, policy_cfg, job)
                got = checks(conn, case, label)
                got.update(provider_calls=mock.calls, latency_ms=ms)
                got['matches_label'] = (got['retained'] == label['retained'] and got['rejected'] == label['rejected']
                                        and mock.calls == label['provider_calls'] and got['exact_quotes']
                                        and got['claim_kinds'] and got['evidence_links'] and got['secret_absent']
                                        and got['foreign_writes'] == 0)
                got['kept_with_policy'] = kept(conn, case['session'])
                # Before: the same case without a policy file (the unchanged 0.6.19 behavior).
                plain = admit(conn, cfg, case, tmp, session=case['session'] + '-builtin')
                mining.run_structured = fx.MockProvider(case['provider'], case['events'])
                process(conn, cfg, plain)
                got['kept_without_policy'] = kept(conn, case['session'] + '-builtin')
                results[case_id] = got
            # P1: admitted under A, provider outage, file replaced by B, retry, replay, new admission.
            case, label = fx.case('P1'), labels['P1']
            cfg_a = replace(cfg, mine_policy_file=fx.policy_path(case['policy']))
            cfg_b = replace(cfg, mine_policy_file=fx.policy_path(case['replacement_policy']))
            cfg_bad = replace(cfg, mine_policy_file=fx.policy_path(case['malformed_policy']))
            job = admit(conn, cfg_a, case, tmp)
            admitted = job['payload']['extraction_policy']['digest']
            mock = fx.MockProvider(case['provider'], case['events'])
            mining.run_structured = mock
            started = time.perf_counter()
            try:
                worker.process_job(conn, cfg_a, {**job, 'attempts': 1})
            except llm.LLMUnavailableError:
                conn.rollback()
            failed_ms = round((time.perf_counter() - started) * 1000, 2)
            reads = []
            real_load = ep.load_file
            ep.load_file = lambda *a, **k: reads.append(1) or real_load(*a, **k)
            _, retry_ms = process(conn, cfg_bad, job, attempts=2)
            ep.load_file = real_load
            accepted_calls = mock.calls
            replay = fx.MockProvider([], case['events'])
            mining.run_structured = replay
            started = time.perf_counter()
            worker.process_job(conn, cfg_b, {**job, 'attempts': 3})
            replay_ms = round((time.perf_counter() - started) * 1000, 2)
            retry_policy = fx.batch_policy(conn, case['session'])
            new = admit(conn, cfg_b, case, tmp, session=case['new_session'])
            mining.run_structured = fx.MockProvider([case['provider'][1]], case['events'])
            process(conn, cfg_b, new)
            new_policy = fx.batch_policy(conn, case['new_session'])
            before = conn.execute('SELECT count(*) n FROM mining_queue').fetchone()['n']
            try:
                jobs.enqueue_mine(conn, cfg_bad, session_id='rag067-p1-malformed', transcript_path=str(Path(tmp) / 'x.jsonl'),
                                  project=case['project'])
                malformed_admitted = True
            except ep.PolicyError:
                malformed_admitted = False
            added = conn.execute('SELECT count(*) n FROM mining_queue').fetchone()['n'] - before
            results['P1'] = {
                'provider_calls_until_accepted': accepted_calls, 'provider_calls_on_replay': replay.calls,
                'retry_digest_equals_admission': retry_policy['digest'] == admitted,
                'retry_read_policy_file': bool(reads),
                'retained_on_retry': fx.retained(conn, case['session']),
                'new_admission_digest_differs': new_policy['digest'] != admitted,
                'new_admission_rejected': new_policy['rejected'],
                'malformed_admitted': malformed_admitted, 'malformed_queue_rows_added': added,
                'latency_ms': {'failed_attempt': failed_ms, 'retry': retry_ms, 'replay': replay_ms}}
            results['P1']['matches_label'] = (
                accepted_calls == label['provider_calls_until_accepted'] and replay.calls == 0
                and results['P1']['retry_digest_equals_admission'] and not reads
                and results['P1']['retained_on_retry'] == label['retained_on_retry']
                and results['P1']['new_admission_digest_differs']
                and new_policy['rejected'] == label['new_admission_after_replacement']['rejected']
                and not malformed_admitted and added == 0)
            # Z1: every category disabled.
            case, label = fx.case('Z1'), labels['Z1']
            cfg_z = replace(cfg, mine_policy_file=fx.policy_path(case['policy']))
            job = admit(conn, cfg_z, case, tmp)
            mock = fx.MockProvider([], case['events'])
            mining.run_structured = mock
            result, ms = process(conn, cfg_z, job)
            results['Z1'] = {'provider_calls': mock.calls, 'skipped': result.skipped, 'saved': result.saved,
                             'cursor_advanced': result.new_last_uuid is not None, 'latency_ms': ms}
            results['Z1']['matches_label'] = (mock.calls == 0 and result.skipped == label['skip_reason']
                                              and result.saved == 0 and results['Z1']['cursor_advanced'])
            # V1: malformed file.
            case, label = fx.case('V1'), labels['V1']
            try:
                ep.load_file(fx.policy_path(case['policy']))
                errors = []
            except ep.PolicyError as error:
                errors = error.errors
            results['V1'] = {'errors': errors, 'matches_label': errors == label['errors']}
            results['_totals'] = {
                'bindings': conn.execute('SELECT count(*) n FROM extraction_policy_bindings').fetchone()['n'],
                'bind_audits': conn.execute("SELECT count(*) n FROM audit_log WHERE op='extraction_policy_bind'").fetchone()['n']}
    return results


def main(output):
    store.try_embed_texts = lambda *a, **k: None
    original = mining.run_structured
    base = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    runs = []
    try:
        for _ in range(REPETITIONS):
            runs.append(repetition(base))
    finally:
        mining.run_structured = original

    def outcome(run):
        return {k: {kk: vv for kk, vv in v.items() if kk != 'latency_ms'} for k, v in run.items()}
    revision = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--', 'agentic_rag', 'sql'], capture_output=True, text=True).stdout.strip())
    latencies = {}
    for run in runs:
        for case_id, value in run.items():
            if isinstance(value.get('latency_ms'), (int, float)):
                latencies.setdefault(case_id, []).append(value['latency_ms'])
            elif isinstance(value.get('latency_ms'), dict):
                for step, ms in value['latency_ms'].items():
                    latencies.setdefault(f'{case_id}.{step}', []).append(ms)
    report = {
        'format': 1, 'source_revision': revision, 'product_tree_dirty': dirty, 'package': '0.6.20', 'schema': 32,
        'python': platform.python_version(), 'repetitions': REPETITIONS, 'provider': 'mock (predetermined output)',
        'deterministic_outcomes_identical': all(outcome(r) == outcome(runs[0]) for r in runs),
        'all_labels_matched': all(v.get('matches_label', True) for r in runs for k, v in r.items() if k != '_totals'),
        'latency_ms': {k: {'min': min(v), 'max': max(v), 'values': v} for k, v in sorted(latencies.items())},
        'runs': runs,
    }
    Path(output).write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n')
    print(json.dumps({k: report[k] for k in ('source_revision', 'deterministic_outcomes_identical', 'all_labels_matched')}))
    return 0 if report['all_labels_matched'] and report['deterministic_outcomes_identical'] else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
