"""One status snapshot for `rag status` and the SessionStart hook."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# module attribute (not a re-read from backup) so tests can monkeypatch
# status.WARNING_STATE independently
from .backup import WARNING_STATE
from .config import Config
from . import provider_health


@dataclass(frozen=True)
class QueueErrorInfo:
    id: int
    kind: str
    session_id: str | None
    attempts: int
    last_error: str | None


@dataclass(frozen=True)
class StatusReport:
    documents: list[dict]
    queue: list[dict]
    queue_errors: list[QueueErrorInfo] = field(default_factory=list)
    last_backup: str | None = None
    backup_warning: str | None = None
    last_curation_at: datetime | None = None
    provider_health: provider_health.ProviderHealth | None = None
    oldest_open_mine_at: datetime | None = None
    open_checkpoints: int = 0
    newest_checkpoint_at: datetime | None = None
    newest_checkpoint_quality: str | None = None
    newest_checkpoint_project: str | None = None
    pending_checkpoint_enrichments: int = 0
    oldest_pending_checkpoint_enrichment_at: datetime | None = None
    oldest_pending_checkpoint_enrichment_age: timedelta | None = None
    checkpoint_warnings: tuple[str, ...] = ()


def _checkpoint_health(conn, cfg: Config) -> dict:
    open_row = conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints "
        "WHERE state = 'open'"
    ).fetchone()
    newest = conn.execute(
        "SELECT updated_at, quality, project_root "
        "FROM continuation_checkpoints WHERE state = 'open' "
        "ORDER BY updated_at DESC, id DESC LIMIT 1"
    ).fetchone()
    pending = conn.execute(
        "SELECT count(*) AS n, min(enqueued_at) AS oldest_at "
        "FROM mining_queue WHERE kind = 'checkpoint_enrich' "
        "AND status = 'pending'"
    ).fetchone()

    now = datetime.now(timezone.utc)
    newest_at = newest["updated_at"] if newest else None
    oldest_pending_at = pending["oldest_at"] if pending else None
    oldest_pending_age = (
        now - oldest_pending_at if oldest_pending_at is not None else None
    )
    warnings = []
    if (
        newest_at is not None
        and now - newest_at > timedelta(days=cfg.stale_days)
    ):
        warnings.append(
            f"newest open checkpoint is stale (>{cfg.stale_days} days)"
        )
    if (
        oldest_pending_age is not None
        and oldest_pending_age
        > timedelta(seconds=cfg.worker_backoff_seconds)
    ):
        warnings.append(
            "checkpoint enrichment pending longer than configured worker "
            f"backoff ({cfg.worker_backoff_seconds}s)"
        )
    return {
        "open_checkpoints": int(open_row["n"] if open_row else 0),
        "newest_checkpoint_at": newest_at,
        "newest_checkpoint_quality": newest["quality"] if newest else None,
        "newest_checkpoint_project": newest["project_root"] if newest else None,
        "pending_checkpoint_enrichments": int(pending["n"] if pending else 0),
        "oldest_pending_checkpoint_enrichment_at": oldest_pending_at,
        "oldest_pending_checkpoint_enrichment_age": oldest_pending_age,
        "checkpoint_warnings": tuple(warnings),
    }


def gather_status(conn, cfg: Config) -> StatusReport:
    documents = [dict(r) for r in conn.execute(
        "SELECT domain, status, count(*) AS n FROM documents"
        " GROUP BY domain, status ORDER BY domain, status").fetchall()]
    queue = [dict(r) for r in conn.execute(
        "SELECT kind, status, count(*) AS n FROM mining_queue"
        " GROUP BY kind, status ORDER BY kind, status").fetchall()]
    queue_errors = [
        QueueErrorInfo(r["id"], r["kind"], r["session_id"], r["attempts"],
                       r["last_error"])
        for r in conn.execute(
            "SELECT id, kind, session_id, attempts, last_error"
            " FROM mining_queue WHERE status = 'error' ORDER BY id"
        ).fetchall()
    ]
    row = conn.execute(
        "SELECT max(at) AS at FROM audit_log WHERE op = 'curation_pass'"
    ).fetchone()
    last_curation_at = row["at"] if row else None
    open_row = conn.execute(
        "SELECT min(enqueued_at) AS at FROM mining_queue"
        " WHERE kind = 'mine'"
        " AND status IN ('pending', 'processing', 'error')"
    ).fetchone()
    oldest_open_mine_at = open_row["at"] if open_row else None
    dumps = sorted(cfg.backup_local_dir.glob("*.dump"), reverse=True)
    last_backup = dumps[0].name if dumps else None
    backup_warning = None
    if WARNING_STATE.exists():
        backup_warning = WARNING_STATE.read_text().strip()
    checkpoint_health = _checkpoint_health(conn, cfg)
    return StatusReport(
        documents, queue, queue_errors, last_backup, backup_warning,
        last_curation_at, provider_health.read_health(), oldest_open_mine_at,
        **checkpoint_health,
    )
