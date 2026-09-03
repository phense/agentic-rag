from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agentic_rag.continuity.model import Checkpoint
from agentic_rag.continuity.render import MIN_RENDER_CHARS, render_checkpoint


LARGE_SPEC_BODY = "copied specification body " * 200


def checkpoint() -> Checkpoint:
    now = datetime.now(UTC)
    return Checkpoint(
        id="checkpoint-123",
        session_id="session-1",
        turn_id="turn-7",
        cursor="event-9",
        source="PreCompact",
        trigger="auto",
        cwd="/work/project",
        project_root="/work/project",
        transcript_fingerprint="sha256:abc",
        git={"branch": "feat/x", "head": "abc123", "status": " M app.py"},
        snapshot={"large_spec_body": LARGE_SPEC_BODY},
        enrichment={
            "goal": "Ship deterministic continuation capture",
            "success_criteria": ["focused tests pass", "render stays bounded"],
            "remaining_steps": ["wire lifecycle hooks"],
            "tests": ["pytest capture/render: passed"],
            "processes": ["worker pid 42 was observed before compaction"],
            "external_states": ["provider was healthy at capture time"],
            "blockers": ["hook integration is not implemented"],
            "next_action": "Implement the lifecycle hook integration",
            "rag_slugs": ["relevant-slug"],
        },
        references=("AGENTS.md", "docs/superpowers/plans/continuity.md"),
        warnings=("git status truncated",),
        state="open",
        quality="enriched",
        compacted_at=None,
        created_at=now,
        updated_at=now,
    )


def test_renderer_is_bounded_ordered_and_reference_oriented():
    saved = checkpoint()

    text = render_checkpoint(saved, max_chars=800)

    assert len(text) <= 800
    assert "Checkpoint checkpoint-123" in text
    assert "Blockers:" in text
    assert "hook integration is not implemented" in text
    assert "Next exact action" in text
    assert "Implement the lifecycle hook integration" in text
    assert "[[relevant-slug]]" in text
    assert LARGE_SPEC_BODY not in text
    assert text.index("Blockers:") < text.index("Next exact action")


def test_renderer_labels_snapshot_and_stale_processes():
    saved = replace(checkpoint(), quality="snapshot")

    text = render_checkpoint(saved, max_chars=2_000)

    assert "semantic enrichment pending" in text
    assert "revalidate" in text.lower()
    assert "worker pid 42" in text
    assert "provider was healthy" in text


def test_renderer_reports_freshness_and_repository_mismatch():
    saved = replace(
        checkpoint(),
        created_at=datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 3, 10, 5, tzinfo=UTC),
    )

    text = render_checkpoint(
        saved, max_chars=2_000,
        current_cwd="/work/other/subdir",
        current_project_root="/work/other",
        now=datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
    )

    assert "Captured: 2026-09-03T10:00:00+00:00" in text
    assert "Updated: 2026-09-03T10:05:00+00:00" in text
    assert "age=2h" in text
    assert "HISTORICAL/MISMATCHED" in text
    assert "current_project=/work/other" in text


def test_renderer_never_calls_unverified_cwd_a_current_project():
    text = render_checkpoint(
        checkpoint(), max_chars=2_000,
        current_cwd="/work/other", current_project_root=None,
    )

    assert "HISTORICAL/UNVERIFIED" in text
    assert "current_cwd=/work/other" in text
    assert "CURRENT project match" not in text


def test_renderer_keeps_freshness_and_applicability_at_minimum_budget():
    text = render_checkpoint(
        checkpoint(), max_chars=MIN_RENDER_CHARS,
        current_cwd="/work/other", current_project_root=None,
    )

    assert len(text) <= MIN_RENDER_CHARS
    assert "Freshness:" in text
    assert "Repository applicability:" in text
    assert "HISTORICAL" in text


def test_renderer_retains_identity_blocker_and_next_action_under_pressure():
    saved = replace(
        checkpoint(),
        enrichment={
            **checkpoint().enrichment,
            "goal": "g" * 2_000,
            "success_criteria": ["c" * 2_000],
            "blockers": ["blocked by review"],
            "next_action": "run the focused test",
        },
    )

    text = render_checkpoint(saved, max_chars=MIN_RENDER_CHARS)

    assert len(text) <= MIN_RENDER_CHARS
    assert "checkpoint-123" in text
    assert "Goal:" in text
    assert "Blockers:" in text and "blocked by review" in text
    assert "Next exact action:" in text and "run the focused test" in text


def test_renderer_rejects_non_positive_budget():
    for max_chars in (0, -1):
        try:
            render_checkpoint(checkpoint(), max_chars=max_chars)
        except ValueError as exc:
            assert "positive" in str(exc)
        else:
            raise AssertionError("non-positive render budget was accepted")


def test_renderer_rejects_budget_below_documented_minimum():
    with pytest.raises(ValueError, match=str(MIN_RENDER_CHARS)):
        render_checkpoint(checkpoint(), max_chars=MIN_RENDER_CHARS - 1)


def test_renderer_minimum_retains_meaningful_mandatory_values():
    saved = replace(
        checkpoint(),
        enrichment={
            **checkpoint().enrichment,
            "goal": "g" * 2_000,
            "blockers": ["blocked by required security review " + "b" * 2_000],
            "next_action": "run the bounded capture regression tests " + "n" * 2_000,
        },
    )

    text = render_checkpoint(saved, max_chars=MIN_RENDER_CHARS)

    assert len(text) <= MIN_RENDER_CHARS
    assert "Checkpoint checkpoint-123" in text
    assert "Blockers: blocked by required" in text
    assert "Next exact action: run the bounded" in text


def test_renderer_includes_labelled_handoff_and_drops_it_before_mandatory():
    from datetime import timedelta
    saved = replace(checkpoint(), handoff="Goal: finish\nNext: run the suite",
                    handoff_at=datetime.now(UTC))

    text = render_checkpoint(saved, max_chars=2000,
                             current_project_root="/work/project")
    assert "Handoff (Claude compact summary, CURRENT" in text
    assert "Goal: finish\nNext: run the suite" in text

    old = replace(saved, handoff_at=datetime.now(UTC) - timedelta(days=45))
    text = render_checkpoint(old, max_chars=2000, stale_days=30)
    assert "Handoff (Claude compact summary, HISTORICAL" in text

    tiny = render_checkpoint(saved, max_chars=MIN_RENDER_CHARS)
    assert "Handoff" not in tiny
    assert "Next exact action" in tiny and "Blockers:" in tiny


def test_renderer_handoff_is_dropped_before_goal_and_after_references():
    saved = replace(checkpoint(), handoff="H" * 600, handoff_at=datetime.now(UTC))

    text = render_checkpoint(saved, max_chars=900)

    assert "Goal:" in text
    assert "Handoff" not in text or "H" * 600 not in text


def test_renderer_truncates_full_length_handoff_instead_of_dropping_it():
    from agentic_rag.continuity.model import HANDOFF_TRUNCATION_MARKER
    # Shipped defaults: handoff_max_chars == render_max_chars == 8000.  A
    # handoff that fills its bound must still surface at SessionStart, and
    # its presence must not evict unrelated reference/volatile sections.
    body = " ".join(f"line{index}" for index in range(2000))[:8000]
    saved = replace(checkpoint(), handoff=body, handoff_at=datetime.now(UTC))

    text = render_checkpoint(saved, max_chars=8000,
                             current_project_root="/work/project")

    assert len(text) <= 8000
    assert "Handoff (Claude compact summary, CURRENT" in text
    assert body[:2000] in text
    assert HANDOFF_TRUNCATION_MARKER in text
    assert "Artifacts/slugs: AGENTS.md" in text and "[[relevant-slug]]" in text
    assert "Volatile state (revalidate): processes=worker pid 42" in text
    assert "Warnings: git status truncated" in text
    assert "Next exact action: Implement the lifecycle hook integration" in text
