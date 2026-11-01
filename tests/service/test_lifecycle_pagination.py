"""Public lifecycle history must advance; bounded detail must signal overflow."""
import json

from starlette.testclient import TestClient

from agentic_rag import cli, db, lifecycle, store
from .test_api import KEYS, app_fixture, headers
from .test_lifecycle_transports import call, lifecycle_store, run_cli


def apply_copy(conn, cfg, ids, *, operation='exact_duplicate', reason='paging'):
    seen = lifecycle.preview(conn, ids['copy'], ids['keep'], operation=operation)
    conn.rollback()
    return store.apply_lifecycle(conn, cfg, member=ids['copy'], target=ids['keep'], operation=operation,
        expected_member_version=seen['member']['version'], expected_target_version=seen['target']['version'],
        reason=reason)


def test_public_history_cursor_advances_rest_mcp_and_cli(lifecycle_store, tmp_path, monkeypatch, capsys):
    cfg, ids = lifecycle_store
    with db.connect(cfg) as writer:
        for n in range(3):
            made = apply_copy(writer, cfg, ids, reason=f'apply {n}')
            if n < 2:
                store.correct_lifecycle(writer, cfg, decision_id=made['decision']['id'], expected_revision=1,
                                        reason=f'correct {n}')
    app, _ = app_fixture(tmp_path, cfg)

    def pages(fetch):
        seen, cursor = [], None
        for _ in range(4):
            page = fetch(cursor)
            ids_in_page = [item['id'] for item in page['items']]
            assert not set(seen).intersection(ids_in_page), 'history cursor repeated an earlier page'
            seen.extend(ids_in_page)
            if not page['more']:
                assert page['cursor'] is None
                break
            assert page['cursor'] and len(ids_in_page) == 2
            cursor = page['cursor']
        assert len(seen) == 5 and len(set(seen)) == 5
        return seen

    with TestClient(app, base_url='https://testserver') as client:
        def rest(cursor):
            status, result = call(client, KEYS[0], 'memory_lifecycle', id_or_slug=ids['copy'],
                                  history=True, cursor=cursor, limit=2)
            assert status == 200, result
            return result['history']

        expected = pages(rest)

        def mcp(cursor):
            response = client.post('/mcp/ro/',
                headers={**headers(KEYS[0]), 'accept': 'application/json, text/event-stream'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                      'params': {'name': 'memory_lifecycle', 'arguments': {
                          'id_or_slug': ids['copy'], 'history': True, 'cursor': cursor, 'limit': 2}}})
            assert response.status_code == 200, response.text
            result = response.json()['result']
            return (result.get('structuredContent') or json.loads(result['content'][0]['text']))['history']

        assert pages(mcp) == expected
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)

    def local_cli(cursor):
        arguments = ['lifecycle', 'history', ids['copy'], '--limit', '2', '--json']
        if cursor:
            arguments.extend(['--cursor', cursor])
        code, out, err = run_cli(capsys, *arguments)
        assert code == 0, err
        return json.loads(out)

    assert pages(local_cli) == expected


def test_member_detail_signals_older_relationships(lifecycle_store):
    cfg, ids = lifecycle_store
    with db.connect(cfg) as writer:
        for n in range(21):
            made = apply_copy(writer, cfg, ids, reason=f'apply {n}')
            store.correct_lifecycle(writer, cfg, decision_id=made['decision']['id'], expected_revision=1,
                                    reason=f'correct {n}')
        apply_copy(writer, cfg, ids, reason='current decision')
    with db.connect(cfg, role='reader') as reader:
        result = lifecycle.detail(reader, ids['copy'])
    assert len(result['as_member']) == 20
    assert result.get('as_member_more') is True


def test_playbook_integrity_allows_contested_relationships(lifecycle_store):
    from .test_lifecycle_playbook import integrity
    cfg, ids = lifecycle_store
    with db.connect(cfg) as writer:
        apply_copy(writer, cfg, {**ids, 'copy': ids['keep'], 'keep': ids['copy']},
                   operation='contradiction', reason='record a disagreement')
        apply_copy(writer, cfg, ids, reason='record the justified exact copy')
    result = integrity(cfg)
    assert result['decisions'] == 2
    assert result['chains'] == 0
    assert result['events_minus_audit'] == 0
