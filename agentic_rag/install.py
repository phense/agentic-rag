"""rag install (spec §3): MCP registration (user scope, via the claude CLI),
hook wiring in ~/.claude/settings.json (idempotent merge — foreign hooks and
unknown keys survive untouched), and the backup LaunchAgent with a FRESHLY
resolved rag path (a recreated .venv must never leave launchd pointing at a
dead interpreter — Plan-1 review gate)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import backup
from .config import Config

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
HOOK_MARKER = "agentic_rag.hooks."
MCP_NAME = "agentic-rag"
MCP_NAME_RO = "agentic-rag-ro"   # spec §5: the subagent server, rag_reader


def hook_entries(python: str) -> dict:
    def block(module: str, timeout: int) -> dict:
        return {"hooks": [{"type": "command",
                           "command": f"{python} -m {module}",
                           "timeout": timeout}]}
    return {
        "SessionStart": [{"matcher": "startup|resume|clear|compact",
                          **block("agentic_rag.hooks.session_start", 10)}],
        "UserPromptSubmit": [block("agentic_rag.hooks.prompt_recall", 5)],
        "Stop": [block("agentic_rag.hooks.stop_enqueue", 10)],
    }


def _is_ours(entry: dict) -> bool:
    return any(HOOK_MARKER in h.get("command", "")
               for h in entry.get("hooks", []))


def merge_hooks(settings: dict, python: str) -> dict:
    out = dict(settings)
    hooks = {k: list(v) for k, v in dict(out.get("hooks") or {}).items()}
    for event, entries in hook_entries(python).items():
        kept = [e for e in hooks.get(event, []) if not _is_ours(e)]
        hooks[event] = kept + entries
    out["hooks"] = hooks
    return out


def register_mcp(python: str, run=subprocess.run) -> None:
    """Register BOTH servers user-scope: agentic-rag (read-write, main
    sessions) and agentic-rag-ro (RAG_READONLY=1 → six read tools on the
    rag_reader role — spec §5's subagent server). Subagents inherit all
    session MCP servers, so containment additionally needs the subagent
    definition to allowlist only mcp__agentic-rag-ro__* tools."""
    # Resolve through PATH so this works on Windows too, where the CLI is a
    # claude.cmd shim unreachable by bare name (mirrors the llm.py seam).
    claude = shutil.which("claude") or "claude"
    base = {"type": "stdio", "command": python,
            "args": ["-m", "agentic_rag.mcp_server"]}
    servers = [
        (MCP_NAME, base),
        (MCP_NAME_RO, {**base, "env": {"RAG_READONLY": "1"}}),
    ]
    for name, spec in servers:
        run([claude, "mcp", "remove", "-s", "user", name],
            capture_output=True, text=True)      # rc ignored: may not exist
        proc = run([claude, "mcp", "add-json", "-s", "user", name,
                    json.dumps(spec)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude mcp add-json ({name}) failed: "
                f"{(proc.stderr or '')[:300]}")


@dataclass(frozen=True)
class InstallReport:
    settings_path: Path
    plist_path: Path | None
    mcp_registered: bool


def install(cfg: Config, *, settings_path: Path | None = None,
            run=subprocess.run, with_launchd: bool = True) -> InstallReport:
    python = sys.executable
    register_mcp(python, run=run)

    settings_path = settings_path or SETTINGS_PATH
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(settings_path.read_text())
    except OSError:
        current = {}        # no settings file yet — start fresh
    except ValueError as e:
        # a CORRUPT settings.json must never be silently replaced with a
        # hooks-only file — that would drop the user's model/permissions/
        # foreign hooks from the live config (the .bak of garbage is no
        # recovery). Abort loudly; the user fixes or moves the file aside.
        raise RuntimeError(
            f"{settings_path} is not valid JSON ({e}) — fix it or move it "
            f"aside, then re-run rag install") from e
    if settings_path.exists():
        settings_path.with_suffix(".json.bak").write_text(
            settings_path.read_text())
    merged = merge_hooks(current, python)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    os.replace(tmp, settings_path)

    plist = None
    if with_launchd and sys.platform == "darwin":
        # the launchd gate: resolve rag NEXT TO the current interpreter —
        # never trust a stale plist or an inherited PATH
        rag_bin = Path(python).with_name("rag")
        plist = backup.install_launchd(cfg, rag_bin)
    return InstallReport(settings_path, plist, True)
