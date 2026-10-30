"""New HTTP failures must spend a finite job budget, including rate limits."""
from dataclasses import replace

import pytest

from agentic_rag import llm, providers, worker


@pytest.mark.parametrize('code', ['rate_limit', 'transient'])
def test_http_retryable_outage_exhausts_finite_job_budget(conn, cfg, monkeypatch, code):
    configured = replace(cfg, llm_provider='openai-compatible', worker_max_attempts=3,
        worker_backoff_seconds=0)
    def unavailable(*a, **k):
        raise providers.ProviderError(code, True, 'Synthetic retryable provider failure.')
    monkeypatch.setattr(providers, 'run_http_structured', unavailable)
    def process(*a, **k):
        return llm.run_structured('Synthetic job', {'type': 'object'}, configured)
    monkeypatch.setattr(worker, 'process_job', process)
    identity = conn.execute("INSERT INTO mining_queue(kind,session_id,transcript_path) VALUES ('mine','synthetic-provider-retry','/synthetic/no-content') RETURNING id").fetchone()['id']
    conn.commit()
    for _ in range(3):
        worker.drain(conn, configured, max_jobs=1)
    row = conn.execute('SELECT status,attempts FROM mining_queue WHERE id=%s', (identity,)).fetchone()
    assert row == {'status': 'error', 'attempts': 3}
