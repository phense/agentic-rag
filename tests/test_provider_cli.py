"""Operator inspection never opens a DB or sends content to a provider."""
import json

import pytest

from agentic_rag import cli, db


def test_provider_inspect_is_offline_without_database_or_credentials(tmp_path, monkeypatch, capsys):
    config = tmp_path / 'config.toml'
    config.write_text('''[llm]
provider = "claude"
model = "haiku"
''')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    monkeypatch.setattr(db, 'connect', lambda *a, **k: pytest.fail('inspection opened database'))
    assert cli.main(['providers', 'inspect']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['mode'] == 'offline-inspection'
    assert output['extraction']['provider'] == 'claude'
    assert output['profiles'] == {}
    assert output['corpus_requests'] == 0


def _profile_config(tmp_path, monkeypatch, url='https://models.example.invalid'):
    config = tmp_path / 'profiles.toml'
    config.write_text(f'''[embedding_profiles.small]
provider = "openai-compatible"
model = "small-v1"
revision = "small-v1"
url = "{url}"
dimensions = 3
credential_env = "SYNTHETIC_MISSING_TOKEN"
''')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    return config


def test_external_probe_requires_explicit_egress_before_any_network(tmp_path, monkeypatch, capsys):
    from agentic_rag import providers
    _profile_config(tmp_path, monkeypatch)
    monkeypatch.setattr(providers, 'verify_profile', lambda *a: pytest.fail('unapproved provider call'))
    assert cli.main(['providers', 'probe', 'small']) == 1
    assert 'allow_egress' in capsys.readouterr().err


def test_offline_inspection_shows_egress_limits_without_reading_secret(tmp_path, monkeypatch, capsys):
    from agentic_rag import providers
    _profile_config(tmp_path, monkeypatch)
    monkeypatch.setattr(providers, '_token', lambda *a: pytest.fail('inspection read credential'))
    assert cli.main(['providers', 'inspect']) == 0
    profile = json.loads(capsys.readouterr().out)['profiles']['small']
    assert profile['external_egress'] is True
    assert profile['max_requests_per_batch'] == 3
    assert profile['max_total_input_chars'] == 128000
    assert profile['fallback'] is False


def test_extraction_probe_requires_explicit_external_choice(tmp_path, monkeypatch, capsys):
    from agentic_rag import providers
    config = tmp_path / 'config.toml'
    config.write_text('[llm]\nprovider="claude"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    monkeypatch.setattr(providers, 'probe_llm', lambda *a: pytest.fail('unapproved CLI extraction call'))
    assert cli.main(['providers', 'probe-extraction']) == 1
    assert 'allow_egress' in capsys.readouterr().err


def test_index_commands_reject_client_administration_and_implicit_corpus(tmp_path, monkeypatch, capsys):
    config = tmp_path / 'client.toml'
    config.write_text('[service]\nmode="client"\nurl="https://service.example.invalid"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG', str(config))
    monkeypatch.setattr(db, 'connect', lambda *a, **k: pytest.fail('client administration opened local DB'))
    assert cli.main(['index', 'status']) == 1
    assert 'local_database_owner' in capsys.readouterr().err
    config.write_text('')
    assert cli.main(['index', 'build', 'next-space']) == 1
    assert 'allow_corpus' in capsys.readouterr().err


def test_cli_build_dryrun_is_readonly_and_requires_no_credential(conn, cfg, tmp_path, monkeypatch, capsys):
    from agentic_rag import indexes, providers
    config = _profile_config(tmp_path, monkeypatch)
    config.write_text(f'[db]\nname="{cfg.db_name}"\n' + config.read_text())
    monkeypatch.setattr(providers, 'verify_identity', lambda p: p.identity)
    from agentic_rag.config import load_config
    configured = load_config()
    indexes.create(conn, configured, 'next-space', 'small')
    conn.commit()
    monkeypatch.setattr(providers, '_token', lambda *a: pytest.fail('dry-run read credentials'))
    monkeypatch.setattr(providers, 'embed_profile', lambda *a: pytest.fail('dry-run sent corpus'))
    before = conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    conn.rollback()
    assert cli.main(['index', 'build', 'next-space', '--dry-run']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['mode'] == 'build-dry-run' and result['corpus_requests'] == 0
    assert result['profile']['external_egress'] is True
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n'] == before
