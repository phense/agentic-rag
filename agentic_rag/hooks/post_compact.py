"""PostCompact hook: record the boundary without restoring model context.

Codex delivers session/turn/trigger and nothing else.  Claude Code delivers
no turn id but includes ``compact_summary``; that summary is retained as a
bounded, secret-stripped handoff on the matching checkpoint.  Neither client
receives ``additionalContext`` from this hook — SessionStart restores.
"""
from __future__ import annotations

import json
import sys

from .. import db
from ..config import Config, load_config
from ..continuity import store
from . import common

_TRIGGERS = frozenset({"manual", "auto"})


def _session_and_trigger(payload: dict) -> tuple[str, str] | None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    trigger = payload.get("trigger")
    if trigger not in _TRIGGERS:
        return None
    return session_id, trigger


def _identity(payload: dict) -> tuple[str, str, str] | None:
    base = _session_and_trigger(payload)
    turn_id = payload.get("turn_id")
    if base is None or not isinstance(turn_id, str) or not turn_id.strip():
        return None
    session_id, trigger = base
    return session_id, turn_id, trigger


def _record_codex_boundary(conn, session_id: str, turn_id: str, trigger: str) -> None:
    checkpoint = store.matching_compaction(conn, session_id, turn_id, trigger)
    if checkpoint is not None:
        store.mark_compacted(conn, session_id, checkpoint.cursor)


def _record_claude_boundary(
    conn, cfg: Config, payload: dict, session_id: str, trigger: str
) -> None:
    checkpoint = store.latest_pre_compact(conn, session_id, trigger)
    if checkpoint is None:
        return
    store.mark_compacted(conn, session_id, checkpoint.cursor)
    summary = payload.get("compact_summary")
    if not isinstance(summary, str) or not summary.strip():
        return
    try:
        store.attach_handoff(
            conn, checkpoint.id, summary,
            max_chars=cfg.checkpoint_handoff_max_chars,
        )
    except Exception as exc:  # noqa: BLE001 — the boundary is already marked
        common.log_hook_error("post_compact.handoff", repr(exc))


def run(payload: dict, stdout) -> None:
    if not common.is_interactive(payload):
        return
    client = common.client_kind(payload)
    if client == "claude":
        identity = _session_and_trigger(payload)
    else:
        identity = _identity(payload)
    if identity is None:
        return
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            if client == "claude":
                _record_claude_boundary(conn, cfg, payload, *identity)
            else:
                _record_codex_boundary(conn, *identity)
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
