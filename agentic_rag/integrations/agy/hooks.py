"""Lossless merge of the owned named hook into Antigravity's ``hooks.json``.

Antigravity CLI hooks live in one JSON object per file whose top-level keys
are *hook names*; each name maps to an optional ``enabled`` flag and per-event
handler lists.  ``PreInvocation``, ``PostInvocation``, ``Stop`` and the
(undocumented, verified live) ``SessionStart`` are *flat* lists of handler
objects; ``PreToolUse``/``PostToolUse`` are matcher groups.  agentic-rag owns
exactly one named hook, ``agentic-rag``; every foreign name, key, and ordering
survives a merge, and any foreign handler that already runs an
``agentic_rag.hooks.`` command is removed so a moved virtualenv never leaves a
stale duplicate behind.
"""
from __future__ import annotations

import shlex
from copy import deepcopy

HOOK_NAME = "agentic-rag"
HOOK_MARKER = "agentic_rag.hooks."
HOOK_MODULE = "agentic_rag.hooks.agy"

# event -> (dispatcher sub-command, timeout seconds)
_EVENTS = {
    "SessionStart": ("session-start", 10),
    "PreInvocation": ("pre-invocation", 5),
    "Stop": ("stop", 10),
}
_GROUPED_EVENTS = ("PreToolUse", "PostToolUse")


def owned_hook(python: str) -> dict:
    """The single named hook agentic-rag installs."""
    quoted = shlex.quote(python)
    entry: dict = {"enabled": True}
    for event, (command, timeout) in _EVENTS.items():
        entry[event] = [{
            "type": "command",
            "command": f"{quoted} -m {HOOK_MODULE} {command}",
            "timeout": timeout,
        }]
    return entry


def _owned_command(handler: object) -> bool:
    return isinstance(handler, dict) and HOOK_MARKER in str(handler.get("command", ""))


def _strip_owned(value: object) -> object:
    """Remove owned handlers from a foreign event list (flat or grouped)."""
    if not isinstance(value, list):
        return value
    kept = []
    for item in value:
        if _owned_command(item):
            continue
        if isinstance(item, dict) and isinstance(item.get("hooks"), list):
            handlers = [h for h in item["hooks"] if not _owned_command(h)]
            if not handlers:
                continue
            item = {**item, "hooks": handlers}
        kept.append(item)
    return kept


def merge_hooks(data: dict, python: str) -> dict:
    """Return a new hooks object with the owned hook applied losslessly."""
    if not isinstance(data, dict):
        raise ValueError("Antigravity hooks.json root must be an object")
    result = deepcopy(data)
    for name, spec in list(result.items()):
        if name == HOOK_NAME:
            continue
        if not isinstance(spec, dict):
            continue
        for event in tuple(_EVENTS) + _GROUPED_EVENTS + ("PostInvocation",):
            if event in spec:
                spec[event] = _strip_owned(spec[event])
    result[HOOK_NAME] = owned_hook(python)
    return result


def owned_commands(data: dict) -> tuple[str, ...]:
    """Every installed agentic-rag command, for review output."""
    spec = data.get(HOOK_NAME) if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        return ()
    commands = []
    for event in _EVENTS:
        for handler in spec.get(event, []) or []:
            if isinstance(handler, dict) and isinstance(handler.get("command"), str):
                commands.append(handler["command"])
    return tuple(commands)
