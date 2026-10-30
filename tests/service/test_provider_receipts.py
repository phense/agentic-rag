"""AF061-005: safe HTTP-provider categories survive worker, receipt and trace."""
from dataclasses import replace

import httpx
import pytest
from starlette.testclient import TestClient

from agentic_rag import db, providers, worker
from .test_api import KEYS, app_fixture, headers
from .test_ingest import envelope
from .test_scope import service_store


@pytest.mark.parametrize('status, category', [(401, 'authentication'), (429, 'rate_limit'), (503, 'transient')])
def test_http_provider_failure_is_visible_in_source_receipt_and_trace(service_store, tmp_path, monkeypatch, status, category):
    cfg, _ = service_store
    cfg = replace(cfg, service_mode='server', service_storage_path=tmp_path,
        llm_provider='openai-compatible', llm_model='extract-v1', llm_revision='extract-v1',
        llm_url='http://127.0.0.1:1', worker_max_attempts=3, worker_backoff_seconds=0)
    secret = 'synthetic-provider-body-must-never-be-diagnostics'
    transport = httpx.MockTransport(lambda request: httpx.Response(status,
        json={'error': secret, 'input': 'synthetic corpus that must stay out of status'}))
    monkeypatch.setattr(providers, '_http_client', lambda **kwargs: httpx.Client(transport=transport, **kwargs))
    app, path = app_fixture(tmp_path, cfg)
    configured = replace(cfg, service_auth_file=path)
    with TestClient(app, base_url='https://testserver') as client:
        submitted = client.post('/v1/windows', headers=headers(KEYS[0]),
            json=envelope(session='provider-' + category))
        assert submitted.status_code == 202, submitted.text
        receipt = submitted.json()['receipt']
        with db.connect(configured) as conn:
            queue_id = conn.execute('SELECT queue_id FROM service_windows WHERE id=%s', (receipt,)).fetchone()['queue_id']
            conn.execute("UPDATE mining_queue SET next_attempt_at=now()+interval '1 day' WHERE id<>%s", (queue_id,))
        for _ in range(3):
            with db.connect(configured) as conn:
                conn.execute('UPDATE mining_queue SET next_attempt_at=now() WHERE id=%s', (queue_id,))
            with db.connect(configured) as conn:
                worker.drain(conn, configured, max_jobs=1)
        observed = client.get('/v1/jobs/' + receipt, headers=headers(KEYS[0]))
        assert observed.status_code == 200
        assert observed.json()['state'] == 'error'
        assert observed.json()['queue']['attempts'] == 3
        assert observed.json()['code'] == 'provider_' + category
        trace = client.get('/v1/traces/' + submitted.headers['x-rag-request-id'], headers=headers(KEYS[0]))
        assert trace.status_code == 200
        assert trace.json()['job']['code'] == 'provider_' + category
        assert trace.json()['trace']['outcome'] == 'accepted'
        assert secret not in observed.text + trace.text
