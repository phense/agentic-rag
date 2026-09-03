"""PreCompact hook: persist fast deterministic continuation state.

Semantic enrichment is queued for the singleton worker; this hook never calls
an LLM or waits for mining.  All output stays silent so compaction can proceed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import db, jobs
from ..config import load_config
from ..continuity import capture, store
from . import common

_TRIGGERS = frozenset({"manual", "auto"})


def _validate(payload: dict) -> tuple[str, str | None]:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("PreCompact requires a session_id")
    trigger = payload.get("trigger")
    if trigger not in _TRIGGERS:
        raise ValueError("PreCompact trigger must be manual or auto")
    transcript = payload.get("transcript_path")
    if transcript is not None and not isinstance(transcript, str):
        raise ValueError("PreCompact transcript_path must be a string or null")
    return session_id, transcript


def run(payload: dict) -> None:
    try:
        session_id, transcript = _validate(payload)
        if not common.is_interactive(payload):
            return
        cfg = load_config()
        snapshot = capture.capture_snapshot_seed(payload)
        conn = db.connect(cfg, role="writer")
        try:
            checkpoint = store.upsert_snapshot(
                conn, snapshot, update_existing=False)
            try:
                repository_snapshot = capture.capture_repository_state(
                    snapshot, cwd=payload.get("cwd"))
                checkpoint = store.upsert_snapshot(conn, repository_snapshot)
            except Exception as exc:  # noqa: BLE001 — seed is already durable
                common.log_hook_error("pre_compact", repr(exc))
            if transcript and Path(transcript).is_file():
                jobs.enqueue_checkpoint_enrichment(
                    conn,
                    checkpoint_id=checkpoint.id,
                    session_id=session_id,
                    transcript_path=transcript,
                    after_cursor=checkpoint.predecessor_cursor,
                )
                common.spawn_worker()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — compaction must never block
        common.log_hook_error("pre_compact", repr(exc))


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
