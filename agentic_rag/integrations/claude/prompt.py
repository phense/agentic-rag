"""Versioned compact instructions delivered through PreCompact stdout."""
from __future__ import annotations

from importlib import resources

MAX_PROMPT_CHARS = 4000
CHECKPOINT_LINE_PREFIX = "agentic-rag checkpoint: "


def compact_prompt_text() -> str:
    text = resources.files("assets").joinpath(
        "claude", "compact_prompt.md"
    ).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Claude compact prompt asset is empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"Claude compact prompt asset exceeds {MAX_PROMPT_CHARS} characters"
        )
    return text
