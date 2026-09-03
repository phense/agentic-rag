"""Stop hook (spec §6): enqueue this session for mining (<100 ms) and spawn
the singleton worker. Debounce/idempotence live in jobs.enqueue_mine — one
open mine job per session, due mine_debounce_seconds in the future. Writes
fail open: every error is logged and swallowed; the hook always exits 0 and
prints nothing."""
from __future__ import annotations

import sys

from . import common, transcript_delta


def run(payload: dict) -> None:
    transcript_delta.enqueue_transcript_delta(payload, hook="stop_enqueue")


def main() -> int:
    run(common.read_payload(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
