"""Authenticated feedback contracts on owned PostgreSQL; no provider calls."""
from dataclasses import replace
import uuid

from starlette.testclient import TestClient

from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS


def test_explicit_writer_search_captures_event_without_retaining_query(service_store, tmp_path):
    # Mutation caught: tool absent, ordinary search substituted or raw query retained.
    cfg, docs = service_store
    cfg = replace(cfg, feedback_enabled=True) if hasattr(cfg, 'feedback_enabled') else cfg
    app, _ = app_fixture(tmp_path, cfg)
    query = 'Synthetic protected evidence'
    with TestClient(app, base_url='https://testserver') as client:
        response = client.post('/v1/tools/memory_feedback_search', headers=headers(KEYS[0]), json={
            'query': query, 'domain': 'alpha', 'project': '/projects/a',
            'idempotency_key': str(uuid.uuid4()), 'strategy': 'lexical'})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['event']['query_sha256'] == '026983b732608b0cc42659a06883a92bbbd48d354ac9007d7ba665b701ca819b'
        assert str(docs['allowed']) in {r['document_id'] for r in data['results']}
    from agentic_rag import db
    with db.connect(cfg) as conn:
        retained = conn.execute('SELECT row_to_json(e)::text data FROM retrieval_feedback_events e WHERE id=%s', (data['event']['id'],)).fetchone()['data']
        assert query not in retained and 'Synthetic protected' not in retained
