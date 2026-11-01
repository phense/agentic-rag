"""RAG-066 frozen synthetic lifecycle corpus and gateway ingestion.

Every row is written through the audited gateways (save_document, save_claim,
save_assertion), in list order with one commit per document, so list order is
creation order. The hand-written labels are expectations, not model output.
Used by the tests and by docs/benchmarks/2026-10-31-memory-lifecycle/measure.py.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / 'docs/benchmarks/2026-10-31-memory-lifecycle/fixtures'
FROZEN = {
    'corpus.json': 'd717507f2a82414a4abdf2ffba1ba0130d7f015e692853d720e4aa7109aa7e67',
    'labels.json': 'f5a98eaa7e4737edecde65a5de4ceb2e1424ea74e4192ab2edda6f290276fa11',
}


def load(name: str) -> dict:
    data = (FIXTURES / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != FROZEN[name]:
        raise ValueError('frozen fixture changed: ' + name)
    return json.loads(data)


def documents(case_ids=None) -> list[dict]:
    corpus = load('corpus.json')
    return [d for d in corpus['documents'] if case_ids is None or d['case'] in case_ids]


def project(key: str | None) -> str | None:
    return None if key is None else load('corpus.json')['projects'][key]


def ingest(conn, cfg, case_ids=None) -> dict[str, str]:
    """Write the selected fixture cases through the gateways; return key -> document id."""
    from .. import domains, store
    for name in load('corpus.json')['domains']:
        if not conn.execute('SELECT 1 FROM domains WHERE name=%s', (name,)).fetchone():
            domains.add_domain(conn, name)
    conn.commit()
    keys = {}
    for d in documents(case_ids):
        selected = project(d.get('project'))
        if d['kind'] == 'claim':
            saved = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain=d['domain'], dtype=d['dtype'],
                                     project=selected, claim_kind=d['claim_kind'],
                                     evidence=[dict(s) for s in d['sources']], actor='cli')
        elif d['kind'] == 'assertion':
            saved = store.save_assertion(conn, cfg, entity=d['entity'], attribute=d['attribute'], value=d['value'],
                                         event_at=d['event_at'], relation=d['relation'], domain=d['domain'],
                                         project=selected, evidence=dict(d['evidence']), actor='cli')
        else:
            saved = store.save_document(conn, cfg, title=d['title'], body=d['body'], domain=d['domain'],
                                        dtype=d['dtype'], project=selected, actor='cli')
        keys[d['key']] = saved.doc_id
        conn.commit()
    return keys
