"""PostCompact hook: record the boundary without restoring model context."""
from __future__ import annotations

import json
import sys

from .. import db
from ..config import load_config
from ..continuity import store
from . import common

_TRIGGERS = frozenset({"manual", "auto"})


def _identity(payload: dict) -> tuple[str, str, str] | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str) or not turn_id.strip():
        return None
    trigger = payload.get("trigger")
    if trigger not in _TRIGGERS:
        return None
    return session_id, turn_id, trigger


def run(payload: dict, stdout) -> None:
    identity = _identity(payload)
    if identity is None or not common.is_interactive(payload):
        return
    session_id, turn_id, trigger = identity
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            checkpoint = store.matching_compaction(
                conn, session_id, turn_id, trigger)
            if checkpoint is not None:
                store.mark_compacted(conn, session_id, checkpoint.cursor)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — compaction already succeeded
        common.log_hook_error("post_compact", repr(exc))
        json.dump({"systemMessage": "checkpoint bookkeeping delayed"}, stdout)


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
