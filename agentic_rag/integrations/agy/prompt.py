"""Versioned compact instructions injected before a ``/compact`` turn."""
from __future__ import annotations

from importlib import resources

MAX_PROMPT_CHARS = 4000
CHECKPOINT_LINE_PREFIX = "agentic-rag checkpoint: "


def compact_prompt_text() -> str:
    text = resources.files("assets").joinpath(
        "agy", "compact_prompt.md"
    ).read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Antigravity compact prompt asset is empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise ValueError(
            f"Antigravity compact prompt asset exceeds {MAX_PROMPT_CHARS} characters"
        )
    return text
