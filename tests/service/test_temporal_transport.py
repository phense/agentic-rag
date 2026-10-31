"""RAG-064 T064-003: additive temporal options across local CLI/MCP, REST,
server MCP, the client MCP proxy and the remote CLI; legacy envelopes intact."""
from dataclasses import asdict, replace
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import cli, mcp_server, search, store
from agentic_rag.domains import add_domain, seed_defaults
from .test_api import app_fixture, headers, KEYS

R1 = '2026-10-30T10:00:00+01:00'
TEMPORAL = {'query': 'switch firmware rollback yesterday', 'temporal': 'filter', 'reference': R1,
            'timezone': 'Europe/Berlin'}
LEGACY = {'query': 'switch firmware rollback', 'domain': 'alpha', 'project': '/projects/a',
          'k': 5, 'context': 'off', 'rerank': 'off', 'as_of': R1}


@pytest.fixture
def temporal_store(conn, cfg, tmp_path, monkeypatch):
    seed_defaults(conn)
    conn.commit()
    add_domain(conn, 'alpha', 'Synthetic allowed domain', actor='test')
    add_domain(conn, 'beta', 'Synthetic foreign domain', actor='test')
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)
    docs = {}
    for name, domain, project, when in (
            ('allowed-yesterday', 'alpha', '/projects/a', '2026-10-29T10:00:00+01:00'),
            ('allowed-older', 'alpha', '/projects/a', '2026-09-01T10:00:00+02:00'),
            ('foreign-yesterday', 'beta', '/projects/b', '2026-10-29T11:00:00+01:00'),
            ('foreign-project', 'alpha', '/projects/b', '2026-10-29T12:00:00+01:00')):
        body = f'Switch firmware rollback {name}. Switch firmware rollback note.'
        docs[name] = store.save_claim(conn, cfg, title=name, body=body, domain=domain, dtype='memory',
            project=project, claim_kind='stated', evidence=[dict(namespace='synthetic', source_id=name, role='user',
                                                                 quote=body, timestamp=when, complete=True)]).doc_id
    conn.commit()
    config = tmp_path / 'local.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://127.0.0.1:1"\n'
                      '[rerank]\nurl = "http://127.0.0.1:1"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    return replace(cfg, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1'), docs, config


def mcp(**arguments):
    return mcp_server.memory_search(**arguments)


def test_local_mcp_legacy_envelope_and_explicit_options(temporal_store):
    cfg, docs, _ = temporal_store
    legacy = mcp(**LEGACY)
    assert set(legacy) == {'results', 'warnings'}
    assert legacy == mcp(**LEGACY, temporal='off') == mcp(**LEGACY, temporal='auto')
    assert all('temporal' not in hit['evidence'] for hit in legacy['results'])
    assert len(legacy['results']) == 2
    filtered = mcp(**{**LEGACY, **TEMPORAL})
    assert [h['document_id'] for h in filtered['results']] == [docs['allowed-yesterday']]
    assert filtered['temporal']['applied'] == 'filter' and filtered['results'][0]['evidence']['temporal']['match'] == 'inside'
    with pytest.raises(ValueError, match='temporal_filter_requires_interval'):
        mcp(**{**LEGACY, **TEMPORAL, 'query': 'switch firmware rollback'})
    with pytest.raises(ValueError, match='invalid_temporal_mode'):
        mcp(**LEGACY, temporal='strict')


def test_local_configuration_enables_auto_preference_and_old_configs_load(temporal_store, monkeypatch):
    cfg, docs, config = temporal_store
    config.write_text(config.read_text() + '\n[temporal]\nenabled = true\ntimezone = "Europe/Berlin"\n')
    preferred = mcp(**{**LEGACY, 'query': 'switch firmware rollback gestern'}, reference=R1)
    assert preferred['temporal']['mode'] == 'prefer' and preferred['temporal']['timezone'] == 'Europe/Berlin'
    assert preferred['results'][0]['document_id'] == docs['allowed-yesterday']
    config.write_text(config.read_text().replace('timezone = "Europe/Berlin"', 'timezone = "Nowhere/City"'))
    with pytest.raises(ValueError, match='invalid_timezone'):
        mcp(**LEGACY)


def test_local_cli_json_text_and_errors(temporal_store, capsys):
    cfg, docs, _ = temporal_store
    base = ['search', LEGACY['query'], '--domain', 'alpha', '--project', '/projects/a', '-k', '5',
            '--context', 'off', '--rerank', 'off', '--as-of', R1]
    assert cli.main(base + ['--json']) == 0
    legacy = json.loads(capsys.readouterr().out)
    assert set(legacy) == {'results', 'warnings'} and legacy == json.loads(json.dumps(mcp(**LEGACY)))
    timed = [TEMPORAL['query'] if a == LEGACY['query'] else a for a in base]
    assert cli.main(timed + ['--json', '--temporal', 'filter', '--reference', R1, '--timezone', 'Europe/Berlin']) == 0
    filtered = json.loads(capsys.readouterr().out)
    assert [h['document_id'] for h in filtered['results']] == [docs['allowed-yesterday']]
    assert filtered['temporal']['interval']['start'] == '2026-10-28T23:00:00+00:00'
    assert cli.main(timed + ['--temporal', 'prefer', '--reference', R1, '--timezone', 'Europe/Berlin']) == 0
    out = capsys.readouterr()
    assert out.out.splitlines()[0].split()[1] == filtered['results'][0]['slug']
    assert 'TEMPORAL: interval 2026-10-28T23:00:00+00:00 .. 2026-10-29T23:00:00+00:00 (Europe/Berlin), applied preference' in out.err
    assert cli.main(base + ['--temporal', 'filter', '--reference', '2026-10-30T10:00:00']) == 1
    assert 'invalid_reference' in capsys.readouterr().err
    assert cli.main(['search', 'switch firmware rollback', '--temporal', 'filter']) == 1
    assert 'temporal_filter_requires_interval' in capsys.readouterr().err


def test_rest_and_server_mcp_parity_scope_and_legacy_envelope(temporal_store, tmp_path):
    cfg, docs, _ = temporal_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        legacy = client.post('/v1/tools/memory_search', headers=headers(KEYS[0]), json=LEGACY)
        assert legacy.status_code == 200 and set(legacy.json()) == {'results', 'warnings'}
        rest = client.post('/v1/tools/memory_search', headers=headers(KEYS[0]), json={**LEGACY, **TEMPORAL})
        assert rest.status_code == 200, rest.text
        body = rest.json()
        assert [h['document_id'] for h in body['results']] == [docs['allowed-yesterday']]
        for foreign in ('foreign-yesterday', 'foreign-project'):
            assert docs[foreign] not in rest.text and docs[foreign] not in legacy.text
        assert body['temporal']['effect']['candidates'] == 2 and body['temporal']['applied'] == 'filter'
        rpc = client.post('/mcp/ro/', headers={**headers(KEYS[0]), 'accept': 'application/json, text/event-stream'},
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'memory_search', 'arguments': {**LEGACY, **TEMPORAL}}})
        assert rpc.status_code == 200, rpc.text
        result = rpc.json()['result']
        assert not result.get('isError'), rpc.text
        assert json.loads(result['content'][0]['text']) == body
        for bad in ({'temporal': 'strict'}, {'temporal': 'prefer', 'timezone': '../x'},
                    {'temporal': 'filter', 'query': 'switch firmware rollback', 'reference': R1}):
            response = client.post('/v1/tools/memory_search', headers=headers(KEYS[0]), json={**LEGACY, **bad})
            assert response.status_code == 400 and response.json()['error'] == 'invalid_arguments'


def test_client_mcp_proxy_omits_unrequested_options(temporal_store, monkeypatch):
    cfg, _, _ = temporal_store
    sent = []
    class Fake:
        def __init__(self, config): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def invoke(self, name, arguments): sent.append((name, arguments)); return {'results': [], 'warnings': []}
    from agentic_rag.service import client as remote
    import agentic_rag.config as config_module
    monkeypatch.setattr(remote, 'RemoteClient', Fake)
    monkeypatch.setattr(config_module, 'load_config', lambda *a: replace(cfg, service_mode='client'))
    server = mcp_server.build_server(True)
    import asyncio
    asyncio.run(server.call_tool('memory_search', {'query': 'switch firmware rollback'}))
    asyncio.run(server.call_tool('memory_search', {'query': 'switch firmware rollback gestern', 'temporal': 'prefer'}))
    assert sent[0][0] == 'memory_search' and not {'temporal', 'reference', 'timezone'} & set(sent[0][1])
    assert sent[0][1]['context'] == 'auto'
    assert sent[1][1]['temporal'] == 'prefer' and 'reference' not in sent[1][1]


def test_remote_cli_uses_service_and_sends_only_requested_options(temporal_store, tmp_path, monkeypatch, capsys):
    cfg, docs, _ = temporal_store
    app, _ = app_fixture(tmp_path, cfg)
    token = tmp_path / 'token'
    token.write_text(KEYS[0])
    token.chmod(0o600)
    client_cfg = replace(cfg, service_mode='client', service_url='https://testserver', service_token_file=token,
                         service_spool_dir=tmp_path / 'spool', db_name='no_local_database_access')
    monkeypatch.setattr(cli, 'load_config', lambda: client_cfg)
    from agentic_rag.service import client as remote
    original, bodies = remote.RemoteClient, []
    with TestClient(app, base_url='https://testserver') as sender:
        real = sender.stream
        def recording(method, url, **kw):
            if '/v1/tools/' in str(url) or '/v1/requests' in str(url):
                bodies.append(kw.get('json'))
            return real(method, url, **kw)
        monkeypatch.setattr(sender, 'stream', recording)
        monkeypatch.setattr(remote, 'RemoteClient', lambda c: original(c, sender=sender))
        base = ['search', LEGACY['query'], '--domain', 'alpha', '--project', '/projects/a', '-k', '5',
                '--context', 'off', '--rerank', 'off', '--as-of', R1, '--json']
        assert cli.main(base) == 0
        legacy = json.loads(capsys.readouterr().out)
        assert set(legacy) == {'results', 'warnings'} and len(legacy['results']) == 2
        timed = [TEMPORAL['query'] if a == LEGACY['query'] else a for a in base]
        assert cli.main(timed + ['--temporal', 'filter', '--reference', R1, '--timezone', 'Europe/Berlin']) == 0
        filtered = json.loads(capsys.readouterr().out)
    assert [h['document_id'] for h in filtered['results']] == [docs['allowed-yesterday']]
    assert filtered['temporal']['applied'] == 'filter'
    payloads = [p.get('arguments', p) for p in bodies if isinstance(p, dict)]
    searches = [p for p in payloads if str(p.get('query', '')).startswith(LEGACY['query'])]
    assert len(searches) == 2
    assert not {'temporal', 'reference', 'timezone'} & set(searches[0])
    assert searches[1]['temporal'] == 'filter' and searches[1]['reference'] == R1
