"""Lossless merge of owned hooks and the compaction policy into
``~/.claude/settings.json``.

Only handler commands carrying ``agentic_rag.hooks.`` are ever replaced; every
foreign entry, key, and ordering survives.  The managed policy is one value:
``autoCompactWindow = 500000`` (a token count, capped by the model's window).
"""
from __future__ import annotations

import shlex
from collections.abc import Mapping
from copy import deepcopy

HOOK_MARKER = "agentic_rag.hooks."
MANAGED_VALUES: dict[str, object] = {"autoCompactWindow": 500000}
OVERRIDING_ENV = (
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    "DISABLE_AUTO_COMPACT",
    "DISABLE_COMPACT",
)
ONE_MILLION_SUFFIX = "[1m]"

# event -> (module, timeout seconds, matcher)
_HOOK_MODULES = {
    "SessionStart": ("session_start", 10, "startup|resume|clear|compact"),
    "UserPromptSubmit": ("prompt_recall", 5, None),
    "Stop": ("stop_enqueue", 10, None),
    "PreCompact": ("pre_compact", 3, "manual|auto"),
    "PostCompact": ("post_compact", 3, "manual|auto"),
    "SessionEnd": ("session_end", 1, None),
}


def managed_settings() -> tuple[tuple[str, object], ...]:
    return tuple(MANAGED_VALUES.items())


def owned_hook_entries(python: str) -> dict[str, list[dict]]:
    quoted = shlex.quote(python)
    result: dict[str, list[dict]] = {}
    for event, (module, timeout, matcher) in _HOOK_MODULES.items():
        entry: dict = {
            "hooks": [{
                "type": "command",
                "command": f"{quoted} -m agentic_rag.hooks.{module}",
                "timeout": timeout,
            }]
        }
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        result[event] = [entry]
    return result


def _without_owned(entry: object) -> object | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
        return entry
    kept = [
        handler for handler in entry["hooks"]
        if not (isinstance(handler, dict)
                and HOOK_MARKER in str(handler.get("command", "")))
    ]
    if not kept:
        return None
    entry["hooks"] = kept
    return entry


def merge_settings(data: dict, python: str) -> dict:
    """Return a new settings object with owned hooks and policy applied."""
    result = deepcopy(data)
    hooks = result.get("hooks")
    if hooks is None:
        hooks = {}
        result["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("Claude settings 'hooks' value must be an object")
    for event, current in list(hooks.items()):
        if not isinstance(current, list):
            raise ValueError(f"Claude settings hooks {event!r} must be an array")
        hooks[event] = [
            kept for original in current
            if (kept := _without_owned(original)) is not None
        ]
    for event, entries in owned_hook_entries(python).items():
        hooks[event] = hooks.get(event, []) + entries
    for key, value in MANAGED_VALUES.items():
        result[key] = value
    return result


def policy_warnings(data: dict, environ: Mapping[str, str]) -> tuple[str, ...]:
    """Report, never fix, conditions under which the managed window is moot."""
    warnings: list[str] = []
    model = data.get("model")
    if not isinstance(model, str) or not model.strip():
        warnings.append(
            "no model configured in settings; autoCompactWindow=500000 is "
            "capped to the default model's context window"
        )
    elif not model.endswith(ONE_MILLION_SUFFIX):
        warnings.append(
            f"model {model!r} has no {ONE_MILLION_SUFFIX} suffix; "
            "autoCompactWindow=500000 is capped to that model's window"
        )
    if data.get("autoCompactEnabled") is False:
        warnings.append(
            "autoCompactEnabled is false; automatic compaction and continuity "
            "checkpoints stay idle until it is re-enabled"
        )
    env_block = data.get("env")
    if isinstance(env_block, dict):
        for key in OVERRIDING_ENV:
            if key in env_block:
                warnings.append(
                    f"settings env {key} overrides the managed autoCompactWindow")
    for key in OVERRIDING_ENV:
        if key in environ:
            warnings.append(
                f"environment variable {key} overrides the managed "
                "autoCompactWindow"
            )
    return tuple(warnings)
