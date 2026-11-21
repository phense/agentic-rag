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
from collections.abc import Sequence
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
    payload = {"project": project}
    if getattr(cfg, "mine_policy_file", None) is not None:
        # RAG-067: capture the configured extraction policy once, inside this
        # serialized admission. A rerun or has_more continuation of the open job
        # keeps its bundle; an invalid file fails this new admission visibly.
        from . import extraction_policy
        try:
            names = [r["name"] for r in conn.execute("SELECT name FROM domains ORDER BY name")]
            payload["extraction_policy"] = extraction_policy.capture(cfg, project, names)
        except BaseException:
            conn.rollback()
            raise
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
         "payload": json.dumps(payload),
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


# Exact worker errors whose cause is fixed in code and whose job can resume
# from its stored cursor. Anything else stays in 'error' for a human.
RECOVERABLE_MINE_ERRORS = {
    "duplicate-identity": "conflicting duplicate transcript identity; recovery required",
    "source-metadata": "source identity has conflicting metadata",
}


def recoverable_mine_errors(conn, error_class: str) -> list[dict]:
    """Errored mine jobs that may resume: exact error text, the newest mine job
    of its session, and no open mine job for that session."""
    message = RECOVERABLE_MINE_ERRORS[error_class]
    rows = conn.execute(
        "SELECT q.id, q.session_id, q.transcript_path, q.last_uuid"
        " FROM mining_queue q"
        " WHERE q.kind = 'mine' AND q.status = 'error' AND q.last_error = %s"
        " AND q.session_id IS NOT NULL AND q.transcript_path IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM mining_queue o"
        "   WHERE o.kind = 'mine' AND o.session_id = q.session_id"
        "   AND (o.id > q.id OR o.status IN ('pending', 'processing')))"
        " ORDER BY q.id", (message,)).fetchall()
    return [dict(r) for r in rows]


def preflight_mine_job(conn, cfg: Config, job: dict) -> str:
    """Raise if a requeued mine job would fail again on its stored cursor.

    A job whose input cursor already has an accepted mining batch replays that
    stored extraction without reading the transcript (source-metadata failures
    happen at that apply step), so only the remaining jobs must still resolve
    their cursor against the transcript with the current reader.
    """
    batch = conn.execute(
        "SELECT id FROM mining_batches WHERE session_id = %s AND input_cursor = %s",
        (job["session_id"], job["last_uuid"] or "")).fetchone()
    conn.commit()
    if batch is not None:
        return f"replays accepted batch {batch['id']}"
    from .mining_window import read_window
    read_window(job["transcript_path"], after_uuid=job["last_uuid"],
                max_chars=cfg.mine_max_digest_chars, per_block=cfg.mine_per_block_chars)
    return "cursor resolves in transcript"


def requeue_recoverable_mine_errors(conn, *, error_class: str, job_ids: Sequence[int],
                                    excluded_ids: Sequence[int] = (), actor: str = "cli") -> bool:
    """Atomically requeue exactly job_ids with one audit row, or change nothing.

    Callers preflight without the enqueue lock, which every hook enqueue
    waits on. Under the lock the cohort is selected again and must still be
    exactly job_ids plus the explicitly excluded ids. Older errored jobs of
    the same session, and excluded jobs, stay in 'error' as history.
    """
    message = RECOVERABLE_MINE_ERRORS[error_class]
    if not job_ids:
        raise ValueError("requeue requires at least one job")
    try:
        _serialize_enqueue(conn)
        cohort = {r["id"] for r in recoverable_mine_errors(conn, error_class)}
        wanted = set(job_ids)
        excluded = set(excluded_ids)
        if not excluded.issubset(cohort) or not wanted.isdisjoint(excluded) or (cohort - excluded) != wanted:
            conn.rollback()
            return False
        ids = sorted(wanted)
        excluded_sorted = sorted(excluded)
        note = f"requeued: {error_class} fixed in code; resumes from stored cursor"
        rows = conn.execute(
            "UPDATE mining_queue SET status = 'pending', attempts = 0,"
            " next_attempt_at = now(), finished_at = NULL, last_error = %s"
            " WHERE id = ANY(%s) AND kind = 'mine' AND status = 'error'"
            " AND last_error = %s RETURNING id, session_id", (note, ids, message)).fetchall()
        if len(rows) != len(ids):
            conn.rollback()
            return False
        sessions = {r["id"]: r["session_id"] for r in rows}
        conn.execute(
            "INSERT INTO audit_log(actor, op, summary)"
            " VALUES (%s, 'mining_queue_requeue', %s)",
            (actor, json.dumps({"error_class": error_class, "job_ids": ids,
                                "sessions": [sessions[i] for i in ids],
                                "excluded_ids": excluded_sorted})))
        conn.commit()
        return True
    except BaseException:
        conn.rollback()
        raise


def enqueue_profile(conn, cfg: Config, project: str | None = None) -> bool:
    """Schedule one open local profile rebuild per canonical project."""
    from .scope import project_id
    selected = project_id(project) if project else None
    _serialize_enqueue(conn)
    n = conn.execute(
        "INSERT INTO mining_queue(kind,payload) SELECT 'profile_refresh',%s"
        " WHERE NOT EXISTS(SELECT 1 FROM mining_queue WHERE kind='profile_refresh'"
        " AND status IN ('pending','processing')"
        " AND payload->>'project' IS NOT DISTINCT FROM %s)",
        (json.dumps({'project':selected}), selected)).rowcount
    conn.commit()
    return bool(n)
