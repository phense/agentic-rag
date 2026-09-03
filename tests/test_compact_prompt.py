from __future__ import annotations

from importlib import resources

import pytest


def compact_prompt_text() -> str:
    resource = resources.files("assets").joinpath(
        "codex", "compact_prompt.md"
    )
    return resource.read_text(encoding="utf-8")


@pytest.mark.parametrize("phrase", [
    "objective", "success criteria", "user instructions", "decisions",
    "worktree", "uncommitted", "test results", "active processes",
    "blockers", "next exact action", "agentic-rag slugs", "revalidate",
])
def test_compact_prompt_contains_continuity_contract(phrase: str):
    assert phrase.lower() in compact_prompt_text().lower()


def test_compact_prompt_is_versioned_and_reference_oriented():
    text = compact_prompt_text().lower()

    assert "version" in text
    assert "evidence" in text
    assert "unverified" in text
    assert "user-owned" in text
    assert "artifact" in text
    assert "slug" in text
    assert "do not ask" in text or "without asking" in text
    assert "body" in text


def test_compact_prompt_explicitly_generates_a_bounded_handoff_from_history():
    text = compact_prompt_text().lower()

    assert "active conversation history" in text
    assert "handoff summary" in text
    assert "bounded" in text
    assert "timestamp" in text
    assert "current" in text and "historical" in text
    assert "canonical" in text and "[[slug]]" in text
    assert "do not continue the task" in text
