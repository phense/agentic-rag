"""RAG-064 frozen synthetic temporal corpus: gateway ingestion and case execution.

Every row is written through the audited gateways. Used by the tests and by
docs/benchmarks/2026-10-31-temporal-query/measure.py; no provider is called.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / 'docs/benchmarks/2026-10-31-temporal-query/fixtures'
FROZEN = {
    'parser-cases.json': '9528011b73dbbc23c91f5e0eb5b44db7a4bde348c2b09fcfb397a4f389d5613f',
    'ranking-corpus.json': '824bdcc2c5c108c03477e38b830538e5a539fc9cade1c7daf158e9efe4743050',
    'ranking-cases.json': '7cd9a2c81ac368c57f1c7ee611627d1f3e7023efcff856605529355a44038b9f',
}


def load(name: str) -> dict:
    data = (FIXTURES / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != FROZEN[name]:
        raise ValueError('frozen fixture changed: ' + name)
    return json.loads(data)


def ingest(conn, cfg, corpus: dict | None = None) -> dict[str, str]:
    """Write the corpus through the gateways; return fixture key -> document id."""
    from .. import store
    from ..evidence import sources
    corpus = corpus or load('ranking-corpus.json')
    domain, namespace = corpus['domain'], corpus['namespace']
    keys = {}
    for d in corpus['documents']:
        if d['kind'] == 'claim':
            evidence = [dict(namespace=namespace, source_id=s['source_id'], role=s['role'], quote=d['body'],
                             timestamp=s['timestamp'], complete=s['complete']) for s in d['sources']]
            saved = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain=domain, dtype='memory',
                                     project=d['project'], claim_kind=d['claim_kind'], evidence=evidence, actor='cli')
        elif d['kind'] == 'assertion':
            saved = store.save_assertion(conn, cfg, entity=d['entity'], attribute=d['attribute'], value=d['value'],
                event_at=d['event_at'], expires_at=d['expires_at'], relation=d['relation'], domain=domain,
                project=d['project'], evidence={'namespace': namespace, 'source_id': d['key'], 'role': 'user',
                                                'quote': d['value'], 'event_at': d['event_at']})
            if saved.disposition != 'accepted':
                raise ValueError('fixture assertion rejected: ' + d['key'])
        else:
            saved = store.save_document(conn, cfg, title=d['title'], body=d['body'], domain=domain,
                                        dtype='memory', project=d['project'], actor='cli')
        keys[d['key']] = saved.doc_id
        for op in d.get('after', ()):
            if op['op'] in ('refute', 'confirm'):
                store.review_claim(conn, saved.doc_id, state={'refute': 'refuted', 'confirm': 'confirmed'}[op['op']],
                                   reason='synthetic fixture review')
            elif op['op'] == 'withdraw':
                wanted = d['sources'][op['source']]['source_id']
                key = next(s['source_key'] for s in sources(conn, saved.doc_id) if s['source_id'] == wanted)
                store.set_source_state(conn, key, state='removed', reason='synthetic fixture withdrawal')
    conn.commit()
    return keys


def options(case: dict, *, mode: str | None) -> dict:
    """search() keyword arguments for one frozen case; mode=None means feature off."""
    params = load('ranking-cases.json')['parameters']
    result = dict(domain=params['domain'], k=params['k'], project=case['project'], strategy=params['strategy'],
                  rerank_mode=params['rerank'], context_mode=params['context'], history=case['history'],
                  as_of=case['as_of'])
    if mode is not None:
        result.update(temporal=mode, reference=case['reference'], timezone=case['timezone'])
    return result


def ranked_keys(hits, keys: dict[str, str]) -> list[str]:
    """Document-level order (first chunk per document) as fixture keys."""
    names = {v: k for k, v in keys.items()}
    seen = []
    for h in hits:
        name = names.get(h.document_id if hasattr(h, 'document_id') else h['document_id'], '?')
        if name not in seen:
            seen.append(name)
    return seen
