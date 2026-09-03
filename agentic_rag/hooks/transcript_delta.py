"""Shared import-light enqueue path for Stop and SessionEnd hooks."""
from __future__ import annotations

from pathlib import Path

from .. import db, jobs
from ..config import load_config
from . import common


def enqueue_transcript_delta(payload: dict, *, hook: str) -> None:
    """Queue one debounced transcript delta and never raise to Codex."""
    try:
        if not common.is_interactive(payload):
            return
        transcript = payload.get("transcript_path")
        session_id = payload.get("session_id")
        if (
            not isinstance(transcript, str)
            or not transcript.strip()
            or not isinstance(session_id, str)
            or not session_id.strip()
            or not Path(transcript).is_file()
        ):
            return
        project = payload.get("cwd")
        if project is not None and not isinstance(project, str):
            return

        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            jobs.enqueue_mine(
                conn,
                cfg,
                session_id=session_id,
                transcript_path=transcript,
                project=project,
            )
        finally:
            conn.close()
        common.spawn_worker()
    except Exception as exc:  # noqa: BLE001 — lifecycle hooks fail open
        common.log_hook_error(hook, repr(exc))
