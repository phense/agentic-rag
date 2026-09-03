from __future__ import annotations

import subprocess
from pathlib import Path

from agentic_rag.continuity import capture


def payload(root: Path, transcript_path: Path | None = None) -> dict[str, object]:
    return {
        "session_id": "session-1",
        "turn_id": "turn-7",
        "hook_event_name": "PreCompact",
        "trigger": "auto",
        "cwd": str(root),
        "transcript_path": str(transcript_path) if transcript_path else None,
    }


def fake_git_for(root: Path, *, branch: str = "feat/x", status: str = ""):
    outputs = {
        ("rev-parse", "--show-toplevel"): str(root),
        ("rev-parse", "--git-dir"): ".git",
        ("rev-parse", "--git-common-dir"): ".git",
        ("branch", "--show-current"): branch,
        ("rev-parse", "HEAD"): "abc123",
        ("status", "--short"): status,
    }
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        command = tuple(argv[3:])
        return subprocess.CompletedProcess(argv, 0, outputs[command] + "\n", "")

    run.calls = calls
    return run


def test_capture_records_bounded_git_state_with_safe_invocations(tmp_path):
    fake_git = fake_git_for(tmp_path, status="M file.py\n" + "x" * 5_000)

    checkpoint = capture.capture_snapshot(payload(tmp_path), run=fake_git)

    assert checkpoint.project_root == str(tmp_path.resolve())
    assert checkpoint.cwd == str(tmp_path.resolve())
    assert checkpoint.git["branch"] == "feat/x"
    assert checkpoint.git["head"] == "abc123"
    assert len(checkpoint.git["status"]) <= 4_000
    assert checkpoint.warnings == ("git status truncated",)
    assert [call[0][3:] for call in fake_git.calls] == [
        ["rev-parse", "--show-toplevel"],
        ["rev-parse", "--git-dir"],
        ["rev-parse", "--git-common-dir"],
        ["branch", "--show-current"],
        ["rev-parse", "HEAD"],
        ["status", "--short"],
    ]
    assert all(call[0][:3] == ["git", "-C", str(tmp_path)] for call in fake_git.calls)
    assert all(call[1]["shell"] is False for call in fake_git.calls)
    assert all(call[1]["timeout"] > 0 for call in fake_git.calls)


def test_capture_labels_detached_head_and_resolves_git_paths(tmp_path):
    fake_git = fake_git_for(tmp_path, branch="")

    checkpoint = capture.capture_snapshot(payload(tmp_path), run=fake_git)

    assert checkpoint.git["branch"] == "detached HEAD"
    assert checkpoint.git["git_dir"] == str((tmp_path / ".git").resolve())
    assert checkpoint.git["git_common_dir"] == str((tmp_path / ".git").resolve())


def test_capture_non_git_and_missing_transcript_still_has_stable_cursor(tmp_path):
    def not_a_repo(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 128, "", "not a git repository")

    checkpoint = capture.capture_snapshot(
        {"session_id": "s", "cwd": str(tmp_path), "transcript_path": None},
        run=not_a_repo,
    )
    repeated = capture.capture_snapshot(
        {"session_id": "s", "cwd": str(tmp_path), "transcript_path": None},
        run=not_a_repo,
    )

    assert checkpoint.project_root is None
    assert checkpoint.git == {}
    assert checkpoint.cursor.startswith("event:")
    assert checkpoint.cursor == repeated.cursor


def test_capture_uses_digest_cursor_and_fingerprints_metadata_not_content(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        '{"uuid":"event-9","message":{"role":"user","content":"TOP SECRET BODY"}}\n'
    )

    checkpoint = capture.capture_snapshot(
        payload(tmp_path, transcript), run=fake_git_for(tmp_path)
    )

    assert checkpoint.cursor == "event-9"
    assert checkpoint.transcript_fingerprint.startswith("sha256:")
    assert "TOP SECRET BODY" not in checkpoint.transcript_fingerprint
    assert "session.jsonl" not in checkpoint.transcript_fingerprint


def test_capture_discovers_only_bounded_authoritative_artifact_paths(tmp_path):
    for filename in ("AGENTS.md", "CLAUDE.md", "BACKLOG.md", "FEATURES.md"):
        (tmp_path / filename).write_text(f"body of {filename}")
    specs = tmp_path / "docs" / "superpowers" / "specs"
    plans = tmp_path / "docs" / "superpowers" / "plans"
    specs.mkdir(parents=True)
    plans.mkdir(parents=True)
    for index in range(20):
        (specs / f"{index:02d}.md").write_text("large body " * 100)
    (plans / "plan.md").write_text("plan body")
    nested = specs / "nested"
    nested.mkdir()
    (nested / "must-not-be-found.md").write_text("nested body")
    (tmp_path / "arbitrary.md").write_text("not authoritative")

    checkpoint = capture.capture_snapshot(payload(tmp_path), run=fake_git_for(tmp_path))

    assert len(checkpoint.artifacts) == 16
    assert checkpoint.artifacts == tuple(sorted(checkpoint.artifacts))
    assert "AGENTS.md" in checkpoint.artifacts
    assert "arbitrary.md" not in checkpoint.artifacts
    assert not any("nested" in artifact for artifact in checkpoint.artifacts)
    assert all("body" not in artifact for artifact in checkpoint.artifacts)
    assert "artifact list truncated" in checkpoint.warnings


def test_capture_degrades_when_git_times_out(tmp_path):
    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    checkpoint = capture.capture_snapshot(payload(tmp_path), run=timed_out)

    assert checkpoint.project_root is None
    assert checkpoint.cursor.startswith("event:")
    assert checkpoint.warnings == ("git rev-parse --show-toplevel timed out",)


def test_capture_honors_configured_status_and_artifact_caps(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("instructions")
    (tmp_path / "BACKLOG.md").write_text("work")
    config = tmp_path / "config.toml"
    config.write_text(
        "[continuity]\n"
        "status_max_chars = 5\n"
        "artifact_max = 1\n"
    )
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(config))

    checkpoint = capture.capture_snapshot(
        payload(tmp_path), run=fake_git_for(tmp_path, status="M abcdef")
    )

    assert checkpoint.git["status"] == "M abc"
    assert checkpoint.artifacts == ("AGENTS.md",)
    assert checkpoint.warnings == ("git status truncated", "artifact list truncated")
