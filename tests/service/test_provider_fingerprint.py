"""Setup verification must expire when either independent provider slot changes."""
from dataclasses import replace

from agentic_rag.config import Config
from agentic_rag.service.dashboard_views import fingerprint


def test_extraction_endpoint_and_credential_rotation_expire_setup(tmp_path, monkeypatch):
    policy = tmp_path / 'policy.json'
    policy.write_text('{}')
    policy.chmod(0o600)
    cfg = Config(llm_provider='openai-compatible', llm_model='extract-v1',
        llm_revision='extract-v1', llm_url='https://first.example.invalid',
        llm_credential_env='SYNTHETIC_SETUP_KEY')
    monkeypatch.setenv('SYNTHETIC_SETUP_KEY', 'synthetic-initial-value')
    initial = fingerprint(cfg, policy)
    assert fingerprint(replace(cfg, llm_url='https://second.example.invalid'), policy) != initial
    monkeypatch.setenv('SYNTHETIC_SETUP_KEY', 'synthetic-rotated-value')
    assert fingerprint(cfg, policy) != initial
