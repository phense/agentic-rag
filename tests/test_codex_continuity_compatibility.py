"""Code-only continuity repair on populated, owned018/019 installations."""
import json
import subprocess

import pytest

from agentic_rag import db, jobs
from agentic_rag.continuity import capture, enrich, store
from agentic_rag.continuity.model import CheckpointSnapshot, ENRICHMENT_FIELDS
from agentic_rag.hooks.session_start import build_context
from scripts.verify_contextual_indexing import snapshot, verified_backup
from test_maintenance_restore import owned_source
from test_transcript_codex import message, write


@pytest.mark.parametrize("schema", [18, 19])
def test_pending_legacy_job_enriches_through_gateway_and_restores_without_migration(tmp_path, schema):
    transcript = write(tmp_path / "rollout.jsonl", message("user", "Fix the public parser"),
                       message("assistant", "Next run focused checks"))
    expected = {field: ("" if field in ("goal", "next_action") else []) for field in ENRICHMENT_FIELDS}
    expected.update(goal="Fix the public parser", next_action="Run focused checks")
    calls = []

    def runner(cmd, **kwargs):
        prompt = cmd[cmd.index("-p") + 1]
        assert "Fix the public parser" in prompt
        calls.append(1)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(expected), stderr="")

    with owned_source(tmp_path, schema) as cfg:
        with db.connect(cfg) as conn:
            old = store.upsert_snapshot(conn, CheckpointSnapshot(
                session_id="public-codex", turn_id="turn-one", cursor="event:legacy-fallback",
                source="PreCompact", trigger="auto", cwd=None, project_root=None))
            jobs.enqueue_checkpoint_enrichment(conn, checkpoint_id=old.id, session_id=old.session_id,
                transcript_path=str(transcript), after_cursor="event:legacy-predecessor")
            tables = [r['tablename'] for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('audit_log','continuation_checkpoints','mining_queue') ORDER BY tablename")]
            before = snapshot(conn, tables)
            job = conn.execute("SELECT * FROM mining_queue WHERE kind='checkpoint_enrich'").fetchone()
            conn.rollback()
        backup = verified_backup(cfg, tmp_path / "source.dump")
        assert backup['all_public_table_rows_match'] and backup['application_table_privileges_match']
        with db.connect(cfg, role="writer") as writer:
            cursor = enrich.enrich_checkpoint(writer, cfg, job, runner)
            assert cursor.startswith("codex-event-v1:")
        with db.connect(cfg, role="reader") as reader:
            context = build_context(reader, cfg, None, old.session_id, "compact")
            assert "Fix the public parser" in context
            assert "Run focused checks" in context
            assert "Preserve public backup evidence" in context
            assert "programming" in context and "general" in context
        with db.connect(cfg) as conn:
            assert store.get(conn, old.id).quality == "enriched"
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='checkpoint_enriched'").fetchone()['n'] == 1
            # No queue requeue or bulk rewrite is part of the repair.
            assert conn.execute("SELECT * FROM mining_queue WHERE id=%s", (job['id'],)).fetchone() == job
            new = store.upsert_snapshot(conn, capture.capture_snapshot_seed({
                "session_id": old.session_id, "turn_id": "turn-two", "hook_event_name": "PreCompact",
                "trigger": "auto", "transcript_path": str(transcript)}))
            assert new.cursor == cursor
            assert new.predecessor_cursor == old.cursor
            assert store.get(conn, old.id).state == "superseded"
            assert store.get(conn, old.id).enrichment == expected
            conn.rollback()
            assert snapshot(conn, tables) == before
        with db.connect(cfg, role="reader") as reader:
            # Real renderer on the persisted legacy checkpoint; no provider call.
            context = build_context(reader, cfg, None, old.session_id, "startup")
            # The newer snapshot has not been enriched, so compact restoration
            # appropriately labels it pending; the archived enriched row survives.
            assert "semantic enrichment pending" in context
            assert "Preserve public backup evidence" in context
            assert "programming" in context
            assert "general" in context
        assert len(calls) == 1
