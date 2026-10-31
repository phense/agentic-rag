"""RAG-063 S3: the same evidence contract through local MCP, REST and remote MCP."""
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import db, evidence, mcp_server, store
from agentic_rag import evidence_contract as contract
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from .test_api import app_fixture, headers, KEYS

SHARED = {'namespace': 'session:/home/alice/.claude/projects/private.jsonl', 'source_id': 'event-1', 'role': 'user',
          'quote': 'Shared synthetic statement', 'complete': True, 'timestamp': '2026-01-02T03:04:05Z'}
OWN = {**SHARED, 'source_id': 'event-own', 'quote': 'Own synthetic statement'}


@pytest.fixture
def evidence_store(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            own = store.save_claim(conn, owned, title='own', body='Own synthetic claim', domain='alpha', dtype='memory',
                                   project='/projects/a', claim_kind='stated', evidence=[SHARED, OWN])
            foreign = store.save_claim(conn, owned, title='foreign', body='Foreign synthetic claim', domain='beta',
                                       dtype='memory', project='/projects/b', claim_kind='stated', evidence=[SHARED])
            rows = {r['quote']: r['source_key'] for r in conn.execute('SELECT quote,source_key FROM claim_evidence WHERE document_id=%s', (own.doc_id,))}
        yield owned, own.doc_id, foreign.doc_id, rows[SHARED['quote']], rows[OWN['quote']]


def local_view(cfg, doc, **kw):
    with db.connect(cfg, role='reader') as conn:
        return contract.inspect(conn, doc, **kw)


def test_tool_registration_keeps_privilege_split():
    ro, rw = set(mcp_server.tool_names(True)), set(mcp_server.tool_names(False))
    assert {'memory_evidence', 'memory_evidence_history'} <= ro
    assert {'memory_review_claim', 'memory_source_state'} <= rw - ro


def test_rest_and_remote_mcp_return_the_local_contract(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    expected = local_view(cfg, own)
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        rest = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': own})
        assert rest.status_code == 200, rest.text
        assert rest.json() == json.loads(json.dumps(expected, default=str))
        mcp = client.post('/mcp/ro/', headers={**headers(KEYS[3]), 'accept': 'application/json, text/event-stream'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'memory_evidence', 'arguments': {'id_or_slug': own}}})
        assert mcp.status_code == 200, mcp.text
        structured = mcp.json()['result'].get('structuredContent') or json.loads(mcp.json()['result']['content'][0]['text'])
        assert structured['version'] == expected['version']
        assert structured['sources']['items'] == rest.json()['sources']['items']
        assert 'private.jsonl' not in rest.text and 'event-1' not in rest.text
        history = client.post('/v1/tools/memory_evidence_history', headers=headers(KEYS[3]),
                              json={'id_or_slug': own, 'source_key': shared_key})
        assert history.status_code == 200 and history.json()['scope'] == 'source'


def test_inaccessible_unknown_and_unlinked_anchors_share_one_response(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        responses = [client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json=args) for args in [
            {'id_or_slug': foreign},
            {'id_or_slug': '00000000-0000-0000-0000-000000000000'},
            {'id_or_slug': own, 'source_key': '0' * 64},
        ]]
        responses.append(client.post('/v1/tools/memory_evidence_history', headers=headers(KEYS[0]),
                                     json={'id_or_slug': foreign, 'source_key': shared_key}))
        assert {(r.status_code, r.text) for r in responses} == {(404, '{"error":"evidence_unavailable"}')}
        # Counts never include foreign dependents of the shared source.
        view = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': own}).json()
        assert view['sources']['total'] == 2 and view['sources']['distinct_sources'] == 2
        assert foreign not in json.dumps(view)


def test_strict_review_conflict_is_409_and_changes_nothing(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        seen = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': own}).json()['version']
        legacy = client.post('/v1/tools/memory_review_claim', headers=headers(KEYS[0]),
                             json={'id_or_slug': own, 'state': 'unreviewed', 'reason': 'legacy writer'})
        assert legacy.status_code == 200 and legacy.json()['review_state'] == 'unreviewed'
        with db.connect(cfg) as conn:
            before = conn.execute('SELECT (SELECT count(*) FROM audit_log) a,(SELECT count(*) FROM claim_history) h').fetchone()
        stale = client.post('/v1/tools/memory_review_claim', headers=headers(KEYS[0]),
                            json={'id_or_slug': own, 'state': 'confirmed', 'reason': 'stale', 'expected_version': seen})
        assert (stale.status_code, stale.json()) == (409, {'error': 'evidence_conflict'})
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT (SELECT count(*) FROM audit_log) a,(SELECT count(*) FROM claim_history) h').fetchone() == before
            legacy_row = conn.execute("SELECT concurrency,inspected_version,actor FROM claim_history WHERE operation='review'").fetchone()
        assert legacy_row == {'concurrency': 'legacy', 'inspected_version': None, 'actor': 'service:machine:alice:vm1'}
        fresh = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': own}).json()['version']
        ok = client.post('/v1/tools/memory_review_claim', headers=headers(KEYS[0]),
                         json={'id_or_slug': own, 'state': 'confirmed', 'reason': 'fresh', 'expected_version': fresh})
        assert ok.status_code == 200 and ok.json()['version'] != fresh
        denied = client.post('/v1/tools/memory_review_claim', headers=headers(KEYS[3]),
                             json={'id_or_slug': own, 'state': 'refuted', 'reason': 'ro', 'expected_version': ok.json()['version']})
        assert denied.status_code == 403


def test_strict_shared_source_change_requires_every_dependent_and_is_non_oracular(evidence_store, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        items = {i['source_key']: i for i in client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]),
                                                           json={'id_or_slug': own}).json()['sources']['items']}
        shared = client.post('/v1/tools/memory_source_state', headers=headers(KEYS[0]), json={
            'source_key': shared_key, 'state': 'removed', 'reason': 'withdraw', 'id_or_slug': own,
            'expected_version': items[shared_key]['source_version']})
        assert (shared.status_code, shared.json()) == (404, {'error': 'evidence_unavailable'})
        own_change = client.post('/v1/tools/memory_source_state', headers=headers(KEYS[0]), json={
            'source_key': own_key, 'state': 'removed', 'reason': 'withdraw own', 'id_or_slug': own,
            'expected_version': items[own_key]['source_version']})
        assert own_change.status_code == 200, own_change.text
        again = client.post('/v1/tools/memory_source_state', headers=headers(KEYS[0]), json={
            'source_key': own_key, 'state': 'active', 'reason': 'stale token', 'id_or_slug': own,
            'expected_version': items[own_key]['source_version']})
        assert (again.status_code, again.json()) == (409, {'error': 'evidence_conflict'})
    with db.connect(cfg) as conn:
        states = {r['source_key']: r['state'] for r in conn.execute('SELECT source_key,state FROM knowledge_sources')}
        assert states == {shared_key: 'active', own_key: 'removed'}


def test_authority_revoked_before_commit_leaves_no_decision(evidence_store, tmp_path, monkeypatch):
    cfg, own, *_ = evidence_store
    app, policy = app_fixture(tmp_path, cfg)
    from agentic_rag.service import context
    original = context.ServiceConnection.check_commit_authority

    def revoke_then_check(self):
        if self.authority_scope is not None and not self.authority_scope.read_only:
            policy.write_text(policy.read_text().replace('write_domains = ["alpha"]', 'write_domains = []'))
        return original(self)
    monkeypatch.setattr(context.ServiceConnection, 'check_commit_authority', revoke_then_check)
    with TestClient(app, base_url='https://testserver') as client:
        seen = client.post('/v1/tools/memory_evidence', headers=headers(KEYS[0]), json={'id_or_slug': own}).json()['version']
        response = client.post('/v1/tools/memory_review_claim', headers=headers(KEYS[0]),
                               json={'id_or_slug': own, 'state': 'refuted', 'reason': 'revoked', 'expected_version': seen})
        assert response.status_code == 403 and response.json() == {'error': 'authorization_changed'}
    with db.connect(cfg) as conn:
        assert conn.execute("SELECT count(*) n FROM claim_history WHERE operation='review'").fetchone()['n'] == 0
        assert local_view(cfg, own)['version'] == seen


def test_local_mcp_matches_contract_and_maps_errors(evidence_store, monkeypatch, tmp_path):
    cfg, own, foreign, shared_key, own_key = evidence_store
    config = tmp_path / 'config.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://localhost:1"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    view = mcp_server.memory_evidence(own)
    assert view == json.loads(json.dumps(local_view(cfg, own), default=str))
    with pytest.raises(ValueError, match='evidence_unavailable'):
        mcp_server.memory_evidence('missing-slug')
    result = mcp_server.memory_review_claim(own, 'confirmed', 'checked', expected_version=view['version'])
    assert result['review_state'] == 'confirmed' and result['version'] != view['version']
    with pytest.raises(ValueError, match='evidence_conflict'):
        mcp_server.memory_review_claim(own, 'refuted', 'stale', expected_version=view['version'])
    legacy = mcp_server.memory_review_claim(own, 'unreviewed', 'legacy')
    assert legacy['document_id'] == own and legacy['review_state'] == 'unreviewed'
    assert mcp_server.memory_review_claim('missing', 'unreviewed', 'legacy') == {'error': 'document not found'}
    page = mcp_server.memory_evidence_history(own, limit=2)
    assert len(page['items']) == 2 and page['next_cursor']
