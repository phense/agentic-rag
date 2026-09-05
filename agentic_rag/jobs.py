"""mining_queue plumbing for hooks and the worker. Import-light by design:
hooks load this + psycopg only — never llm/mining/curation.

Debounce design (spec §6 'batched'): Stop fires after EVERY assistant turn,
so a naive enqueue would cost one Haiku call per turn. Instead: at most one
open mine job per session; a new job becomes due mine_debounce_seconds in
the future; last_uuid carries over from the session's last completed job so
each drain mines only the delta. A session's tail (turns after the last
drain) is picked up by the next worker spawn on the machine — any Stop or
any SessionStart with due jobs.
"""
from __future__ import annotations

import json
from datetime import datetime

from .config import Config


_LEGACY_PROVIDER_FAILURE_SQL = """
kind = 'mine'
AND status = 'error'
AND (
    last_error LIKE 'claude binary not found (%'
    OR last_error LIKE 'claude exited 1:%'
)
"""


def _serialize_enqueue(conn) -> None:
    """Transaction-scoped advisory lock: INSERT..WHERE NOT EXISTS alone is
    NOT race-safe under READ COMMITTED — two concurrent connections can
    both pass the NOT EXISTS snapshot and both insert. The lock serializes
    enqueues across connections; it releases automatically at COMMIT."""
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('mining_queue_enqueue'))")


def enqueue_mine(conn, cfg: Config, *, session_id: str, transcript_path: str,
                 project: str | None) -> bool:
    _serialize_enqueue(conn)
    open_job = conn.execute(
        "SELECT id FROM mining_queue WHERE session_id=%s AND kind='mine'"
        " AND status IN ('pending','processing') FOR UPDATE", (session_id,)).fetchone()
    if open_job:
        conn.execute("UPDATE mining_queue SET payload=payload ||"
                     " '{\"rerun_requested\":true}'::jsonb WHERE id=%s", (open_job["id"],))
        conn.commit()
        return False
    n = conn.execute(
        "INSERT INTO mining_queue"
        " (kind, session_id, transcript_path, payload, last_uuid,"
        "  next_attempt_at)"
        " SELECT 'mine', %(sid)s, %(path)s, %(payload)s,"
        "        (SELECT last_uuid FROM mining_queue"
        "          WHERE session_id = %(sid)s AND kind = 'mine'"
        "          AND status = 'done' ORDER BY id DESC LIMIT 1),"
        "        now() + make_interval(secs => %(debounce)s)"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM mining_queue WHERE session_id = %(sid)s"
        "   AND kind = 'mine' AND status IN ('pending', 'processing'))",
        {"sid": session_id, "path": transcript_path,
         "payload": json.dumps({"project": project}),
         "debounce": cfg.mine_debounce_seconds},
    ).rowcount
    conn.commit()
    return bool(n)


def enqueue_curate(conn, *, reason: str) -> bool:
    _serialize_enqueue(conn)
    n = conn.execute(
        "INSERT INTO mining_queue (kind, payload)"
        " SELECT 'curate', %(payload)s"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM mining_queue WHERE kind = 'curate'"
        "   AND status IN ('pending', 'processing'))",
        {"payload": json.dumps({"reason": reason})},
    ).rowcount
    conn.commit()
    return bool(n)


def enqueue_checkpoint_enrichment(
        conn, *, checkpoint_id: str, session_id: str,
        transcript_path: str, after_cursor: str | None) -> bool:
    """Enqueue one semantic pass for a checkpoint, idempotently."""
    _serialize_enqueue(conn)
    n = conn.execute(
        "INSERT INTO mining_queue"
        " (kind, session_id, transcript_path, payload, last_uuid)"
        " SELECT 'checkpoint_enrich', %(sid)s, %(path)s, %(payload)s, %(cursor)s"
        " WHERE NOT EXISTS ("
        "   SELECT 1 FROM mining_queue WHERE kind = 'checkpoint_enrich'"
        "   AND payload ->> 'checkpoint_id' = %(checkpoint_id)s)",
        {
            "sid": session_id,
            "path": transcript_path,
            "payload": json.dumps({"checkpoint_id": checkpoint_id}),
            "cursor": after_cursor,
            "checkpoint_id": checkpoint_id,
        },
    ).rowcount
    conn.commit()
    return bool(n)


def due_jobs_exist(conn) -> bool:
    return conn.execute(
        "SELECT 1 FROM mining_queue WHERE status = 'pending'"
        " AND next_attempt_at <= now() LIMIT 1"
    ).fetchone() is not None


def last_curation_at(conn) -> datetime | None:
    row = conn.execute(
        "SELECT max(at) AS at FROM audit_log WHERE op = 'curation_pass'"
    ).fetchone()
    return row["at"] if row else None


def count_legacy_provider_failures(conn) -> int:
    """Count only the two known pre-circuit-break Claude outage signatures."""
    row = conn.execute(
        f"SELECT count(*) AS n FROM mining_queue WHERE {_LEGACY_PROVIDER_FAILURE_SQL}"
    ).fetchone()
    return int(row["n"])


def requeue_legacy_provider_failures(conn, *, expected_count: int) -> bool:
    """Atomically requeue the exact legacy outage cohort, or change nothing on mismatch."""
    _serialize_enqueue(conn)
    if count_legacy_provider_failures(conn) != expected_count:
        conn.rollback()
        return False
    conn.execute(
        f"UPDATE mining_queue SET status = 'pending', attempts = 0, "
        "next_attempt_at = now(), finished_at = NULL, "
        "last_error = 'requeued: legacy Claude provider failure; Codex migration 2026-09-02' "
        f"WHERE {_LEGACY_PROVIDER_FAILURE_SQL}"
    )
    conn.commit()
    return True
