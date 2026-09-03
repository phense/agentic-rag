from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentic_rag import jobs, provider_health, status
from agentic_rag.config import Config
from agentic_rag.continuity import store
from agentic_rag.continuity.model import CheckpointSnapshot


def _snapshot(*, session_id="s", cursor="u1", project_root="/project"):
    return CheckpointSnapshot(
        session_id=session_id,
        turn_id="turn-1",
        cursor=cursor,
        source="PreCompact",
        trigger="auto",
        cwd=project_root,
        project_root=project_root,
    )


def test_gather_status_counts_docs_and_queue(conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('s1', 'd', 'memory', 'T')")
    conn.execute(
        "INSERT INTO mining_queue(kind, session_id, status, attempts,"
        " last_error) VALUES ('mine', 'sess-1', 'error', 3, 'boom')")
    conn.commit()
    cfg2 = Config(db_name=cfg.db_name, backup_local_dir=tmp_path)
    rep = status.gather_status(conn, cfg2)
    assert {"domain": "d", "status": "active", "n": 1} in rep.documents
    assert {"kind": "mine", "status": "error", "n": 1} in rep.queue
    assert rep.queue_errors[0].last_error == "boom"
    assert rep.last_backup is None
    assert rep.backup_warning is None


def test_gather_status_surfaces_backup_warning(conn, cfg, tmp_path, monkeypatch):
    warn = tmp_path / "backup_warning"
    warn.write_text("2026-07-05 cloud not mounted")
    monkeypatch.setattr(status, "WARNING_STATE", warn)
    cfg2 = Config(db_name=cfg.db_name, backup_local_dir=tmp_path)
    rep = status.gather_status(conn, cfg2)
    assert "cloud not mounted" in rep.backup_warning


def test_gather_status_reports_last_backup_name(conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    (tmp_path / "agentic_rag-20260701-030000.dump").write_bytes(b"x")
    cfg2 = Config(db_name=cfg.db_name, backup_local_dir=tmp_path)
    rep = status.gather_status(conn, cfg2)
    assert rep.last_backup == "agentic_rag-20260701-030000.dump"


def test_gather_status_includes_provider_health_and_oldest_open_mine(
        conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(provider_health, "HEALTH_PATH", health)
    provider_health.record_failure("codex", "login required", path=health)
    conn.execute(
        "INSERT INTO mining_queue(kind, session_id, status, enqueued_at)"
        " VALUES ('mine', 'old', 'pending', now() - interval '2 hours'),"
        "        ('mine', 'new', 'pending', now() - interval '1 hour')")
    conn.commit()
    cfg2 = Config(db_name=cfg.db_name, backup_local_dir=tmp_path)
    rep = status.gather_status(conn, cfg2)
    assert rep.provider_health.provider == "codex"
    assert rep.provider_health.available is False
    assert rep.oldest_open_mine_at is not None
    assert rep.oldest_open_mine_at < rep.provider_health.last_failure_at


def test_gather_status_reports_checkpoint_freshness(conn, cfg, tmp_path,
                                                     monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    checkpoint = store.upsert_snapshot(conn, _snapshot())
    jobs.enqueue_checkpoint_enrichment(
        conn,
        checkpoint_id=checkpoint.id,
        session_id="s",
        transcript_path="/transcript.jsonl",
        after_cursor=None,
    )

    rep = status.gather_status(conn, cfg)

    assert rep.open_checkpoints == 1
    assert rep.pending_checkpoint_enrichments == 1
    assert rep.newest_checkpoint_at == checkpoint.updated_at
    assert rep.newest_checkpoint_quality == "snapshot"
    assert rep.newest_checkpoint_project == "/project"
    assert rep.oldest_pending_checkpoint_enrichment_at is not None


def test_gather_status_has_no_checkpoint_warning_when_none_exist(
        conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")

    rep = status.gather_status(conn, cfg)

    assert rep.open_checkpoints == 0
    assert rep.pending_checkpoint_enrichments == 0
    assert rep.checkpoint_warnings == ()


def test_gather_status_warns_for_configured_stale_and_pending_conditions(
        conn, cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(status, "WARNING_STATE", tmp_path / "absent")
    checkpoint = store.upsert_snapshot(conn, _snapshot())
    old = datetime.now(timezone.utc) - timedelta(days=cfg.stale_days + 1)
    conn.execute(
        "UPDATE continuation_checkpoints SET updated_at = %s WHERE id = %s",
        (old, checkpoint.id),
    )
    jobs.enqueue_checkpoint_enrichment(
        conn,
        checkpoint_id=checkpoint.id,
        session_id="s",
        transcript_path="/transcript.jsonl",
        after_cursor=None,
    )
    pending_old = datetime.now(timezone.utc) - timedelta(
        seconds=cfg.worker_backoff_seconds + 1
    )
    conn.execute(
        "UPDATE mining_queue SET enqueued_at = %s "
        "WHERE kind = 'checkpoint_enrich'",
        (pending_old,),
    )
    conn.commit()

    rep = status.gather_status(conn, cfg)

    assert any("stale" in warning for warning in rep.checkpoint_warnings)
    assert any("pending" in warning for warning in rep.checkpoint_warnings)
