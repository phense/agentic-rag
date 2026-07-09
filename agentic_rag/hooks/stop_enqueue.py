"""Stop hook (spec §6): enqueue this session for mining (<100 ms) and spawn
the singleton worker. Debounce/idempotence live in jobs.enqueue_mine — one
open mine job per session, due mine_debounce_seconds in the future. Writes
fail open: every error is logged and swallowed; the hook always exits 0 and
prints nothing."""
from __future__ import annotations

import sys
from pathlib import Path

from .. import db, jobs
from ..config import load_config
from . import common


def run(payload: dict) -> None:
    try:
        if not common.is_interactive(payload):
            return
        transcript = payload.get("transcript_path")
        session_id = payload.get("session_id")
        if (not transcript or not session_id
                or not Path(transcript).is_file()):
            return
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            jobs.enqueue_mine(conn, cfg, session_id=str(session_id),
                              transcript_path=str(transcript),
                              project=payload.get("cwd"))
        finally:
            conn.close()
        common.spawn_worker()
    except Exception as e:  # noqa: BLE001 — never block the session
        common.log_hook_error("stop_enqueue", repr(e))


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
