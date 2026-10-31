"""RAG-065 frozen synthetic pattern corpus, gateway ingestion and scripted provider.

Every row is written through the audited gateways. The scripted provider stands in
for the structured-provider boundary only: it reads the candidate list the
synthesis prompt offers and answers with a frozen response whose citations are
selected by quote text. It never sees private data and makes no network call.
Used by the tests and by docs/benchmarks/2026-10-31-pattern-synthesis/measure.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / 'docs/benchmarks/2026-10-31-pattern-synthesis/fixtures'
FROZEN = {
    'corpus.json': '8b2388177c94f0e912a6dea42018754f3dfc6bd6468bba6ec2d426e38d8d7081',
    'responses.json': '4cd4fb6b2c322d1d9afc6f35c6c4ae2d93b3d50c3bbcbb7621106190244afb76',
    'labels.json': 'd7fbcff3ad856c4a2d925d92d5554948ff0597ec9fa4bd6cbbc813aa88901dc4',
}


def load(name: str) -> dict:
    data = (FIXTURES / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != FROZEN[name]:
        raise ValueError('frozen fixture changed: ' + name)
    return json.loads(data)


def cases(split: str | None = None) -> dict:
    labels = load('labels.json')['cases']
    return {k: v for k, v in labels.items() if split is None or v['split'] == split}


def project(case: str) -> str:
    return next(d['project'] for d in load('corpus.json')['documents'] if d['case'] == case)


def ingest(conn, cfg, case_ids=None) -> dict[str, str]:
    """Write the selected fixture cases through the gateways; return key -> document id."""
    from .. import store
    corpus = load('corpus.json')
    keys = {}
    for d in corpus['documents']:
        if case_ids is not None and d['case'] not in case_ids:
            continue
        if d['kind'] == 'claim':
            evidence = [dict(namespace=s['namespace'], source_id=s['source_id'], role=s['role'], quote=s['quote'],
                             timestamp=s['timestamp'], complete=s['complete']) for s in d['sources']]
            saved = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain=corpus['domain'],
                                     dtype=d['dtype'], project=d['project'], claim_kind=d['claim_kind'],
                                     evidence=evidence, actor='cli')
        else:
            saved = store.save_document(conn, cfg, title=d['title'], body=d['body'], domain=corpus['domain'],
                                        dtype=d['dtype'], project=d['project'], actor='cli')
        keys[d['key']] = saved.doc_id
    conn.commit()
    return keys


def candidates_from_prompt(prompt: str) -> list[dict]:
    from ..synthesis import CANDIDATES_MARKER
    return json.loads(prompt.split(CANDIDATES_MARKER, 1)[1])['candidates']


def resolve(template: dict, candidates: list[dict]) -> dict:
    """Replace quote selectors with the opaque ids the prompt actually offered."""
    def citations(items):
        out = []
        for c in items:
            if 'literal_id' in c:
                out.append({'id': c['literal_id'], 'stance': c['stance']})
                continue
            matched = [x['id'] for x in candidates if c['quote_contains'] in x['quote']]
            if not matched:
                raise AssertionError('scripted citation not offered: ' + c['quote_contains'])
            out.extend({'id': i, 'stance': c['stance']} for i in matched)
        return out
    response = json.loads(json.dumps(template))
    for s in response.get('suggestions', []):
        for p in s.get('parts', []):
            p['citations'] = citations(p['citations'])
    for n in response.get('non_conclusions', []):
        n['citations'] = citations(n['citations'])
    return response


class ScriptedProvider:
    """Drop-in for llm.run_structured; records every call for exact counts."""

    def __init__(self, case: str, variant: str = 'oracle', fail: Exception | None = None):
        self.template = next(r['response'] for r in load('responses.json')['responses']
                             if r['case'] == case and r['variant'] == variant)
        self.fail = fail
        self.calls = []

    def __call__(self, prompt, schema, cfg, *, system=None, timeout=None, **kwargs):
        self.calls.append({'chars': len(prompt) + len(system or ''), 'timeout': timeout, 'schema': schema})
        if self.fail is not None:
            raise self.fail
        return resolve(self.template, candidates_from_prompt(prompt))


class ForbiddenProvider:
    """Fails the test on any provider call."""
    calls = 0

    def __call__(self, *args, **kwargs):
        type(self).calls += 1
        raise AssertionError('provider must not be called')
