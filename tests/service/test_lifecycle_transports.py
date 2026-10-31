"""RAG-066 T066-006: lifecycle tools over local MCP functions, REST, remote MCP, the
local CLI and the central CLI client; reader/writer split, foreign and revoked
principals, uniform not_found and the additive view wire argument."""
from dataclasses import replace
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import cli, db, lifecycle, mcp_server, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from .test_api import app_fixture, headers, KEYS

READ = {'memory_lifecycle_preview', 'memory_lifecycle'}
WRITE = {'memory_lifecycle_apply', 'memory_lifecycle_correct'}
MISSING = '00000000-0000-0000-0000-000000000000'


@pytest.fixture
def lifecycle_store(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr('agentic_rag.search.try_embed_texts', lambda *a, **k: None)
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    with isolated_database(cfg) as owned:
        ids = {}
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            conn.commit()
            for key, domain, project in (('keep', 'alpha', '/projects/a'), ('copy', 'alpha', '/projects/a'),
                                         ('foreign-keep', 'beta', '/projects/b'), ('foreign-copy', 'beta', '/projects/b')):
                ids[key] = store.save_document(conn, owned, title='Plotter paper size', body='The plotter is loaded with A0 rolls.',
                                               domain=domain, dtype='memory', project=project).doc_id
        yield owned, ids


def call(client, key, name, **arguments):
    response = client.post('/v1/tools/' + name, headers=headers(key), json=arguments)
    return response.status_code, response.json()


def test_registration_keeps_privilege_split_and_old_signatures():
    ro, rw = set(mcp_server.tool_names(True)), set(mcp_server.tool_names(False))
    assert READ <= ro and not (WRITE & ro) and WRITE <= rw
    assert len(rw) - len(ro) == 13
    # Unset view is omitted on the wire; older services keep accepting the call.
    for name in ('memory_search', 'memory_research', 'memory_get', 'memory_neighbors', 'memory_path'):
        assert 'view' in mcp_server.ADDITIVE_ARGUMENTS[name]
        assert 'view' not in mcp_server.wire_arguments(name, {'query': 'x', 'view': None})
        assert mcp_server.wire_arguments(name, {'view': 'current'}) == {'view': 'current'}


def test_rest_remote_mcp_writer_reader_foreign_and_parity(lifecycle_store, tmp_path):
    cfg, ids = lifecycle_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        status, seen = call(client, KEYS[3], 'memory_lifecycle_preview', member=ids['copy'], target=ids['keep'])
        assert status == 200 and seen['classification'] == 'exact_duplicate' and seen['writes'] == 0
        with db.connect(cfg, role='reader') as conn:
            local = json.loads(json.dumps(lifecycle.preview(conn, ids['copy'], ids['keep']), default=str))
        assert seen == local
        arguments = dict(member=ids['copy'], target=ids['keep'], operation='exact_duplicate', reason='same note',
                         expected_member_version=seen['member']['version'], expected_target_version=seen['target']['version'])
        assert call(client, KEYS[3], 'memory_lifecycle_apply', **arguments) == (403, {'error': 'scope_denied'})
        # Foreign, invisible and missing anchors are indistinguishable, with no counts.
        foreign = [call(client, KEYS[2], 'memory_lifecycle_preview', member=ids['copy'], target=ids['keep']),
                   call(client, KEYS[2], 'memory_lifecycle_preview', member=MISSING, target=ids['foreign-keep']),
                   call(client, KEYS[2], 'memory_lifecycle_apply', **arguments),
                   call(client, KEYS[2], 'memory_lifecycle', id_or_slug=ids['copy'])]
        assert {json.dumps(r) for r in foreign} == {json.dumps([404, {'error': 'not_found'}])}
        status, made = call(client, KEYS[0], 'memory_lifecycle_apply', **arguments)
        assert status == 200 and made['decision']['state'] == 'active', made
        assert call(client, KEYS[0], 'memory_lifecycle_apply', **arguments)[1]['replayed'] is True
        status, stale = call(client, KEYS[0], 'memory_lifecycle_apply', **{**arguments, 'reason': 'other'})
        assert (status, stale) == (409, {'error': 'stale_version'})
        mcp = client.post('/mcp/ro/', headers={**headers(KEYS[3]), 'accept': 'application/json, text/event-stream'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'memory_lifecycle', 'arguments': {'id_or_slug': ids['keep']}}})
        assert mcp.status_code == 200, mcp.text
        result = mcp.json()['result']
        structured = result.get('structuredContent') or json.loads(result['content'][0]['text'])
        assert [m['member']['id'] for m in structured['as_canonical']['members']] == [ids['copy']]
        listed = client.post('/mcp/ro/', headers={**headers(KEYS[3]), 'accept': 'application/json, text/event-stream'},
                             json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}).json()['result']['tools']
        names = {t['name'] for t in listed}
        assert READ <= names and not (WRITE & names)
        # Views over REST: omitted keeps the payload, explicit adds labels, invalid fails.
        status, plain = call(client, KEYS[0], 'memory_search', query='plotter rolls', strategy='lexical', rerank='off')
        assert status == 200 and [h['document_id'] for h in plain['results']] == [ids['keep']]
        assert all('lifecycle' not in h['evidence'] for h in plain['results'])
        status, merged = call(client, KEYS[0], 'memory_search', query='plotter rolls', strategy='lexical', rerank='off',
                              view='include_merged')
        assert {h['evidence']['lifecycle']['state'] for h in merged['results']} == {'current', 'merged'}
        assert call(client, KEYS[0], 'memory_search', query='x', view='current', history=True) == (400, {'error': 'invalid_view'})
        status, got = call(client, KEYS[3], 'memory_get', id_or_slug=ids['copy'], view='current')
        assert status == 200 and got['lifecycle']['resolution'] == 'canonical' and got['document']['id'] == ids['keep']
        status, detail = call(client, KEYS[0], 'memory_lifecycle', id_or_slug=ids['copy'], history=True)
        decision = detail['as_member'][0]
        assert call(client, KEYS[2], 'memory_lifecycle_correct', decision_id=decision['id'], expected_revision=1,
                    reason='foreign') == (404, {'error': 'not_found'})
        status, corrected = call(client, KEYS[0], 'memory_lifecycle_correct', decision_id=decision['id'],
                                 expected_revision=decision['revision'], reason='mistaken merge')
        assert status == 200 and corrected['decision']['state'] == 'corrected'
    with db.connect(cfg) as conn:
        audit = conn.execute("SELECT op FROM audit_log WHERE op LIKE 'lifecycle%%' ORDER BY id").fetchall()
    assert [a['op'] for a in audit] == ['lifecycle_apply', 'lifecycle_correct']


def test_authority_revoked_before_commit_leaves_no_decision(lifecycle_store, tmp_path, monkeypatch):
    cfg, ids = lifecycle_store
    app, policy = app_fixture(tmp_path, cfg)
    from agentic_rag.service import context
    original = context.ServiceConnection.check_commit_authority

    def revoke_then_check(self):
        if self.authority_scope is not None and not self.authority_scope.read_only:
            policy.write_text(policy.read_text().replace('write_domains = ["alpha"]', 'write_domains = []'))
        return original(self)
    with TestClient(app, base_url='https://testserver') as client:
        status, seen = call(client, KEYS[0], 'memory_lifecycle_preview', member=ids['copy'], target=ids['keep'])
        monkeypatch.setattr(context.ServiceConnection, 'check_commit_authority', revoke_then_check)
        response = call(client, KEYS[0], 'memory_lifecycle_apply', member=ids['copy'], target=ids['keep'],
                        operation='exact_duplicate', reason='revoked', expected_member_version=seen['member']['version'],
                        expected_target_version=seen['target']['version'])
        assert response == (403, {'error': 'authorization_changed'})
    with db.connect(cfg) as conn:
        assert conn.execute("SELECT (SELECT count(*) FROM lifecycle_decisions)+(SELECT count(*) FROM lifecycle_events)"
                            "+(SELECT count(*) FROM audit_log WHERE op LIKE 'lifecycle%%') n").fetchone()['n'] == 0


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_local_and_central_cli_share_the_contract(lifecycle_store, tmp_path, monkeypatch, capsys):
    cfg, ids = lifecycle_store
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    code, out, err = run_cli(capsys, 'lifecycle', 'preview', ids['copy'], ids['keep'], '--json')
    assert code == 0, err
    seen = json.loads(out)
    code, out, err = run_cli(capsys, 'lifecycle', 'preview', ids['copy'], ids['keep'])
    assert code == 0 and 'exact_duplicate' in out and 'not proven' in out
    code, out, err = run_cli(capsys, 'lifecycle', 'apply', ids['copy'], ids['keep'], '--operation', 'exact_duplicate',
                             '--member-version', seen['member']['version'], '--target-version', seen['target']['version'],
                             '--reason', 'same plotter note', '--json')
    assert code == 0, err
    decision = json.loads(out)['decision']
    code, out, err = run_cli(capsys, 'search', 'plotter rolls', '--strategy', 'lexical', '--rerank', 'off',
                             '--project', '/projects/a', '--view', 'include_merged', '--json')
    assert code == 0 and {h['evidence']['lifecycle']['state'] for h in json.loads(out)['results']} == {'current', 'merged'}, err
    code, out, err = run_cli(capsys, 'get', ids['copy'], '--view', 'current', '--json')
    assert code == 0 and json.loads(out)['lifecycle']['canonical_id'] == ids['keep'], err
    code, out, err = run_cli(capsys, 'lifecycle', 'show', ids['copy'])
    assert code == 0 and 'hiding' in out and decision['id'] in out
    code, out, err = run_cli(capsys, 'lifecycle', 'history', ids['copy'], '--json')
    assert code == 0 and [e['event'] for e in json.loads(out)['items']] == ['applied']
    code, out, err = run_cli(capsys, 'lifecycle', 'apply', ids['foreign-copy'], ids['keep'], '--operation', 'exact_duplicate',
                             '--member-version', seen['member']['version'], '--target-version', seen['target']['version'],
                             '--reason', 'cross scope')
    assert code == 1 and 'scope_mismatch' in err
    # Central client mode reaches the same gateway through the service.
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
        code, out, err = run_cli(capsys, 'lifecycle', 'show', ids['copy'], '--json')
        assert code == 0 and json.loads(out)['as_member'][0]['id'] == decision['id'], err
        code, out, err = run_cli(capsys, 'search', 'plotter rolls', '--strategy', 'lexical', '--rerank', 'off',
                                 '--project', '/projects/a', '--view', 'current', '--json')
        assert code == 0 and [h['document_id'] for h in json.loads(out)['results']] == [ids['keep']], err
        code, out, err = run_cli(capsys, 'lifecycle', 'correct', decision['id'], '--revision', '1', '--reason', 'undo')
        assert code == 0 and 'corrected' in out, err
        code, out, err = run_cli(capsys, 'lifecycle', 'correct', decision['id'], '--revision', '1', '--reason', 'second')
        assert code == 1 and 'stale_version' in err
