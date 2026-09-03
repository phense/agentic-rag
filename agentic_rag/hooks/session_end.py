"""SessionEnd hook: enqueue the main thread's final transcript delta."""
from __future__ import annotations

import sys

from . import common, transcript_delta


def run(payload: dict) -> None:
    if payload.get("reason") != "other":
        return
    transcript_delta.enqueue_transcript_delta(payload, hook="session_end")


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
