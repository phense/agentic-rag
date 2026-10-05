"""Import-light projection of Codex rollout response items.

The rollout format is internal. Read only user/assistant prose and tool names;
event mirrors, reasoning, compaction internals and tool outputs are excluded.
"""
from __future__ import annotations

import hashlib
import json

from .secrets import strip_secrets


def response_identity(event: dict) -> str | None:
    """Stable opaque cursor, including for items whose message id is null.

    Capture reads a bounded tail while enrichment reads the file: hashing the
    same parsed record lets both identify the boundary without line numbering.
    Existing Claude/agy and lossless mining-window cursors stay unchanged.
    """
    if event.get("type") != "response_item" or not isinstance(event.get("payload"), dict):
        return None
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "codex-event-v1:" + hashlib.sha256(encoded).hexdigest()


def response_prose(event: dict, *, per_block: int) -> list[str]:
    payload = event.get("payload")
    if event.get("type") != "response_item" or not isinstance(payload, dict):
        return []
    kind = payload.get("type")
    if kind == "message":
        role = payload.get("role")
        if role not in ("user", "assistant"):
            return []
        if payload.get("phase") not in (None, "commentary", "final"):
            return []
        if payload.get("channel") not in (None, "commentary", "final"):
            return []
        content = payload.get("content")
        if not isinstance(content, list):
            return []
        lines = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in ("input_text", "output_text", "text"):
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                lines.append(f"[{role}] {strip_secrets(text.strip())[0][:per_block]}")
        return lines
    if kind not in ("function_call", "custom_tool_call"):
        return []
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return []
    # Custom tool inputs and ordinary function arguments never enter a digest.
    # Only named memory tools may add the existing slug/query hint contract.
    arguments = payload.get("arguments")
    if "memory_" in name and kind == "function_call" and isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = None
        if isinstance(arguments, dict):
            hint = arguments.get("slug") or arguments.get("id_or_slug") or arguments.get("query")
            if isinstance(hint, str) and hint.strip():
                name += " " + strip_secrets(hint)[0][:120]
    return [f"[assistant tool: {strip_secrets(name)[0][:per_block]}]"]
