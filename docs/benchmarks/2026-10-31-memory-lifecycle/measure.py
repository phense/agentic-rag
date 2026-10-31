"""RAG-066 frozen-fixture measurement of source-preserving lifecycle decisions.

Runs the real gateways, preview, apply/correct, the SQL view predicate, lexical
retrieval and automatic curation on owned, automatically dropped PostgreSQL
databases. The 0.6.18 curation figures come from the actual 0.6.18 code (git
archive of main d4d2372) run in a subprocess against the same ingested corpus.
No model or provider is called: the semantic labels are the author's hand
judgement, so this measures the deterministic policy and plumbing, NOT semantic
accuracy and NOT real-model quality.

Usage (owned local PostgreSQL only; every database is created and dropped here):
    env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
        .venv/bin/python docs/benchmarks/2026-10-31-memory-lifecycle/measure.py \
        --repetitions 3 --output docs/benchmarks/2026-10-31-memory-lifecycle/results.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import psycopg

from agentic_rag import curation, db, lifecycle, llm, search, store
from agentic_rag.benchmark import memory_lifecycle as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config

ROOT = Path(__file__).resolve().parents[3]
OLD_SOURCE = 'd4d2372'
PROJECT = fx.project('a')
SAME = {'same_knowledge', 'same_knowledge_different_type'}
ORIGINAL_TABLES = ('documents', 'chunks', 'claim_records', 'claim_evidence', 'knowledge_sources', 'edges', 'pins',
                   'fact_assertions', 'assertion_sources', 'source_revisions', 'claim_revisions')
# One query per case whose decision hides documents; the listed keys are the hidden members.
QUERIES = {'E1': ('flush the DNS cache', ['E1-copy']), 'M1': ('release wheel changelog', ['M1-copy1', 'M1-copy2']),
           'R1': ('printer toner', ['R1-short']), 'P1': ('wiki backups', ['P1-old']),
           'P2': ('mail relay', ['P2-older-late']), 'D1': ('plotter paper', ['D1-copy']),
           'X1': ('disk alerts ops channel', ['X1-short'])}
APPLIES = ('E1', 'R1', 'P1', 'P2', 'C1', 'X1', 'D1', 'G1')
EXAMPLES = ('E1-copy', 'P1-old', 'C1-a')
OLD_CURATION = r'''
import json
from agentic_rag.config import load_config
from agentic_rag import db, curation
cfg = load_config()
with db.connect(cfg, role='writer') as conn:
    curation.run_pass(conn, cfg, runner=None)
    print(json.dumps(sorted(str(r['id']) for r in conn.execute("SELECT id FROM documents WHERE status='archived'"))))
'''
LABELS = fx.load('labels.json')
CASES = LABELS['cases']
PROVIDER_CALLS = []


def _provider(*args, **kwargs):
    PROVIDER_CALLS.append(1)
    raise RuntimeError('the measurement expects no provider call')


def _ms(started):
    return round((time.perf_counter() - started) * 1000, 2)


def _summary(samples):
    return {'n': len(samples), 'median_ms': round(statistics.median(samples), 2), 'max_ms': round(max(samples), 2)}


def _rows(conn):
    out = {t: conn.execute(f"SELECT md5(COALESCE(string_agg(md5(to_jsonb(x)::text),',' ORDER BY md5(to_jsonb(x)::text)),''))"
                           f" h FROM {t} x").fetchone()['h'] for t in ORIGINAL_TABLES}
    conn.rollback()
    return out


def _ev1(conn):
    out = {str(r['id']): r['v'] for r in conn.execute('SELECT id, rag_document_version(id) v FROM documents')}
    conn.rollback()
    return out


def _counts(conn):
    out = dict(conn.execute("SELECT (SELECT count(*) FROM lifecycle_decisions) decisions,"
                            " (SELECT count(*) FROM lifecycle_events) events,"
                            " (SELECT count(*) FROM audit_log WHERE op LIKE 'lifecycle%%') audit,"
                            " (SELECT count(*) FROM lifecycle_decisions WHERE state='active') active").fetchone())
    conn.rollback()
    return out


def _case(key):
    return next(d['case'] for d in fx.documents() if d['key'] == key)


def _named(value, ids):
    text = json.dumps(value, default=str)
    for key, doc_id in ids.items():
        text = text.replace(doc_id, key)
    return json.loads(text)


def preview(cfg, ids, member, target, operation=None):
    with db.connect(cfg, role='reader') as reader:
        return lifecycle.preview(reader, ids[member], ids[target], operation=operation)


def apply(cfg, ids, member, target, operation, *, reason='measurement', seen=None, request_key=None, role='writer'):
    with db.connect(cfg, role=role) as c:
        seen = seen or lifecycle.preview(c, ids[member], ids[target], operation=operation)
        c.rollback()
        return store.apply_lifecycle(c, cfg, member=ids[member], target=ids[target], operation=operation,
                                     expected_member_version=seen['member']['version'],
                                     expected_target_version=seen['target']['version'], reason=reason,
                                     reviewed=operation not in ('exact_duplicate', 'contradiction'),
                                     request_key=request_key, actor='cli')


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except lifecycle.LifecycleError as error:
        return error.code
    return 'ok'


def selected(conn, ids, keys, view):
    names = {v: k for k, v in ids.items()}
    with lifecycle.view_scope(conn, view):
        rows = conn.execute('SELECT id::text AS id FROM documents WHERE id = ANY(%s::uuid[]) AND status=%s'
                            ' AND assertion_eligible(id)', ([ids[k] for k in keys if k in ids], 'active')).fetchall()
    conn.rollback()
    return sorted(names[r['id']] for r in rows)


def lexical(conn, cfg, query, k=8, **kw):
    hits, _ = search.search(conn, cfg, query, domain='general', k=k, project=PROJECT, strategy='lexical',
                            rerank_mode='off', context_mode='off', **kw)
    conn.rollback()
    return hits


def retrieval(conn, cfg, ids, **kw):
    names = {v: k for k, v in ids.items()}
    out = {}
    for case, (query, members) in QUERIES.items():
        hits = [names.get(h.document_id, h.document_id) for h in lexical(conn, cfg, query, **kw)]
        out[case] = {'top8': hits, 'members_in_top8': sorted(set(hits) & set(members))}
    return out


def timed_searches(conn, cfg, rounds=5):
    samples = []
    for _ in range(rounds):
        for query, _members in QUERIES.values():
            started = time.perf_counter()
            lexical(conn, cfg, query)
            samples.append(_ms(started))
    return _summary(samples)


def old_tree(scratch):
    root = scratch / 'old-0.6.18'
    root.mkdir()
    archive = scratch / 'old.tar'
    with archive.open('wb') as out:
        subprocess.run(['git', 'archive', OLD_SOURCE, 'agentic_rag', 'sql', 'pyproject.toml'], stdout=out, check=True, cwd=ROOT)
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    if 'version = "0.6.18"' not in (root / 'pyproject.toml').read_text():
        raise RuntimeError('old tree is not 0.6.18')
    return root


def run_old_curation(old, cfg, scratch):
    config = scratch / f'old-{cfg.db_name}.toml'
    budget = LABELS['automatic_curation']['budget']
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n\n[curation]\nbudget = {budget}\n')
    env = {**os.environ, 'PYTHONPATH': str(old), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', OLD_CURATION], cwd=old, env=env, text=True, capture_output=True,
                            timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def curation_run(cfg, policy, old, scratch):
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            ids = fx.ingest(conn, owned)
        started = time.perf_counter()
        if policy == '0.6.18':
            archived = run_old_curation(old, owned, scratch)
        else:
            with db.connect(owned) as conn:
                curation.run_pass(conn, owned, budget=LABELS['automatic_curation']['budget'], runner=None)
                archived = [str(r['id']) for r in conn.execute("SELECT id FROM documents WHERE status='archived'")]
                conn.commit()
        elapsed = _ms(started)
        with db.connect(owned) as conn:
            documents = conn.execute('SELECT count(*) n FROM documents').fetchone()['n']
    names = {v: k for k, v in ids.items()}
    keys = sorted(names[i] for i in archived)
    legit = sorted(c for c, v in CASES.items() if v['human'] in SAME and 'pair' in v)
    return {'archived': keys,
            'matches_label': keys == LABELS['automatic_curation']['policy_' + policy.replace('.', '_')]['archived'],
            'false_merges': [k for k in keys if CASES[_case(k)]['human'] not in SAME],
            'same_knowledge_pairs_left_for_review': [c for c in legit if CASES[c]['pair'][0] not in keys],
            'documents_after': documents, 'ms': elapsed}


def previews(cfg, ids):
    checks, samples = {}, []
    for case, label in CASES.items():
        if 'preview' not in label:
            continue
        started = time.perf_counter()
        try:
            got = preview(cfg, ids, *label['pair'], label['preview'].get('requested'))
            result = {'class': got['classification'], 'proof': got['proof']}
            wanted = {'class': label['preview']['class'], 'proof': label['preview']['proof']}
            checks[case + ':no_write_no_provider'] = got['writes'] == 0 and got['provider_calls'] == 0
        except lifecycle.LifecycleError as error:
            result, wanted = {'code': error.code}, {'code': label['preview']['code']}
        samples.append(_ms(started))
        checks[case] = result == wanted
    for case, key in (('E1', 'reverse'), ('T1', 'exact_request'), ('T2', 'exact_request'), ('T3', 'exact_request'),
                      ('P2', 'reverse'), ('P3', 'replacement'), ('P4', 'replacement'), ('P5', 'replacement')):
        pair = CASES[case]['pair'][::-1] if key == 'reverse' else CASES[case]['pair']
        requested = CASES[case][key].get('requested', 'replacement')
        got = preview(cfg, ids, *pair, requested)['operations'][requested]
        checks[f'{case}:{key}'] = not got['allowed'] and got['code'] == CASES[case][key]['code']
    return checks, samples


def transitions(conn, cfg, ids, applied):
    out = {}
    key = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s', (ids['X1-short'],)).fetchone()['source_key']
    store.set_source_state(conn, key, state='removed', reason='withdrawn')
    out['X1:source_withdrawn'] = selected(conn, ids, CASES['X1']['pair'], 'current') == CASES['X1']['source_withdrawn']['current']
    store.set_source_state(conn, key, state='active', reason='reinstated')
    out['X1:source_reinstated'] = selected(conn, ids, CASES['X1']['pair'], 'current') == CASES['X1']['source_reinstated']['current']
    out['X1:relationship_stale'] = lifecycle.detail(conn, ids['X1-short'])['as_member'][0]['relationship'] == 'stale'
    conn.rollback()
    for body in ('Plotter note under edit.', 'The plotter is loaded with A0 rolls.'):
        store.save_document(conn, cfg, doc_id=ids['D1-copy'], title='Plotter paper size', body=body,
                            domain='general', dtype='memory')
    conn.commit()
    out['D1:content_aba'] = selected(conn, ids, CASES['D1']['pair'], 'current') == CASES['D1']['content_aba']['current']
    store.save_document(conn, cfg, doc_id=ids['R1-rich'], title='Printer P1 toner and drum',
                        body='Printer P1 uses toner TN-243 and drum DR-243; replace the drum every 12000 pages.',
                        domain='general', dtype='memory', status='archived')
    conn.commit()
    out['R1:target_archived'] = selected(conn, ids, CASES['R1']['pair'], 'current') == CASES['R1']['target_archived']['current']
    store.review_claim(conn, ids['G1-new'], state='refuted', reason='wrong server')
    conn.execute('DELETE FROM documents WHERE id=%s', (ids['G1-new'],))
    conn.commit()
    purged = CASES['G1']['target_refuted_and_purged']
    out['G1:views'] = all(selected(conn, ids, CASES['G1']['pair'], v) == purged[v] for v in ('current', 'include_merged', 'historical'))
    detail = lifecycle.detail(conn, ids['G1-old'])
    conn.rollback()
    out['G1:detail_without_disclosure'] = (detail['as_member'][0]['resolution'] == purged['detail']
                                           and ids['G1-new'] not in json.dumps(detail, default=str))
    with db.connect(cfg) as w:
        store.correct_lifecycle(w, cfg, decision_id=applied['P1']['decision']['id'], expected_revision=1,
                                reason='measurement undo', actor='cli')
    out['P1:after_correction'] = selected(conn, ids, CASES['P1']['pair'], 'current') == CASES['P1']['after_correction']['current']
    return {'checks': len(out), 'matching': sum(out.values()), 'mismatches': sorted(k for k, v in out.items() if not v)}


def decisions(cfg):
    out = {}
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            out['postgres'] = conn.execute('SHOW server_version').fetchone()['server_version']
            started = time.perf_counter()
            ids = fx.ingest(conn, owned)
            out['ingest_ms'] = _ms(started)
            out['documents'] = len(set(ids.values()))
            names = {v: k for k, v in ids.items()}
            rows_before, ev1_before = _rows(conn), _ev1(conn)
            checks, preview_ms = previews(owned, ids)
            out['preview'] = {'checks': len(checks), 'matching': sum(checks.values()),
                              'mismatches': sorted(k for k, v in checks.items() if not v), 'latency': _summary(preview_ms)}
            out['retrieval_before'] = retrieval(conn, owned, ids)
            search_before = timed_searches(conn, owned)
            applied, apply_ms, checks = {}, [], {}
            for case in APPLIES:
                label = CASES[case]
                started = time.perf_counter()
                applied[case] = apply(owned, ids, *label['pair'], label['apply']['operation'])
                apply_ms.append(_ms(started))
                checks[case + ':state'] = applied[case]['decision']['state'] == label['apply']['state']
            for member, target in CASES['M1']['applies']:
                started = time.perf_counter()
                apply(owned, ids, member, target, 'exact_duplicate')
                apply_ms.append(_ms(started))
            for chain in CASES['M1']['chains']:
                checks['M1:chain:' + chain['member']] = code_of(
                    apply, owned, ids, chain['member'], chain['target'], chain['operation']) == chain['code']
            for case in ('E1', 'R1', 'P1', 'P2', 'C1', 'A1', 'Q1', 'M1'):
                keys = ['M1-canon', 'M1-copy1', 'M1-copy2', 'M1-copy3'] if case == 'M1' else CASES[case]['pair']
                for view, wanted in CASES[case]['views'].items():
                    checks[f'{case}:{view}'] = selected(conn, ids, keys, view) == wanted
            as_of = CASES['P1']['as_of']
            hits = lexical(conn, owned, 'Wiki backups', view='current', as_of=as_of['at'])
            checks['P1:as_of'] = sorted(names[h.document_id] for h in hits) == as_of['current']
            out['apply'] = {'counts': _counts(conn), 'latency': _summary(apply_ms)}
            out['views'] = {'checks': len(checks), 'matching': sum(checks.values()),
                            'mismatches': sorted(k for k, v in checks.items() if not v)}
            out['retrieval_after'] = {'omitted': retrieval(conn, owned, ids), 'current': retrieval(conn, owned, ids, view='current'),
                                      'include_merged': retrieval(conn, owned, ids, view='include_merged')}
            out['k1'] = {str(view or 'omitted'): names[lexical(conn, owned, CASES['E1']['query'], k=1, view=view)[0].document_id]
                         for view in (None, 'current', 'include_merged')}
            out['k1_expected_current'] = CASES['E1']['k1_current']
            out['search_latency'] = {'before_decisions': search_before, 'after_decisions': timed_searches(conn, owned)}
            out['source_retention'] = {'original_rows_unchanged': _rows(conn) == rows_before,
                                       'ev1_unchanged': _ev1(conn) == ev1_before, 'documents': len(ev1_before)}
            out['examples'] = {key: _named(lifecycle.detail(conn, ids[key]), ids) for key in EXAMPLES}
            conn.rollback()
            out['transitions'] = transitions(conn, owned, ids, applied)
            out['end_counts'] = _counts(conn)
    return out


def concurrency(cfg):
    out = {}
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            ids = fx.ingest(conn, owned)
        outcomes, barrier = [], threading.Barrier(2)

        def race(member, target):
            try:
                with db.connect(owned, role='writer') as c:
                    seen = lifecycle.preview(c, ids[member], ids[target], operation='semantic_duplicate')
                    c.rollback()
                    barrier.wait()
                    store.apply_lifecycle(c, owned, member=ids[member], target=ids[target], operation='semantic_duplicate',
                                          expected_member_version=seen['member']['version'],
                                          expected_target_version=seen['target']['version'], reason='race',
                                          reviewed=True, actor='cli')
                    outcomes.append('ok')
            except lifecycle.LifecycleError as error:
                outcomes.append(error.code)
        threads = [threading.Thread(target=race, args=p) for p in (('R2-p2', 'R2-p3'), ('R2-p3', 'R2-p2'))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with db.connect(owned) as conn:
            out['opposing_applies'] = {'outcomes': sorted(outcomes), **_counts(conn)}
            seen = preview(owned, ids, 'E1-copy', 'E1-keep')
            first = apply(owned, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', seen=seen, request_key='m-1')
            again = apply(owned, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', seen=seen, request_key='m-2')
            now = _counts(conn)
            out['replay_new_transport_id'] = {'same_decision': first['decision']['id'] == again['decision']['id'],
                                              'replayed': again['replayed'], 'decisions': now['decisions'] - 1,
                                              'events': now['events'] - 1}
            out['request_key_other_payload'] = code_of(apply, owned, ids, 'E1-copy', 'E1-keep', 'exact_duplicate',
                                                       seen=seen, reason='other reason', request_key='m-1')
            seen = preview(owned, ids, 'D1-copy', 'D1-keep')
            store.save_document(conn, owned, doc_id=ids['D1-copy'], title='Plotter paper size',
                                body='The plotter is loaded with A0 rolls.', domain='general', dtype='memory')
            conn.commit()
            out['edit_after_preview'] = code_of(apply, owned, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', seen=seen)
            seen = preview(owned, ids, 'D1-copy', 'D1-keep')
            made = apply(owned, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', seen=seen, reason='aba')
            store.correct_lifecycle(conn, owned, decision_id=made['decision']['id'], expected_revision=1, reason='undo', actor='cli')
            replay = apply(owned, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', seen=seen, reason='aba')
            out['replay_after_correction'] = {'state': replay['decision']['state'], 'replayed': replay['replayed'],
                                              'member_current': selected(conn, ids, ['D1-copy'], 'current') == ['D1-copy']}
            before = _counts(conn)
            real = lifecycle._audit

            def broken(*args, **kwargs):
                raise psycopg.errors.InsufficientPrivilege('injected audit failure')
            lifecycle._audit = broken
            try:
                apply(owned, ids, 'M1-copy1', 'M1-canon', 'exact_duplicate')
                out['injected_audit_failure'] = 'unexpected success'
            except psycopg.Error:
                after = _counts(conn)
                out['injected_audit_failure'] = {k: after[k] - before[k] for k in ('decisions', 'events', 'audit')}
            finally:
                lifecycle._audit = real
            try:
                apply(owned, ids, 'M1-copy1', 'M1-canon', 'exact_duplicate', role='reader')
                out['reader_role_apply'] = 'unexpected success'
            except (lifecycle.LifecycleError, psycopg.Error) as error:
                after = _counts(conn)
                out['reader_role_apply'] = {'error': getattr(error, 'code', type(error).__name__),
                                            **{k: after[k] - before[k] for k in ('decisions', 'events', 'audit')}}
    return out


def scale(cfg, pairs=300):
    """Worst case for the per-row check: one broad query whose matches are all merged members."""
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            fx.ingest(conn, owned)
            made = []
            for n in range(pairs):
                keep, copy = (store.save_document(conn, owned, title=f'Note {n}', body=f'Widget {n} needs gasket model G{n}.',
                                                  domain='general', dtype='memory', project=PROJECT).doc_id for _ in range(2))
                made.append((copy, keep))
            conn.commit()
            conn.execute('ANALYZE')
            conn.commit()

            def timed(query):
                samples = []
                for _ in range(7):
                    started = time.perf_counter()
                    hits = lexical(conn, owned, query)
                    samples.append(_ms(started))
                return {**_summary(samples), 'hits': len(hits)}
            before = {'broad': timed('widget gasket'), 'unrelated': timed('flush the DNS cache')}
            started = time.perf_counter()
            for copy, keep in made:
                seen = lifecycle.preview(conn, copy, keep)
                conn.rollback()
                store.apply_lifecycle(conn, owned, member=copy, target=keep, operation='exact_duplicate',
                                      expected_member_version=seen['member']['version'],
                                      expected_target_version=seen['target']['version'], reason='scale', actor='cli')
            applied_ms = _ms(started)
            conn.execute('ANALYZE')
            conn.commit()
            after = {'broad': timed('widget gasket'), 'unrelated': timed('flush the DNS cache')}
            hidden = conn.execute('SELECT count(*) n FROM documents WHERE rag_lifecycle_hidden(id)').fetchone()['n']
            conn.rollback()
    return {'pairs': pairs, 'hidden_members': hidden, 'apply_total_ms': applied_ms,
            'search_before_decisions': before, 'search_after_decisions': after}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items()
                if not (k.endswith('_ms') or k in ('ms', 'latency', 'search_latency', 'examples', 'broad', 'unrelated'))}
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
    llm.run_structured = _provider
    cfg = Config(ollama_url='http://127.0.0.1:1')
    runs = []
    with tempfile.TemporaryDirectory(prefix='rag066-measure-') as scratch:
        scratch = Path(scratch)
        old = old_tree(scratch)
        for _ in range(args.repetitions):
            started = time.perf_counter()
            run = {'curation_0.6.19': curation_run(cfg, '0.6.19', old, scratch),
                   'curation_0.6.18': curation_run(cfg, '0.6.18', old, scratch),
                   'decisions': decisions(cfg), 'concurrency': concurrency(cfg), 'scale': scale(cfg)}
            run['wall_ms'] = _ms(started)
            runs.append(run)
    output = {
        'feature': 'RAG-066 memory lifecycle (S1)', 'fixtures': fx.FROZEN,
        'source_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        'source_tree_clean': subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT,
                                            capture_output=True, text=True).stdout.strip() == '',
        'old_curation_source': OLD_SOURCE, 'python': platform.python_version(),
        'postgres': runs[0]['decisions']['postgres'], 'repetitions': len(runs), 'provider_calls': len(PROVIDER_CALLS),
        'deterministic_outcomes_identical': all(_strip(r) == _strip(runs[0]) for r in runs),
        'runs': runs,
        'limits': ['synthetic hand-labelled corpus (frozen fixtures); not a private or production corpus',
                   'semantic labels are the author judgement; no model quality or semantic accuracy is measured',
                   'lexical retrieval only; embeddings, rerankers and context indexing are disabled',
                   'old curation time includes starting a Python subprocess',
                   'the scale section is a synthetic worst case (every broad match is a merged member), not a usage profile',
                   'timings come from one shared host with a local PostgreSQL and vary between runs'],
    }
    text = json.dumps(output, indent=1, sort_keys=True, default=str)
    if args.output:
        args.output.write_text(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
