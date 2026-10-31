"""RAG-063 before/after measurement on disposable synthetic databases only.

Runs one scenario against the actual 0.6.15 code (git archive of the base commit,
schema028) and against the working tree (schema029). Usage, from the repository
root with an owned local PostgreSQL and TMPDIR set:

    python docs/benchmarks/2026-10-31-source-evidence/measure.py > results.json

No provider, model or network call is made; embeddings are disabled.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, os.getcwd())
from agentic_rag import db
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config

BASE = '5390a6f6b4a7cce4b27abc9b51226acf2dac6223'
HOST_PATH = '/home/synthetic/.claude/projects/p/transcript.jsonl'

SCENARIO = r'''
import json, sys
from agentic_rag.config import load_config
from agentic_rag import db, store, evidence, thematic, domains
mode = sys.argv[1]
cfg = load_config()
store.try_embed_texts = lambda *a, **k: None
if mode == 'after':
    from agentic_rag import evidence_contract as contract
out = {'mode': mode}
PROJECT = '/synthetic/measure'
HOST_PATH = '/home/synthetic/.claude/projects/p/transcript.jsonl'
def src(sid, quote, ns='session:measure', role='user'):
    return {'namespace': ns, 'source_id': sid, 'role': role, 'quote': quote, 'complete': True,
            'timestamp': '2026-01-01T00:00:00Z'}
def claim(body, *sources, kind='inference'):
    return store.save_claim(conn, cfg, title=body[:40], body=body, domain='general', dtype='memory',
                            project=PROJECT, claim_kind=kind, evidence=list(sources))
def keys(doc):
    return [s['source_key'] for s in evidence.sources(conn, doc)]
def counts():
    history = conn.execute("SELECT to_regclass('public.claim_history') IS NOT NULL ok").fetchone()['ok']
    return conn.execute('SELECT (SELECT count(*) FROM audit_log) a' + (',(SELECT count(*) FROM claim_history) h' if history else ',0 h')).fetchone()
with db.connect(cfg) as conn:
    domains.seed_defaults(conn); domains.add_domain(conn, 'programming'); conn.commit()
    # E1: a confirmation decided on evidence that changed after inspection.
    trials = {'committed': 0, 'conflict': 0, 'rows_added_by_rejected': 0, 'n': 0}
    for kind in ('attach', 'withdraw_reinstate', 'legacy_review_cycle', 'second_source_refuted'):
        for i in range(10):
            body = f'Measured claim {kind} {i}'
            one = claim(body, src(f'{kind}-{i}-a', body), src(f'{kind}-{i}-b', body + ' (second)'))
            inspected = contract.inspect(conn, one.doc_id)['version'] if mode == 'after' else None
            if kind == 'attach':
                claim(body, src(f'{kind}-{i}-c', body + ' (late)'))
            elif kind == 'withdraw_reinstate':
                key = keys(one.doc_id)[0]
                store.set_source_state(conn, key, state='removed', reason='withdrawn')
                store.set_source_state(conn, key, state='active', reason='reinstated')
            elif kind == 'legacy_review_cycle':
                evidence.review(conn, one.doc_id, state='refuted', reason='other operator')
                evidence.review(conn, one.doc_id, state='unreviewed', reason='other operator again')
            else:
                store.set_source_state(conn, keys(one.doc_id)[1], state='refuted', reason='second source corrected')
            before = counts()
            trials['n'] += 1
            try:
                if mode == 'after':
                    evidence.review(conn, one.doc_id, state='confirmed', reason='stale decision', expected_version=inspected)
                else:
                    evidence.review(conn, one.doc_id, state='confirmed', reason='stale decision')
                trials['committed'] += 1
            except Exception as exc:
                assert type(exc).__name__ == 'EvidenceConflict', exc
                trials['conflict'] += 1
                after = counts()
                trials['rows_added_by_rejected'] += (after['a'] - before['a']) + (after['h'] - before['h'])
    out['stale_decisions'] = trials
    # E2: one inspection response for a claim with 48 spans whose sessions are host paths.
    body = 'Measured payload claim'
    for batch in range(6):
        doc = claim(body, *[src(f'p-{batch}-{n}', f'{body} quote {batch}-{n} ' + 'x' * 300, ns='session:' + HOST_PATH)
                            for n in range(8)], kind='stated').doc_id
    if mode == 'before':
        sources = store.get_document(conn, doc)['claim_sources']
        payload = json.dumps(sources, default=str)
        out['inspection'] = {'spans_total': len(sources), 'spans_in_first_response': len(sources),
                             'first_response_bytes': len(payload.encode()), 'host_path_occurrences': payload.count(HOST_PATH),
                             'responses_to_see_all': 1}
    else:
        page = contract.inspect(conn, doc)
        payload = json.dumps(page, default=str)
        pages, cursor, seen, occurrences = 0, None, 0, 0
        while True:
            current = contract.inspect(conn, doc, cursor=cursor)
            pages += 1; seen += len(current['sources']['items'])
            occurrences += json.dumps(current, default=str).count(HOST_PATH)
            cursor = current['sources']['next_cursor']
            if not cursor:
                break
        out['inspection'] = {'spans_total': page['sources']['total'], 'spans_in_first_response': len(page['sources']['items']),
                             'first_response_bytes': len(payload.encode()), 'host_path_occurrences': occurrences,
                             'responses_to_see_all': pages, 'spans_seen_across_pages': seen}
    # E3: history labels for a value replaced only in another domain.
    labels = {'n': 0, 'wrongly_superseded': 0}
    for i in range(5):
        entity = f'measured-service-{i}'
        old = store.save_assertion(conn, cfg, entity=entity, attribute='port', value=str(7000 + i), domain='general',
            event_at='2026-01-01T00:00:00Z', project=PROJECT,
            evidence={'source_id': f'g-{i}', 'role': 'user', 'quote': f'{entity} port {7000 + i}'})
        store.save_assertion(conn, cfg, entity=entity, attribute='port', value=str(8000 + i), domain='programming',
            event_at='2026-02-01T00:00:00Z', relation='replacement', project=PROJECT,
            evidence={'source_id': f'p-{i}', 'role': 'user', 'quote': f'{entity} port {8000 + i}'})
        store.refresh_summaries(conn, cfg, f'{entity} port', project=PROJECT, history=True)
        packet = thematic.read(conn, cfg, f'{entity} port', project=PROJECT, history=True)
        label = {e['document_id']: e['temporal_status'] for e in packet['entries']}.get(old.doc_id)
        current = conn.execute('SELECT assertion_eligible(%s) ok', (old.doc_id,)).fetchone()['ok']
        assert current, 'canonical predicate keeps the general-domain value current'
        labels['n'] += 1
        labels['wrongly_superseded'] += label == 'historical_superseded'
    out['cross_domain_history_labels'] = labels
print(json.dumps(out))
'''


def tree(directory):
    archive = Path(directory) / 'base.tar'
    with archive.open('wb') as stream:
        subprocess.run(['git', 'archive', BASE, 'agentic_rag', 'sql'], stdout=stream, check=True)
    root = Path(directory) / 'base'
    root.mkdir()
    with tarfile.open(archive) as content:
        content.extractall(root, filter='data')
    archive.unlink()
    return root


def run(root, cfg, mode, directory):
    config = Path(directory) / (mode + '.toml')
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n')
    env = {**os.environ, 'PYTHONPATH': str(root), 'AGENTIC_RAG_CONFIG': str(config), 'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-c', SCENARIO, mode], cwd=root, env=env, text=True,
                            capture_output=True, timeout=600)
    if result.returncode:
        raise SystemExit(result.stderr[-3000:])
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    results = {'feature': 'RAG-063', 'base_commit': BASE,
               'candidate_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'candidate_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
               'limits': 'Synthetic data on owned disposable PostgreSQL17; local SQL gateway, no service/network/'
                         'provider/model; counts, not latency claims.'}
    with tempfile.TemporaryDirectory(prefix='rag063-measure-', dir=os.environ.get('TMPDIR')) as directory:
        base = tree(directory)
        with isolated_database(cfg, initialize=False) as before:
            with db.connect(before) as conn:
                db.apply_migrations(conn, base / 'sql')
            results['before'] = run(base, before, 'before', directory)
        with isolated_database(cfg) as after:
            results['after'] = run(Path(os.getcwd()), after, 'after', directory)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
