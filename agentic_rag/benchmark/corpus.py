"""Versioned synthetic corpus loader with pre-ingestion label validation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_CORPUS = Path(__file__).with_name('corpus-v1.json')


def validate(corpus: dict) -> None:
    if not isinstance(corpus, dict) or corpus.get('version') != 1 or corpus.get('synthetic') is not True:
        raise ValueError('benchmark requires version 1 and explicitly synthetic data')
    documents = corpus.get('documents', [])
    queries = corpus.get('queries', [])
    if not isinstance(documents, list) or not isinstance(queries, list) or not documents or not queries:
        raise ValueError('corpus must include documents and queries')
    for document in documents:
        if not isinstance(document, dict) or not all(isinstance(document.get(k), str) and document[k].strip()
                   for k in ['id', 'title', 'body', 'project']):
            raise ValueError('invalid source document')
    for q in queries:
        if not isinstance(q, dict) or not all(isinstance(q.get(k), str) and q[k].strip()
                                              for k in ['id', 'query', 'category']):
            raise ValueError('invalid query metadata')
        for key in ['expected_ids', 'answers', 'stale_answers']:
            values = q.get(key, [] if key == 'stale_answers' else None)
            if (not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError(f'invalid query label list: {key}')
        if not isinstance(q.get('family', q['id']), str) or not q.get('family', q['id']).strip():
            raise ValueError('invalid query family')
    by_id = {d['id']: d for d in documents}
    if len(by_id) != len(documents) or len({q['id'] for q in queries}) != len(queries):
        raise ValueError('duplicate corpus identity')
    from ..scope import selection, write_scope
    for document in documents:
        if document.get("scope") is not None:
            write_scope(document["project"] if document["project"].startswith("/") else None, document["scope"])
    families = {}
    for q in queries:
        if q.get('split') not in {'dev', 'test'}:
            raise ValueError('invalid query split')
        if q.get('language') not in {'en', 'de'} or not q.get('category') or not q.get('query'):
            raise ValueError('invalid query metadata')
        if len(set(q['expected_ids'])) != len(q['expected_ids']) or not set(q['expected_ids']) <= by_id.keys():
            raise ValueError('expected evidence missing or duplicated')
        if type(q.get('unanswerable')) is not bool:
            raise ValueError('unanswerable must be explicit')
        if q['unanswerable']:
            if q['expected_ids'] or q['answers']:
                raise ValueError('unanswerable queries cannot have expected evidence/answers')
        elif not q['expected_ids'] or not q['answers']:
            raise ValueError('answerable queries require evidence and answers')
        selected = selection(q.get("project"), q.get("scope"))
        if selected is not None:
            for identity in q["expected_ids"]:
                doc = by_id[identity]
                target = write_scope(doc["project"] if doc["project"].startswith("/") else None, doc.get("scope")) or "unknown"
                if target not in selected:
                    raise ValueError("expected evidence outside query scope")
        family = q.get('family', q['id'])
        if family in families and families[family] != q['split']:
            raise ValueError('query family leaks across split')
        families[family] = q['split']


def load(path: Path | None = None) -> tuple[dict, str]:
    data = (path or DEFAULT_CORPUS).read_bytes()
    corpus = json.loads(data)
    validate(corpus)
    return corpus, hashlib.sha256(data).hexdigest()
