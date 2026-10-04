"""Rehearsal helpers must refuse canonical writes and preserve measured identity."""
from dataclasses import replace
import pytest
from agentic_rag.config import Config, load_config
from scripts import verify_incremental_ingestion as verify


def test_child_refuses_canonical_database_before_any_connection(monkeypatch):
    monkeypatch.setattr(verify, 'load_config', lambda: Config())
    monkeypatch.setattr(verify.db, 'connect', lambda *a, **k: pytest.fail('canonical DB accessed'))
    with pytest.raises(ValueError, match='owned'):
        verify.child_main(['edit', '0'])


def test_child_config_preserves_model_and_relevant_options(tmp_path):
    cfg=replace(Config(),embed_model='alternate:tag',dedup_threshold=.82,
        mine_max_digest_chars=24000,worker_backoff_seconds=17)
    path=verify.config_file(cfg,tmp_path/'config.toml')
    assert load_config(path)==cfg
    assert path.stat().st_mode & 0o077 == 0
