"""One status snapshot for `rag status` and the SessionStart hook."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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
    return StatusReport(
        documents, queue, queue_errors, last_backup, backup_warning,
        last_curation_at, provider_health.read_health(), oldest_open_mine_at)
