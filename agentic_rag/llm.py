"""The auth-agnostic LLM chokepoint (spec §3): every `claude -p` call in the
system goes through run_structured. It is agnostic about how the local `claude`
CLI is authenticated — it uses WHATEVER that CLI is logged into, either your
Claude subscription (OAuth login) or an ANTHROPIC_API_KEY. The choice is the
user's; this module neither imposes nor refuses one. On a subscription, these
calls add nothing beyond your plan; with an API key, they are metered by
Anthropic like any API use. (Embeddings are always local — Ollama/bge-m3 — so
retrieval is free regardless of auth.)

It still strips inherited Claude-Code session markers (CLAUDECODE_*) so an
in-session-spawned worker can never recurse into the parent session (recursion
guard), and sets AGENTIC_RAG_HOOKS_DISABLE so a spawned child never re-mines
its own transcript (mining-cascade guard). This module is the single seam to
repoint at a local model.

Verified CLI contract (claude 2.1.201): with -p and --json-schema, stdout is
EXACTLY the schema-conforming JSON document (no envelope), exit 0.
"""
from __future__ import annotations

import json
import os
import subprocess

from .config import Config

_STRIP_ENV = (
    "CLAUDECODE",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
)


class LLMError(RuntimeError):
    """The claude CLI failed (missing, timeout, non-zero exit, bad output)."""


def _child_env(env: dict | None) -> dict:
    child = dict(os.environ if env is None else env)
    for key in _STRIP_ENV:
        child.pop(key, None)
    # A `claude -p` child inherits ~/.claude/settings.json, so on completion it
    # fires ITS OWN Stop hook, which would enqueue the child's transcript for
    # mining -> mining spawns another `claude -p` -> self-amplifying cascade
    # (nested "SESSION DIGEST" digests truncated at max_chars). Setting the
    # kill switch every agentic-rag hook honors (common.is_interactive) makes
    # the system's own LLM calls hook-inert. Stripping CLAUDE_CODE_* above only
    # stops parent-session recursion; this stops child-transcript re-mining.
    child["AGENTIC_RAG_HOOKS_DISABLE"] = "1"
    # ANTHROPIC_API_KEY (if any) passes through UNCHANGED: agentic-rag is
    # auth-agnostic and lets the claude CLI use whatever it is logged into —
    # subscription OAuth or an API key. The user's choice; we neither impose
    # nor refuse one.
    return child


def run_structured(prompt: str, schema: dict, cfg: Config, *,
                   system: str | None = None, timeout: int | None = None,
                   runner=subprocess.run, env: dict | None = None) -> dict:
    """One structured `claude -p --json-schema` call. Returns the parsed dict.

    `runner` is subprocess.run-compatible and injectable — tests never spawn
    a real process; the worker passes the default.
    """
    child_env = _child_env(env)
    cmd = [cfg.llm_bin, "--model", cfg.llm_model]
    if system is not None:
        cmd += ["--system-prompt", system]
    cmd += ["-p", prompt, "--json-schema", json.dumps(schema)]
    try:
        proc = runner(cmd, capture_output=True, text=True,
                      timeout=timeout or cfg.llm_timeout, env=child_env)
    except FileNotFoundError as e:
        raise LLMError(
            f"claude binary not found ({cfg.llm_bin!r}); is the CLI on "
            f"PATH?") from e
    except subprocess.TimeoutExpired as e:
        raise LLMError(
            f"claude timed out after {timeout or cfg.llm_timeout}s") from e
    if proc.returncode != 0:
        raise LLMError(
            f"claude exited {proc.returncode}: {(proc.stderr or '')[:500]}")
    try:
        data = json.loads(proc.stdout)
    except ValueError as e:
        raise LLMError(
            f"claude output is not valid JSON: {proc.stdout[:200]!r}") from e
    if not isinstance(data, dict):
        raise LLMError(f"claude output is not a JSON object: {data!r:.200}")
    return data
