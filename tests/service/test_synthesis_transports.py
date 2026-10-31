"""RAG-065 T065-004: one pattern tool family through local MCP functions, REST,
remote MCP, local CLI and the central CLI client; read-only and foreign scopes,
global switch, credential revocation before commit, and unchanged old tools.
"""
from dataclasses import replace
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import cli, db, llm, mcp_server, store, worker
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from .test_api import app_fixture, headers, KEYS

OLD_TOOLS = ['memory_entity', 'memory_context', 'memory_summary', 'memory_domains', 'memory_search', 'memory_research',
             'memory_get', 'memory_neighbors', 'memory_path', 'memory_timeline', 'memory_evidence',
             'memory_evidence_history', 'memory_entity_alias', 'memory_entity_alias_review', 'memory_save',
             'memory_assert', 'memory_source_state', 'memory_review_claim', 'memory_pin', 'memory_unpin']
READ = {'memory_pattern_preview', 'memory_pattern_status', 'memory_patterns', 'memory_pattern'}
WRITE = {'memory_pattern_policy', 'memory_pattern_backfill', 'memory_pattern_recover'}
K1 = [d for d in fx.load('corpus.json')['documents'] if d['case'] == 'K1']


@pytest.fixture
def pattern_store(monkeypatch):
    from agentic_rag import synthesis
    monkeypatch.setattr(synthesis, 'SETTLE_SECONDS', 0)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1', synthesis_enabled=True)
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            conn.commit()
        yield owned


def ingest(cfg, domain='alpha', project='/projects/a'):
    ids = {}
    with db.connect(cfg) as conn:
        for d in K1:
            s = d['sources'][0]
            ids[d['key']] = store.save_claim(conn, cfg, title=d['title'], body=d['body'], domain=domain, dtype='memory',
                                             project=project, claim_kind='stated', evidence=[dict(s)]).doc_id
    return ids


def call(client, key, name, **arguments):
    response = client.post('/v1/tools/' + name, headers=headers(key), json=arguments)
    return response.status_code, response.json()


def process(cfg, policy_file, monkeypatch, provider=None):
    from agentic_rag import synthesis
    monkeypatch.setattr(llm, 'run_structured', provider or fx.ScriptedProvider('K1'))
    worker_cfg = replace(cfg, service_auth_file=policy_file)
    with db.connect(worker_cfg, role='writer') as conn:
        synthesis.schedule(conn, worker_cfg)
        worker.drain(conn, worker_cfg)
        row = conn.execute('SELECT state,code FROM synthesis_runs ORDER BY created_at DESC LIMIT 1').fetchone()
        conn.commit()
    return dict(row)


def test_tool_registration_adds_family_and_keeps_old_signatures():
    ro, rw = set(mcp_server.tool_names(True)), set(mcp_server.tool_names(False))
    assert READ <= ro and not (WRITE & ro) and WRITE <= rw
    assert set(OLD_TOOLS) <= ro | rw and [t for t in mcp_server.tool_names(False) if t in OLD_TOOLS] == OLD_TOOLS


def test_rest_remote_mcp_scopes_and_read_only_principals(pattern_store, tmp_path, monkeypatch):
    cfg = pattern_store
    app, policy_file = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        status, body = call(client, KEYS[3], 'memory_pattern_preview', domain='alpha', project='/projects/a')
        assert status == 200 and body['candidates']['memories'] == 0
        for name, args in [('memory_pattern_policy', dict(domain='alpha', project='/projects/a', enabled=True, reason='ro')),
                           ('memory_pattern_backfill', dict(domain='alpha', project='/projects/a', reason='ro',
                                                            start='2026-01-01T00:00:00Z', end='2026-01-02T00:00:00Z')),
                           ('memory_pattern_recover', dict(run_id='00000000-0000-0000-0000-000000000000', reason='ro'))]:
            assert call(client, KEYS[3], name, **args) == (403, {'error': 'scope_denied'})
        # Writer enables its own scope; another user's write is denied before any SQL.
        status, policy = call(client, KEYS[0], 'memory_pattern_policy', domain='alpha', project='/projects/a',
                              enabled=True, reason='forward patterns for team a')
        assert status == 200 and policy['enabled'] and policy['forward_from']
        assert call(client, KEYS[2], 'memory_pattern_policy', domain='alpha', project='/projects/a', enabled=False,
                    reason='foreign')[0] == 403
        ids = ingest(cfg)
        assert process(cfg, policy_file, monkeypatch) == {'state': 'applied', 'code': None}
        status, listed = call(client, KEYS[0], 'memory_patterns', domain='alpha', project='/projects/a')
        assert status == 200 and len(listed['items']) == 1
        pattern = listed['items'][0]['id']
        with db.connect(cfg, role='reader') as conn:
            from agentic_rag import synthesis
            local = json.loads(json.dumps(synthesis.inspect(conn, pattern), default=str))
        status, remote = call(client, KEYS[0], 'memory_pattern', id_or_slug=pattern)
        assert status == 200 and remote == local
        mcp = client.post('/mcp/ro/', headers={**headers(KEYS[3]), 'accept': 'application/json, text/event-stream'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'memory_pattern', 'arguments': {'id_or_slug': pattern}}})
        assert mcp.status_code == 200, mcp.text
        result = mcp.json()['result']
        structured = result.get('structuredContent') or json.loads(result['content'][0]['text'])
        assert structured['pattern']['id'] == pattern and structured['parts'] == local['parts']
        # Foreign principals learn nothing: same response as an unknown id.
        foreign = [call(client, KEYS[2], 'memory_pattern', id_or_slug=pattern),
                   call(client, KEYS[2], 'memory_pattern', id_or_slug='00000000-0000-0000-0000-000000000000'),
                   call(client, KEYS[2], 'memory_evidence', id_or_slug=pattern)]
        assert {json.dumps(r) for r in foreign} == {json.dumps([404, {'error': 'evidence_unavailable'}])}
        status, bob = call(client, KEYS[2], 'memory_pattern_status')
        assert status == 200 and bob['policies'] == [] and bob['runs'] == []
        status, alice = call(client, KEYS[0], 'memory_pattern_status', domain='alpha', project='/projects/a')
        assert status == 200 and alice['runs'][0]['state'] == 'applied'
        assert 'owner' not in json.dumps(alice) and 'session:' not in json.dumps(alice)
        assert 'evt-' not in json.dumps(remote) and 'session:' not in json.dumps(remote)
        # A source change withholds the pattern on every central surface.
        with db.connect(cfg) as conn:
            key = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s', (ids['k1-a'],)).fetchone()['source_key']
            conn.commit()
            store.set_source_state(conn, key, state='refuted', reason='corrected')
        assert call(client, KEYS[0], 'memory_pattern', id_or_slug=pattern) == (404, {'error': 'evidence_unavailable'})
        assert call(client, KEYS[0], 'memory_evidence', id_or_slug=pattern) == (404, {'error': 'evidence_unavailable'})
        status, got = call(client, KEYS[0], 'memory_get', id_or_slug=pattern)
        assert status == 200 and 'error' in got
        assert call(client, KEYS[0], 'memory_patterns', domain='alpha', project='/projects/a')[1]['items'] == []


def test_global_switch_off_rejects_writes_with_a_stable_code(pattern_store, tmp_path):
    app, _ = app_fixture(tmp_path, replace(pattern_store, synthesis_enabled=False))
    with TestClient(app, base_url='https://testserver') as client:
        assert call(client, KEYS[0], 'memory_pattern_policy', domain='alpha', project='/projects/a', enabled=True,
                    reason='x') == (409, {'error': 'synthesis_disabled'})
        assert call(client, KEYS[0], 'memory_pattern_status')[0] == 200


def test_central_writer_recovers_accepted_run_without_another_provider_call(pattern_store, tmp_path, monkeypatch):
    # Missing synthesis queue RLS must fail here, even when local owner recovery works.
    from agentic_rag import synthesis
    cfg = pattern_store
    app, policy_file = app_fixture(tmp_path, cfg)
    provider = fx.ScriptedProvider('K1')
    real_register = synthesis._register
    with TestClient(app, base_url='https://testserver') as client:
        assert call(client, KEYS[0], 'memory_pattern_policy', domain='alpha', project='/projects/a',
                    enabled=True, reason='recover regression')[0] == 200
        ingest(cfg)
        def fail_apply(*args, **kwargs):
            raise RuntimeError('injected apply failure')
        monkeypatch.setattr(synthesis, '_register', fail_apply)
        assert process(cfg, policy_file, monkeypatch, provider)['state'] == 'accepted'
        monkeypatch.setattr(synthesis, '_register', real_register)
        # Simulate the existing worker exhausting its finite apply attempts.
        with db.connect(cfg) as conn:
            conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'")
            conn.commit()
        assert process(cfg, policy_file, monkeypatch, provider) == {'state': 'error', 'code': 'apply_failed'}
        with db.connect(cfg) as conn:
            run_id = str(conn.execute('SELECT id FROM synthesis_runs').fetchone()['id'])
        assert call(client, KEYS[3], 'memory_pattern_recover', run_id=run_id, reason='read only')[0] == 403
        assert call(client, KEYS[2], 'memory_pattern_recover', run_id=run_id, reason='foreign') == call(
            client, KEYS[2], 'memory_pattern_recover', run_id='00000000-0000-0000-0000-000000000000', reason='foreign')
        status, recovered = call(client, KEYS[0], 'memory_pattern_recover', run_id=run_id, reason='storage repaired')
        assert status == 200, recovered
        assert recovered == {'id': run_id, 'state': 'accepted'}
        assert process(cfg, policy_file, monkeypatch, provider) == {'state': 'applied', 'code': None}
        assert len(provider.calls) == 1
        assert len(call(client, KEYS[0], 'memory_patterns', domain='alpha', project='/projects/a')[1]['items']) == 1


def test_revoked_owner_credential_withholds_before_any_commit(pattern_store, tmp_path, monkeypatch):
    cfg = pattern_store
    app, policy_file = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        assert call(client, KEYS[0], 'memory_pattern_policy', domain='alpha', project='/projects/a', enabled=True,
                    reason='on')[0] == 200
    ingest(cfg)
    from agentic_rag.service.auth import hash_key
    text = policy_file.read_text().replace(hash_key(KEYS[0]), hash_key('one.synthetic-rotated-replacement-secret'))
    policy_file.write_text(text)
    provider = fx.ForbiddenProvider()
    fx.ForbiddenProvider.calls = 0
    assert process(cfg, policy_file, monkeypatch, provider) == {'state': 'withheld', 'code': 'authorization_changed'}
    assert fx.ForbiddenProvider.calls == 0
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM synthesis_patterns').fetchone()['n'] == 0


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_local_and_central_cli_use_the_same_contract(pattern_store, tmp_path, monkeypatch, capsys):
    cfg = pattern_store
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    code, out, err = run_cli(capsys, 'pattern', 'enable', '--domain', 'alpha', '--project', '/projects/a',
                             '--reason', 'local operator opt-in')
    assert code == 0, err
    ids = ingest(cfg)
    code, out, err = run_cli(capsys, 'pattern', 'preview', '--domain', 'alpha', '--project', '/projects/a', '--json')
    assert code == 0 and json.loads(out)['candidates']['independent_events'] == 4, err
    code, out, err = run_cli(capsys, 'pattern', 'preview', '--domain', 'alpha', '--project', '/projects/a')
    assert code == 0 and 'Independent events: 4' in out and 'no provider call' in out
    from agentic_rag import synthesis
    monkeypatch.setattr(llm, 'run_structured', fx.ScriptedProvider('K1'))
    with db.connect(cfg, role='writer') as conn:
        synthesis.schedule(conn, cfg)
        worker.drain(conn, cfg)
    code, out, err = run_cli(capsys, 'pattern', 'list', '--domain', 'alpha', '--project', '/projects/a', '--json')
    pattern = json.loads(out)['items'][0]['id']
    code, out, err = run_cli(capsys, 'pattern', 'show', pattern)
    assert code == 0 and 'Inferred pattern' in out and 'not a user statement' in out
    code, out, err = run_cli(capsys, 'pattern', 'status', '--json')
    assert code == 0 and json.loads(out)['runs'][0]['state'] == 'applied'
    code, out, err = run_cli(capsys, 'pattern', 'backfill', '--domain', 'alpha', '--project', '/projects/a',
                             '--start', '2026-01-01T00:00:00Z', '--end', '2026-01-02T00:00:00Z', '--reason', 'history')
    assert code == 0 and 'backfill' in out
    code, out, err = run_cli(capsys, 'pattern', 'disable', '--domain', 'alpha', '--project', '/projects/a',
                             '--reason', 'pause')
    assert code == 0
    code, out, err = run_cli(capsys, 'pattern', 'show', pattern)
    assert code == 1 and 'evidence_unavailable' in err
    # Central client mode: the same commands go through the service.
    app, _ = app_fixture(tmp_path, cfg)
    token = tmp_path / 'token'
    token.write_text(KEYS[0])
    token.chmod(0o600)
    client_cfg = replace(cfg, service_mode='client', service_url='https://testserver', service_token_file=token,
                         service_spool_dir=tmp_path / 'spool', db_name='no_local_database_access')
    monkeypatch.setattr(cli, 'load_config', lambda: client_cfg)
    from agentic_rag.service import client as remote
    original = remote.RemoteClient
    with TestClient(app, base_url='https://testserver') as sender:
        monkeypatch.setattr(remote, 'RemoteClient', lambda c: original(c, sender=sender))
        code, out, err = run_cli(capsys, 'pattern', 'enable', '--domain', 'alpha', '--project', '/projects/a',
                                 '--reason', 'central opt-in')
        assert code == 0, err
        code, out, err = run_cli(capsys, 'pattern', 'show', pattern, '--json')
        assert code == 0 and json.loads(out)['pattern']['id'] == pattern, err
        code, out, err = run_cli(capsys, 'pattern', 'status', '--domain', 'alpha', '--project', '/projects/a', '--json')
        assert code == 0 and json.loads(out)['policies'][0]['enabled'] is True
    assert len(ids) == 4
