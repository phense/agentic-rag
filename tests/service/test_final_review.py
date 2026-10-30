"""Whole-feature review regressions on owned databases and real transports."""
from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from agentic_rag import db, store
from agentic_rag.service.context import CURRENT
from .test_api import app_fixture, headers, KEYS
from .test_worker_fencing import owned


@pytest.mark.parametrize('revoke', ['logout', 'expire', 'rotate_key', 'remove_scope'])
def test_synchronous_write_revalidates_authority_before_commit(owned, tmp_path, monkeypatch, revoke):
    # A check only at request entry must not allow a post-revocation commit.
    cfg, _ = owned
    app, policy = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        login = client.post('/v1/login', headers={'x-rag-protocol': '1'}, json={
            'username': 'alice', 'password': 'correct horse synthetic password'})
        assert login.status_code == 200
        token = KEYS[0] if revoke in {'rotate_key', 'remove_scope'} else login.json()['access_token']
        def embed(*args, **kwargs):
            original = CURRENT.set(None)  # independent logout/operator connection
            try:
                if revoke == 'logout':
                    assert client.post('/v1/logout', headers=headers(token)).status_code == 200
                elif revoke == 'expire':
                    with db.connect(cfg) as conn:
                        conn.execute("UPDATE service_sessions SET expires_at=now()-interval '1 second'")
                elif revoke == 'rotate_key':
                    from agentic_rag.service.auth import hash_key
                    policy.write_text(policy.read_text().replace(hash_key(KEYS[0]), hash_key('one.synthetic-replacement-secret')))
                else:
                    policy.write_text(policy.read_text().replace('write_domains = ["alpha"]', 'write_domains = []'))
            finally:
                CURRENT.reset(original)
            return None
        monkeypatch.setattr(store, 'try_embed_texts', embed)
        result = client.post('/v1/tools/memory_save', headers=headers(token), json={
            'title': 'Must roll back after revocation', 'body': 'Synthetic port declaration',
            'domain': 'alpha', 'project': '/projects/a'})
        assert result.status_code == 403, result.text
        assert result.json() == {'error': 'authorization_changed'}
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM documents WHERE title='Must roll back after revocation'").fetchone()['n'] == 0
            assert conn.execute("SELECT count(*) n FROM mining_queue").fetchone()['n'] == 0


def test_deployment_idle_timeout_allows_configured_inference(owned, monkeypatch):
    # Exercise the supplied PG and model limits at 1/1000 wall-clock scale.
    # The old 60s idle limit kills a valid 300s model/120s embedding wait.
    from pathlib import Path
    import re
    import time
    import tomllib
    from agentic_rag import mining
    from agentic_rag.service.ingest import mining_window
    from .test_worker_fencing import window
    cfg, _ = owned
    examples = Path(__file__).resolve().parents[2]/'deploy'/'central-service'
    idle = re.search(r"idle_in_transaction_session_timeout\s*=\s*'([^']+)'", (examples/'postgresql.conf.example').read_text()).group(1)
    configured = tomllib.loads((examples/'server.toml.example').read_text())['llm']['timeout']
    with db.connect(cfg) as conn:
        seconds = conn.execute("SELECT extract(epoch FROM %s::interval) n", (idle,)).fetchone()['n']
        conn.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, false)", (str(int(seconds))+'ms',))
        conn.commit()
        # Use this actual connection for mining to exercise both external waits.
        monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: time.sleep(configured/1000) or {
            'memories': [dict(title='Slow valid inference', body='server port is now 9000', domain='alpha', edges=[], claim_kind='stated', evidence=[dict(source_id='event-1', quote='server port is now 9000')])]})
        monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: time.sleep(.120) or None)
        result = mining.mine_session(conn, cfg, session_id='slow-valid', transcript_path='', last_uuid=None,
                                     project='/projects/a', provided_window=mining_window(window()))
        assert result.saved == 1
        assert conn.execute("SELECT count(*) n FROM documents WHERE title='Slow valid inference'").fetchone()['n'] == 1
        assert conn.execute('SHOW idle_in_transaction_session_timeout').fetchone()['idle_in_transaction_session_timeout'] == str(int(seconds))+'ms'


def test_remote_read_budget_includes_retained_source_records(owned, tmp_path):
    cfg, _ = owned
    app, _ = app_fixture(tmp_path, cfg)
    with db.connect(cfg) as conn:
        claim = store.save_claim(conn, cfg, title='Small claim with large sources', body='A short synthetic claim', domain='alpha', dtype='memory',
                                 project='/projects/a', claim_kind='stated', evidence=[dict(namespace='synthetic', source_id=str(n), role='user', quote='A short synthetic claim', complete=True) for n in range(2)])
        keys = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s', (claim.doc_id,)).fetchall()
        for source in keys:
            store.set_source_state(conn, source['source_key'], state='active', reason='x'*600000)
        assert len(store.get_document(conn, claim.doc_id)['claim_sources'][0]['reason']) == 600000
    with TestClient(app, base_url='https://testserver') as client:
        result = client.post('/v1/tools/memory_get', headers=headers(KEYS[0]), json={'id_or_slug': claim.doc_id})
        assert result.status_code == 413, len(result.content)
        assert result.json() == {'error': 'result_too_large'}


@pytest.mark.parametrize('kind', ['graph', 'domain'])
def test_large_graph_and_domain_values_never_reach_python(owned, tmp_path, monkeypatch, kind):
    # A server cursor alone must not transfer a huge legacy row before checking.
    import psycopg
    from agentic_rag import domains
    cfg, _ = owned
    with db.connect(cfg) as conn:
        if kind == 'domain':
            domains.add_domain(conn, 'alpha', description='x'*(8*1024*1024))
        else:
            dst = store.save_document(conn, cfg, title='Budget destination', body='Small target', domain='alpha', dtype='memory', project='/projects/a')
            src = store.save_document(conn, cfg, title='Budget source', body='Small source', domain='alpha', dtype='memory', project='/projects/a',
                                      edges=[store.EdgeSpec('references', dst.slug, evidence='x'*(8*1024*1024))])
    transferred = []
    real_fetch = psycopg.ServerCursor.fetchmany
    def observe(cursor, *args, **kwargs):
        batch = real_fetch(cursor, *args, **kwargs)
        transferred.append(sum(len(v.encode()) for row in batch for v in row.values() if isinstance(v, str)))
        return batch
    monkeypatch.setattr(psycopg.ServerCursor, 'fetchmany', observe)
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        tool, arguments = ('memory_domains', {}) if kind == 'domain' else ('memory_neighbors', {'id_or_slug': src.doc_id, 'depth': 1})
        result = client.post('/v1/tools/'+tool, headers=headers(KEYS[0]), json=arguments)
        assert result.status_code == 413, result.text
        assert result.json() == {'error': 'result_too_large'}
        assert max(transferred, default=0) <= 512*1024
