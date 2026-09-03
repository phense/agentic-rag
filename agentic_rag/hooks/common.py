"""Shared hook plumbing. Contract: hooks NEVER block a session — every
error is swallowed (logged to ~/.agentic-rag/log/hooks.log) and the hook
exits 0. Import-light: stdlib only in this module."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

INTERACTIVE_SOURCES = {"startup", "resume", "clear", "compact"}
HOOK_LOG = Path.home() / ".agentic-rag" / "log" / "hooks.log"
WORKER_LOG = Path.home() / ".agentic-rag" / "log" / "worker.log"


def read_payload(stream) -> dict:
    try:
        data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def is_interactive(payload: dict) -> bool:
    """Skip for non-interactive session starts (cron/CI); tolerate a missing
    source (format drift must not silence the hooks). Kill switch:
    AGENTIC_RAG_HOOKS_DISABLE."""
    if os.environ.get("AGENTIC_RAG_HOOKS_DISABLE", "").strip():
        return False
    source = payload.get("source")
    return source is None or source in INTERACTIVE_SOURCES


def emit_context(stdout, event: str, text: str) -> None:
    json.dump({"hookSpecificOutput": {"hookEventName": event,
                                      "additionalContext": text}}, stdout)


def spawn_worker() -> None:
    """Fire-and-forget the singleton worker. A no-op when one already runs
    (it exits on lock contention). Never raises into the hook."""
    try:
        WORKER_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WORKER_LOG.open("ab") as log:
            subprocess.Popen(
                [sys.executable, "-m", "agentic_rag.worker"],
                start_new_session=True, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log)
    except Exception:  # noqa: BLE001 — fail-open by contract
        pass


def sanitize_error(err: object) -> str:
    """Return a secret-scrubbed diagnostic safe for logs and hook output."""
    try:
        from ..secrets import strip_secrets
        return strip_secrets(str(err))[0]
    except Exception:  # noqa: BLE001 — never leak the original on failure
        return "hook failure (diagnostic unavailable)"


def log_hook_error(hook: str, err: str) -> None:
    try:
        safe_err = sanitize_error(err)
        HOOK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with HOOK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} "
                     f"[{hook}] {safe_err}\n")
    except OSError:
        pass
