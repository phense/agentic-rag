"""Populated schema026 provider-index upgrades preserve every original row."""
from dataclasses import replace

import pytest

from agentic_rag import db, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from test_maintenance_restore import owned_source


@pytest.mark.parametrize('mode', ['local', 'central'])
def test_populated026_provider_upgrade_strict_restore_and_retry(tmp_path, monkeypatch, mode):
    from agentic_rag import query_cache
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    with owned_source(tmp_path, 26) as cfg:
        with db.connect(cfg) as conn:
            conn.execute("INSERT INTO mining_queue(kind,session_id,transcript_path) VALUES ('mine','provider-upgrade-pending','/synthetic/source.jsonl')")
            before_ids = conn.execute('SELECT id FROM documents ORDER BY id').fetchall()
        original = upgrade.inventory(cfg, '0.6.13', identities=True)
        assert len(original['migrations']) == 26
        if mode == 'local':
            result = upgrade.local_upgrade(cfg, '0.6.13', tmp_path / 'provider.dump',
                apply=True, writers_stopped=True)
            assert result['migrations_applied'] == ['027_provider_indexes.sql','028_reranker_settings.sql','029_source_evidence.sql','030_pattern_synthesis.sql','031_memory_lifecycle.sql','032_extraction_policy.sql', '033_trusted_replacements.sql']
            assert result['restore_verified'] and result['original_rows_unchanged']
            assert upgrade.verify_preserved(cfg, original)['unchanged']
            with db.connect(cfg) as conn:
                assert conn.execute('SELECT id FROM documents ORDER BY id').fetchall() == before_ids
            retry = upgrade.local_upgrade(cfg, '0.6.13', tmp_path / 'retry.dump',
                apply=True, writers_stopped=True)
            assert retry['migrations_applied'] == []
        else:
            proof = upgrade.verified_backup(cfg, '0.6.13', tmp_path / 'provider.dump')
            with isolated_database(cfg, initialize=False) as target:
                target = replace(target, ollama_url=cfg.ollama_url)
                result = upgrade.restore_target(target, tmp_path / 'provider.dump',
                    proof['manifest'], apply=True)
                assert result['migrations_applied'] == ['027_provider_indexes.sql','028_reranker_settings.sql','029_source_evidence.sql','030_pattern_synthesis.sql','031_memory_lifecycle.sql','032_extraction_policy.sql', '033_trusted_replacements.sql']
                assert result['restore_verified'] and result['original_rows_unchanged']
                with db.connect(target) as conn:
                    assert conn.execute('SELECT id FROM documents ORDER BY id').fetchall() == before_ids
                assert upgrade.restore_target(target, tmp_path / 'provider.dump',
                    proof['manifest'], apply=True, resume=True)['resumed']
        # Central restore never changes its source. Local migration changes only
        # additive schema/migration metadata, checked above against the manifest.
        if mode == 'central':
            assert upgrade.inventory(cfg, '0.6.13')['tables'] == original['tables']
