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
CLIENT_KINDS = ("claude", "codex")
HOOK_LOG = Path.home() / ".agentic-rag" / "log" / "hooks.log"
WORKER_LOG = Path.home() / ".agentic-rag" / "log" / "worker.log"


def client_kind(payload: dict, argv: list[str] | None = None) -> str:
    """Which client delivered this hook event: ``claude`` or ``codex``.

    An explicit ``--client`` argument wins (tests, diagnostics).  Otherwise a
    non-blank ``turn_id`` is Codex's documented stable field; Claude Code
    never sends one.  Environment variables are ignored on purpose: a Claude
    session exports CLAUDECODE=1 to every child, including test runs.
    """
    args = sys.argv[1:] if argv is None else argv
    for index, arg in enumerate(args):
        if arg == "--client" and index + 1 < len(args):
            if args[index + 1] in CLIENT_KINDS:
                return args[index + 1]
        elif arg.startswith("--client=") and arg[len("--client="):] in CLIENT_KINDS:
            return arg[len("--client="):]
    turn_id = payload.get("turn_id")
    if isinstance(turn_id, str) and turn_id.strip():
        return "codex"
    return "claude"


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


def emit_context(stdout, event: str, text: str, *,
                 system_message: str | None = None) -> None:
    output = {"hookSpecificOutput": {"hookEventName": event,
                                     "additionalContext": text}}
    if system_message is not None:
        output["systemMessage"] = system_message
    json.dump(output, stdout)


def spawn_worker() -> Exception | None:
    """Fire-and-forget the singleton worker. A no-op when one already runs
    (it exits on lock contention). Never raises into the hook. Return a launch
    error for callers that can report it; existing callers may ignore the result."""
    try:
        from ..config import load_config
        module='agentic_rag.service.uploader' if load_config().service_mode=='client' else 'agentic_rag.worker'
        # Children use their own bounded diagnostics. A raw append-only stderr
        # descriptor would bypass rotation and could fill the client filesystem.
        subprocess.Popen(
            [sys.executable, "-m", module],
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001 — fail-open by contract
        return exc


def sanitize_error(err: object) -> str:
    """Return a secret-scrubbed diagnostic safe for logs and hook output."""
    try:
        from ..secrets import strip_secrets
        return strip_secrets(str(err))[0]
    except Exception:  # noqa: BLE001 — never leak the original on failure
        return "hook failure (diagnostic unavailable)"


def log_hook_error(hook: str, err: str) -> None:
    try:
        from ..bounded_log import append
        append(HOOK_LOG,f'[{hook}] {sanitize_error(err)}')
    except OSError:
        pass
