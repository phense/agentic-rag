"""Antigravity CLI (``agy``) transcript steps: version-tolerant helpers.

The CLI writes one JSON object per line to
``<app data>/brain/<conversation>/.system_generated/logs/transcript_full.jsonl``.
Each object is a trajectory *step* with ``step_index``, ``source``
(``USER_EXPLICIT`` / ``MODEL`` / ``SYSTEM``), ``type`` (``USER_INPUT``,
``PLANNER_RESPONSE``, ...), ``status``, ``created_at``, and either ``content``
or ``tool_calls``.  User prompts arrive wrapped in ``<USER_REQUEST>`` with
client-added ``<ADDITIONAL_METADATA>`` / ``<USER_SETTINGS_CHANGE>`` blocks.

The format is product-internal: unknown fields are ignored, unparsable lines
are skipped, and nothing here raises on malformed input.  Import-light (stdlib
plus the secret scrubber) so hooks stay fast.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .secrets import strip_secrets

STEP_PREFIX = "agy-step-"
USER_INPUT = "USER_INPUT"
PLANNER_RESPONSE = "PLANNER_RESPONSE"
COMPACT_COMMAND = "/compact"
# Automatic context summarization inserts the summary under this tag; the
# trajectory step type for that boundary is CHECKPOINT.  Both signals are
# treated as one compaction marker because the live shape of an automatic
# compaction has not been observed yet (see BACKLOG).
AUTO_COMPACTION_TYPES = frozenset({"CHECKPOINT", "CONTEXT_SUMMARY"})
AUTO_COMPACTION_TAG = "<CONTEXT_SUMMARY>"
TAIL_BYTES = 256 * 1024

_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_DROP_BLOCKS_RE = re.compile(
    r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|EPHEMERAL_MESSAGE)>.*?"
    r"</\1>", re.S)


@dataclass(frozen=True)
class Step:
    index: int
    type: str
    source: str
    content: str
    tool_calls: tuple[str, ...]
    raw: dict

    @property
    def identity(self) -> str:
        return f"{STEP_PREFIX}{self.index}"

    @property
    def is_user_input(self) -> bool:
        return self.type == USER_INPUT

    @property
    def is_model_response(self) -> bool:
        return self.type == PLANNER_RESPONSE


def is_step(event: object) -> bool:
    """A JSON object shaped like an agy trajectory step."""
    return (
        isinstance(event, dict)
        and isinstance(event.get("step_index"), int)
        and not isinstance(event.get("step_index"), bool)
        and isinstance(event.get("type"), str)
    )


def step_identity(event: dict) -> str | None:
    return f"{STEP_PREFIX}{event['step_index']}" if is_step(event) else None


def parse_step(event: dict) -> Step | None:
    if not is_step(event):
        return None
    content = event.get("content")
    names: list[str] = []
    calls = event.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            if isinstance(call, dict) and isinstance(call.get("name"), str):
                names.append(call["name"])
    return Step(
        index=event["step_index"],
        type=event["type"],
        source=str(event.get("source") or ""),
        content=content if isinstance(content, str) else "",
        tool_calls=tuple(names),
        raw=event,
    )


def user_request_text(content: str) -> str:
    """The user's own words: unwrap ``<USER_REQUEST>`` and drop client blocks."""
    match = _REQUEST_RE.search(content)
    text = match.group(1) if match else content
    text = _DROP_BLOCKS_RE.sub("", text)
    return text.strip()


def is_compact_request(content: str) -> bool:
    text = user_request_text(content)
    return text == COMPACT_COMMAND or text.startswith(COMPACT_COMMAND + " ")


def _memory_hint(call: dict) -> str:
    name = str(call.get("name", "?"))
    args = call.get("args")
    # MCP tools reach agy through call_mcp_tool; the memory tool name and its
    # slug/query live inside the arguments.  Only memory tools may contribute
    # an argument hint (general tool inputs are a secret + size surface).
    if isinstance(args, dict):
        inner = args.get("ToolName") or args.get("tool_name") or args.get("name")
        if isinstance(inner, str) and "memory_" in inner:
            name = inner
            params = args.get("Arguments") or args.get("arguments") or args.get("args")
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except ValueError:
                    params = None
            if isinstance(params, dict):
                hint = params.get("slug") or params.get("id_or_slug") or params.get("query")
                if isinstance(hint, str) and hint.strip():
                    name += " " + strip_secrets(hint)[0][:120]
    return strip_secrets(name)[0]


def step_prose(event: dict, *, per_block: int | None = None) -> list[str]:
    """Digest lines for one step: user words, model prose, tool NAMES only.

    Tool results, thinking, and every non-memory tool argument are excluded
    (the secret + size surface), matching the Claude and Codex digests.
    """
    step = parse_step(event)
    if step is None:
        return []
    lines: list[str] = []
    if step.is_user_input:
        text = user_request_text(step.content)
        if text:
            lines.append(f"[user] {_bounded(strip_secrets(text)[0], per_block)}")
    elif step.is_model_response:
        text = step.content.strip()
        if text:
            lines.append(
                f"[assistant] {_bounded(strip_secrets(text)[0], per_block)}")
        calls = step.raw.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict):
                    lines.append(f"[assistant tool: {_memory_hint(call)}]")
    return lines


def _bounded(text: str, per_block: int | None) -> str:
    return text if per_block is None else text[:per_block]


def read_tail_steps(path: str | Path, *, max_bytes: int = TAIL_BYTES) -> list[Step]:
    """Parse the complete lines in the last ``max_bytes`` of a transcript.

    A live file can end mid-line or mid-character; such a tail line is
    skipped, never raised.  Returns steps in file order.
    """
    steps: list[Step] = []
    try:
        file = Path(path)
        size = file.stat().st_size
        with file.open("rb") as fh:
            start = max(0, size - max_bytes)
            fh.seek(start)
            data = fh.read()
    except OSError:
        return steps
    if start:
        boundary = data.find(b"\n")
        data = data[boundary + 1:] if boundary >= 0 else b""
    for raw in data.splitlines():
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(event, dict):
            step = parse_step(event)
            if step is not None:
                steps.append(step)
    return steps


def last_user_input(steps: list[Step]) -> Step | None:
    for step in reversed(steps):
        if step.is_user_input:
            return step
    return None


def manual_compaction(steps: list[Step]) -> Step | None:
    """The trailing ``/compact`` request, when the current turn is one."""
    step = last_user_input(steps)
    if step is not None and is_compact_request(step.content):
        return step
    return None


def compaction_summary(steps: list[Step], request_index: int) -> str | None:
    """The model response that answered the ``/compact`` request."""
    for step in steps:
        if step.index > request_index and step.is_model_response:
            return step.content.strip() or None
        if step.index > request_index and step.is_user_input:
            return None
    return None


def latest_auto_compaction(steps: list[Step]) -> Step | None:
    """The newest automatic-compaction marker step in the tail, if any."""
    for step in reversed(steps):
        if step.type in AUTO_COMPACTION_TYPES or (
                step.source == "SYSTEM" and AUTO_COMPACTION_TAG in step.content):
            return step
    return None


def auto_compaction_summary(step: Step) -> str | None:
    text = step.content
    if not text:
        for key in ("summary", "checkpoint_summary"):
            value = step.raw.get(key)
            if isinstance(value, str):
                text = value
                break
    text = text.replace(AUTO_COMPACTION_TAG, "").replace("</CONTEXT_SUMMARY>", "")
    text = text.strip()
    return text or None
