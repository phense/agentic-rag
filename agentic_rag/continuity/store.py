"""Audited transactional persistence for continuation checkpoints."""
from __future__ import annotations

import json
from collections.abc import Mapping

from .model import Checkpoint, CheckpointSnapshot


def _checkpoint(row) -> Checkpoint:
    return Checkpoint(
        id=str(row["id"]),
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        cursor=row["cursor"],
        source=row["source"],
        trigger=row["trigger"],
        cwd=row["cwd"],
        project_root=row["project_root"],
        transcript_fingerprint=row["transcript_fingerprint"],
        git=row["git"],
        snapshot=row["snapshot"],
        enrichment=row["enrichment"],
        references=tuple(row["references"]),
        warnings=tuple(row["warnings"]),
        state=row["state"],
        quality=row["quality"],
        compacted_at=row["compacted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _json(value: object, name: str) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc


def _checkpoint_summary(checkpoint_id: str, action: str) -> str:
    return f"checkpoint {checkpoint_id} {action}"


def get(conn, checkpoint_id: str) -> Checkpoint | None:
    row = conn.execute(
        "SELECT * FROM continuation_checkpoints WHERE id = %s", (checkpoint_id,)
    ).fetchone()
    return _checkpoint(row) if row is not None else None


def upsert_snapshot(conn, snapshot: CheckpointSnapshot) -> Checkpoint:
    """Persist one cursor idempotently and supersede prior open session state."""
    if not isinstance(snapshot, CheckpointSnapshot):
        raise TypeError("snapshot must be a CheckpointSnapshot")
    snapshot_json = {"source": snapshot.source, "trigger": snapshot.trigger}
    try:
        # Serialize before beginning writes, so invalid caller input cannot leave
        # a partially changed transaction behind.
        git = _json(dict(snapshot.git), "git")
        capture = _json(snapshot_json, "snapshot")
        references = _json(list(snapshot.artifacts), "artifacts")
        warnings = _json(list(snapshot.warnings), "warnings")

        # Concurrent PreCompact deliveries serialize per session.  Lock first,
        # then upsert the exact cursor, then supersede only other open cursors.
        conn.execute(
            "SELECT id FROM continuation_checkpoints "
            "WHERE session_id = %s AND state = 'open' FOR UPDATE",
            (snapshot.session_id,),
        )
        row = conn.execute(
            "INSERT INTO continuation_checkpoints("
            "session_id, turn_id, cursor, transcript_fingerprint, source, trigger, "
            "cwd, project_root, git, snapshot, \"references\", warnings) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (session_id, cursor) DO UPDATE SET "
            "turn_id = EXCLUDED.turn_id, "
            "transcript_fingerprint = EXCLUDED.transcript_fingerprint, "
            "source = EXCLUDED.source, trigger = EXCLUDED.trigger, cwd = EXCLUDED.cwd, "
            "project_root = EXCLUDED.project_root, git = EXCLUDED.git, "
            "snapshot = EXCLUDED.snapshot, \"references\" = EXCLUDED.\"references\", "
            "warnings = EXCLUDED.warnings, updated_at = now() "
            "WHERE continuation_checkpoints.state = 'open' AND "
            "(continuation_checkpoints.turn_id, "
            " continuation_checkpoints.transcript_fingerprint, "
            " continuation_checkpoints.source, continuation_checkpoints.trigger, "
            " continuation_checkpoints.cwd, continuation_checkpoints.project_root, "
            " continuation_checkpoints.git, continuation_checkpoints.snapshot, "
            " continuation_checkpoints.\"references\", continuation_checkpoints.warnings) "
            "IS DISTINCT FROM "
            "(EXCLUDED.turn_id, EXCLUDED.transcript_fingerprint, EXCLUDED.source, "
            " EXCLUDED.trigger, EXCLUDED.cwd, EXCLUDED.project_root, EXCLUDED.git, "
            " EXCLUDED.snapshot, EXCLUDED.\"references\", EXCLUDED.warnings) "
            "RETURNING *, (xmax = 0) AS inserted",
            (snapshot.session_id, snapshot.turn_id, snapshot.cursor,
             snapshot.transcript_fingerprint, snapshot.source, snapshot.trigger,
             snapshot.cwd, snapshot.project_root, git, capture, references, warnings),
        ).fetchone()
        changed = row is not None
        if row is None:
            row = conn.execute(
                "SELECT * FROM continuation_checkpoints "
                "WHERE session_id = %s AND cursor = %s",
                (snapshot.session_id, snapshot.cursor),
            ).fetchone()
        if changed and row["inserted"]:
            conn.execute(
                "UPDATE continuation_checkpoints SET state = 'superseded', updated_at = now() "
                "WHERE session_id = %s AND state = 'open' AND id <> %s",
                (snapshot.session_id, row["id"]),
            )
        if changed:
            conn.execute(
                "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
                ("continuity", "checkpoint_snapshot",
                 _checkpoint_summary(str(row["id"]), "captured")),
            )
        conn.commit()
        return get(conn, str(row["id"]))  # type: ignore[return-value]
    except Exception:
        conn.rollback()
        raise


def apply_enrichment(conn, checkpoint_id: str, enrichment: Mapping[str, object]) -> Checkpoint:
    """Attach validated semantic state without changing its lifecycle state."""
    if not isinstance(enrichment, Mapping):
        raise ValueError("enrichment must be a mapping")
    encoded = _json(dict(enrichment), "enrichment")
    try:
        row = conn.execute(
            "UPDATE continuation_checkpoints SET enrichment = %s, quality = 'enriched', "
            "updated_at = now() WHERE id = %s RETURNING *",
            (encoded, checkpoint_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"no such checkpoint: {checkpoint_id}")
        conn.execute(
            "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
            ("continuity", "checkpoint_enriched",
             _checkpoint_summary(str(row["id"]), "enriched")),
        )
        conn.commit()
        return _checkpoint(row)
    except Exception:
        conn.rollback()
        raise


def mark_compacted(conn, session_id: str, cursor: str) -> bool:
    """Record a successful compaction boundary for one immutable cursor."""
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-blank string")
    if not isinstance(cursor, str) or not cursor.strip():
        raise ValueError("cursor must be a non-blank string")
    try:
        row = conn.execute(
            "UPDATE continuation_checkpoints SET compacted_at = now(), updated_at = now() "
            "WHERE session_id = %s AND cursor = %s AND compacted_at IS NULL RETURNING *",
            (session_id, cursor),
        ).fetchone()
        if row is None:
            exists = conn.execute(
                "SELECT 1 FROM continuation_checkpoints WHERE session_id = %s AND cursor = %s",
                (session_id, cursor),
            ).fetchone()
            conn.rollback()
            return exists is not None
        conn.execute(
            "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
            ("continuity", "checkpoint_compacted",
             _checkpoint_summary(str(row["id"]), "compacted")),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def latest_for_session(conn, session_id: str) -> Checkpoint | None:
    row = conn.execute(
        "SELECT * FROM continuation_checkpoints WHERE session_id = %s AND state = 'open' "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return _checkpoint(row) if row is not None else None


def latest_for_project(conn, project_root: str) -> Checkpoint | None:
    row = conn.execute(
        "SELECT * FROM continuation_checkpoints "
        "WHERE project_root = %s AND state = 'open' "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        (project_root,),
    ).fetchone()
    return _checkpoint(row) if row is not None else None
