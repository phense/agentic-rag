"""Version-tolerant Claude Code transcript digests (spec §6.1).

The JSONL format is officially internal and unstable: skip what we cannot
parse, ignore fields we do not know, degrade — never crash. The digest keeps
user/assistant prose, tool NAMES, and the slug/query args of memory tools
(so mining can name existing documents); tool_result bodies and all other
tool inputs are excluded (the secret + size surface). Prose is
secret-stripped here (first line of defense; the write gateway is the
second).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .secrets import strip_secrets


@dataclass(frozen=True)
class Digest:
    text: str
    last_uuid: str | None
    n_events: int


def _events(path: Path):
    try:
        # errors="replace": a live session file can end mid-multibyte-char;
        # UnicodeDecodeError is NOT an OSError and must never crash the
        # digest (degrade-never-crash) — the mangled line just fails JSON
        # parsing and is skipped like any other bad line
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict):
                    yield ev
    except OSError:
        return


def build_digest(path, *, after_uuid: str | None = None,
                 max_chars: int = 12000, per_block: int = 800,
                 keep: str = "head") -> Digest:
    path = Path(path)
    events = list(_events(path))
    start = 0
    if after_uuid is not None:
        for i, ev in enumerate(events):
            if ev.get("uuid") == after_uuid:
                start = i + 1
                break
        # unknown uuid (rotated file, format change) → mine the full
        # transcript rather than silently mining nothing
    lines: list[str] = []
    last_uuid = None
    n = 0
    for ev in events[start:]:
        n += 1
        if isinstance(ev.get("uuid"), str):
            last_uuid = ev["uuid"]
        msg = ev.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "?")
        content = msg.get("content")
        if isinstance(content, str):
            _append_prose(lines, role, content, per_block)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                _append_prose(lines, role, block.get("text") or "", per_block)
            elif btype == "tool_use":
                label = str(block.get("name", "?"))
                inp = block.get("input")
                # ONLY memory tools may contribute an arg hint (slugs/queries
                # ground mining in existing documents). The gate is the tool
                # NAME, not the field name — WebSearch and arbitrary MCP tools
                # also have a `query` field, and general tool inputs are a
                # secret + size surface that must never reach the digest.
                # MCP naming makes memory tools appear as
                # mcp__agentic-rag__memory_search, hence substring match.
                if "memory_" in label and isinstance(inp, dict):
                    hint = inp.get("slug") or inp.get("id_or_slug") \
                        or inp.get("query")
                    if isinstance(hint, str) and hint.strip():
                        hint, _ = strip_secrets(hint)
                        label += f" {hint[:120]}"
                lines.append(f"[{role} tool: {label}]")
            # tool_result bodies deliberately skipped (secret + size surface)
    text = "\n".join(lines)
    if keep == "head":
        bounded = text[:max_chars]
    elif keep == "tail":
        marker = "[... earlier delta omitted ...]\n"
        if len(text) <= max_chars:
            bounded = text
        elif max_chars <= len(marker):
            bounded = text[-max_chars:]
        else:
            bounded = marker + text[-(max_chars - len(marker)):]
    else:
        raise ValueError("keep must be 'head' or 'tail'")
    return Digest(bounded, last_uuid, n)


def _append_prose(lines: list[str], role: str, text: str,
                  per_block: int) -> None:
    text = text.strip()
    if not text:
        return
    text, _ = strip_secrets(text)
    lines.append(f"[{role}] {text[:per_block]}")
