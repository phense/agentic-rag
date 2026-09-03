"""Lossless merge support for Codex lifecycle hooks."""
from __future__ import annotations

from copy import deepcopy


HOOK_MARKER = "agentic_rag.hooks."

_HOOK_MODULES = {
    "SessionStart": ("session_start", 10, "startup|resume|clear|compact"),
    "UserPromptSubmit": ("prompt_recall", 5, None),
    "Stop": ("stop_enqueue", 10, None),
    "PreCompact": ("pre_compact", 10, "manual|auto"),
    "PostCompact": ("post_compact", 10, "manual|auto"),
    "SessionEnd": ("session_end", 10, None),
}


def owned_hook_entries(python: str) -> dict[str, list[dict]]:
    """Build the six hook entries owned by agentic-rag."""
    result = {}
    for event, (module, timeout, matcher) in _HOOK_MODULES.items():
        entry = {
            "hooks": [
                {
                    "type": "command",
                    "command": f"{python} -m agentic_rag.hooks.{module}",
                    "timeout": timeout,
                }
            ]
        }
        if matcher is not None:
            entry["matcher"] = matcher
        result[event] = [entry]
    return result


def _without_owned_handlers(entry: object) -> object | None:
    if not isinstance(entry, dict):
        return entry
    handlers = entry.get("hooks")
    if not isinstance(handlers, list):
        return entry
    kept = [
        handler
        for handler in handlers
        if not (
            isinstance(handler, dict)
            and HOOK_MARKER in str(handler.get("command", ""))
        )
    ]
    if not kept:
        return None
    entry["hooks"] = kept
    return entry


def merge_hooks(data: dict, python: str) -> dict:
    """Replace only owned hook commands while retaining all foreign JSON."""
    result = deepcopy(data)
    hooks = result.get("hooks")
    if hooks is None:
        hooks = {}
        result["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks.json 'hooks' value must be an object")

    for event, current in list(hooks.items()):
        if not isinstance(current, list):
            raise ValueError(f"Codex hooks.json {event!r} value must be an array")
        retained = []
        for original in current:
            entry = _without_owned_handlers(original)
            if entry is not None:
                retained.append(entry)
        hooks[event] = retained
    for event, owned_entries in owned_hook_entries(python).items():
        hooks[event] = hooks.get(event, []) + owned_entries
    return result


def duplicate_herdr_commands(data: dict) -> tuple[str, ...]:
    """Return duplicated foreign herdr commands without changing them."""
    counts: dict[str, int] = {}
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return ()
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for handler in entry.get("hooks", []):
                if not isinstance(handler, dict):
                    continue
                command = str(handler.get("command", ""))
                if "herdr-agent-state.sh" in command:
                    counts[command] = counts.get(command, 0) + 1
    return tuple(sorted(command for command, count in counts.items() if count > 1))
