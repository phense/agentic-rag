"""RAG-063 T063-005: local and central CLI evidence/history and strict options."""
from dataclasses import replace
import json

import pytest
from starlette.testclient import TestClient

from agentic_rag import cli, db
from agentic_rag import evidence_contract as contract
from .test_api import app_fixture, KEYS
from .test_evidence_transports import evidence_store, local_view  # noqa: F401  (fixture)


@pytest.fixture
def local_cli(evidence_store, tmp_path, monkeypatch):
    cfg = evidence_store[0]
    config = tmp_path / 'local.toml'
    config.write_text(f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://localhost:1"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    return evidence_store


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_local_show_history_json_and_readable_text(local_cli, capsys):
    cfg, own, foreign, shared_key, own_key = local_cli
    code, out, _ = run(capsys, 'evidence', 'show', own, '--json')
    assert code == 0 and json.loads(out) == json.loads(json.dumps(local_view(cfg, own), default=str))
    code, out, _ = run(capsys, 'evidence', 'show', own, '--limit', '1')
    assert code == 0
    assert 'Version: ev1:' in out and ('Shared synthetic statement' in out or 'Own synthetic statement' in out)
    assert 'Trust: active' in out and 'Next page: --cursor ' in out and 'Independent verification: no' in out
    assert 'private.jsonl' not in out and 'event-1' not in out
    code, out, _ = run(capsys, 'evidence', 'history', own, '--source', shared_key, '--json')
    assert code == 0 and json.loads(out)['scope'] == 'source'
    code, out, err = run(capsys, 'evidence', 'show', foreign + 'x')
    assert code == 1 and 'evidence_unavailable' in err


def test_local_strict_and_legacy_writes(local_cli, capsys):
    cfg, own, foreign, shared_key, own_key = local_cli
    seen = local_view(cfg, own)
    code, out, _ = run(capsys, 'evidence', 'review', own, '--state', 'unreviewed', '--reason', 'legacy cli')
    assert code == 0 and out.strip() == 'evidence state saved'
    code, _, err = run(capsys, 'evidence', 'review', own, '--state', 'confirmed', '--reason', 'stale',
                       '--expected-version', seen['version'])
    assert code == 1 and 'evidence_conflict' in err
    fresh = local_view(cfg, own)
    code, out, _ = run(capsys, 'evidence', 'review', own, '--state', 'confirmed', '--reason', 'checked',
                       '--expected-version', fresh['version'])
    assert code == 0 and 'New version: ev1:' in out
    item = next(i for i in local_view(cfg, own)['sources']['items'] if i['source_key'] == own_key)
    code, out, _ = run(capsys, 'evidence', 'source-state', own_key, '--state', 'removed', '--reason', 'withdrawn',
                       '--document', own, '--expected-version', item['source_version'])
    assert code == 0 and 'New source version: src1:' in out
    code, _, err = run(capsys, 'evidence', 'source-state', own_key, '--state', 'active', '--reason', 'x', '--document', own)
    assert code == 1
    with db.connect(cfg) as conn:
        actors = {r['actor'] for r in conn.execute("SELECT actor FROM audit_log WHERE op IN ('claim_review','source_state')")}
    assert actors == {'cli'}


def test_central_cli_uses_service_with_same_contract_and_conflicts(evidence_store, tmp_path, monkeypatch, capsys):
    cfg, own, foreign, shared_key, own_key = evidence_store
    expected = local_view(cfg, own)
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
        code, out, _ = run(capsys, 'evidence', 'show', own, '--json')
        assert code == 0 and json.loads(out)['version'] == expected['version']
        code, _, err = run(capsys, 'evidence', 'show', foreign, '--json')
        assert code == 1 and 'evidence_unavailable' in err
        code, _, err = run(capsys, 'evidence', 'review', own, '--state', 'confirmed', '--reason', 'stale',
                           '--expected-version', 'ev1:' + '0' * 64)
        assert code == 1 and 'evidence_conflict' in err
        code, out, _ = run(capsys, 'evidence', 'review', own, '--state', 'confirmed', '--reason', 'central check',
                           '--expected-version', expected['version'])
        assert code == 0 and 'New version: ev1:' in out
        code, out, _ = run(capsys, 'evidence', 'history', own, '--json')
        assert code == 0 and json.loads(out)['items'][0]['concurrency'] == 'strict'
    with db.connect(cfg) as conn:
        row = conn.execute("SELECT actor,inspected_version FROM claim_history WHERE operation='review'").fetchone()
    assert row == {'actor': 'service:machine:alice:vm1', 'inspected_version': expected['version']}
