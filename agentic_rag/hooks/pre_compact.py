"""PreCompact hook: persist fast deterministic continuation state.

Semantic enrichment is queued for the singleton worker; this hook never calls
an LLM or waits for mining.  Codex output stays silent.  Claude Code appends a
PreCompact hook's stdout to its compaction instructions, so for Claude the hook
prints the versioned compact prompt (plus the checkpoint id when one exists)
after persistence — even when persistence failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .. import db, jobs
from ..config import load_config
from ..continuity import capture, store
from ..integrations.claude.prompt import CHECKPOINT_LINE_PREFIX, compact_prompt_text
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


def _persist(payload: dict) -> str | None:
    """Snapshot, enrich-enqueue, and return the checkpoint id (or None)."""
    session_id, transcript = _validate(payload)
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
        return checkpoint.id
    finally:
        conn.close()


def _emit_compact_instructions(stdout, checkpoint_id: str | None) -> None:
    try:
        text = compact_prompt_text()
    except Exception as exc:  # noqa: BLE001 — a missing asset must not block
        common.log_hook_error("pre_compact.prompt", repr(exc))
        return
    stdout.write(text.rstrip("\n") + "\n")
    if checkpoint_id:
        stdout.write(f"{CHECKPOINT_LINE_PREFIX}{checkpoint_id}\n")
    stdout.flush()


def run(payload: dict, stdout=None) -> None:
    if not common.is_interactive(payload):
        return
    checkpoint_id = None
    try:
        checkpoint_id = _persist(payload)
    except Exception as exc:  # noqa: BLE001 — compaction must never block
        common.log_hook_error("pre_compact", repr(exc))
    if stdout is not None and common.client_kind(payload) == "claude":
        _emit_compact_instructions(stdout, checkpoint_id)


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
