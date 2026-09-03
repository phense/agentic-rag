"""SessionEnd hook: enqueue the main thread's final transcript delta.

Codex fires ``reason="other"`` when the main thread really ends.  Claude Code
ends the transcript on every reason it reports (``clear``, ``resume``,
``logout``, ``prompt_input_exit``, ``other``) and gives all SessionEnd hooks
1.5 seconds in total, so this module stays import-light and the ``Stop`` hook
remains the guaranteed enqueue path.
"""
from __future__ import annotations

import sys

from . import common, transcript_delta

CODEX_REASONS = frozenset({"other"})
CLAUDE_REASONS = frozenset(
    {"clear", "resume", "logout", "prompt_input_exit", "other"})


def run(payload: dict) -> None:
    reasons = (
        CLAUDE_REASONS if common.client_kind(payload) == "claude"
        else CODEX_REASONS
    )
    if payload.get("reason") not in reasons:
        return
    transcript_delta.enqueue_transcript_delta(payload, hook="session_end")


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
