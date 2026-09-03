from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from agentic_rag.integrations.codex.config import merge_config
from agentic_rag.integrations.codex.hooks import merge_hooks
from agentic_rag.integrations.codex.install import (
    CodexPaths,
    install_codex,
    restore_codex,
)


HOME = Path("/Users/tester")
PYTHON = "/tmp/test-venv/bin/python"


class SuccessfulCodex:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        stdout = "codex-cli 0.152.1\n" if command[-1] == "--version" else ""
        if command[-1] == "--help":
            stdout = "--strict-config\n--listen\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")


def codex_paths(tmp_path: Path) -> CodexPaths:
    return CodexPaths.for_home(tmp_path)


def test_merge_config_preserves_comments_unknown_keys_and_sets_values():
    source = '# mine\ncustom = "keep"\n[features]\nhooks = true\n'

    merged = merge_config(source, home=HOME)

    assert "# mine" in merged
    assert 'custom = "keep"' in merged
    parsed = tomllib.loads(merged)
    assert parsed["model_context_window"] == 600000
    assert parsed["model_auto_compact_token_limit"] == 500000
    assert parsed["model_auto_compact_token_limit_scope"] == "total"
    assert parsed["experimental_compact_prompt_file"] == (
        "/Users/tester/.codex/compact_prompt.md"
    )
    assert parsed["features"] == {"hooks": True, "memories": True}
    assert parsed["memories"] == {
        "generate_memories": True,
        "use_memories": True,
        "disable_on_external_context": False,
        "min_rollout_idle_hours": 6,
        "max_rollout_age_days": 90,
        "max_rollouts_per_startup": 32,
        "max_raw_memories_for_consolidation": 1024,
        "max_unused_days": 180,
        "min_rate_limit_remaining_percent": 15,
        "extract_model": "gpt-5.6-luna",
        "consolidation_model": "gpt-5.6-luna",
    }
    assert merge_config(merged, home=HOME) == merged


def test_merge_hooks_installs_each_owned_lifecycle_event_once():
    merged = merge_hooks({}, PYTHON)

    assert set(merged["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "Stop",
        "PreCompact",
        "PostCompact",
        "SessionEnd",
    }
    for event, entries in merged["hooks"].items():
        owned = [
            handler
            for entry in entries
            for handler in entry["hooks"]
            if "agentic_rag.hooks." in handler["command"]
        ]
        assert len(owned) == 1, event
        assert owned[0]["command"].startswith(PYTHON)
    assert merged["hooks"]["SessionStart"][-1]["matcher"] == (
        "startup|resume|clear|compact"
    )
    assert merged["hooks"]["PreCompact"][-1]["matcher"] == "manual|auto"
    assert merged["hooks"]["PostCompact"][-1]["matcher"] == "manual|auto"


def test_merge_hooks_replaces_only_owned_commands_and_preserves_foreign_data():
    herdr = {
        "type": "command",
        "command": "/foreign/herdr-agent-state.sh",
        "timeout": 3,
    }
    source = {
        "custom": {"preserve": True},
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "foreign-matcher",
                    "metadata": "keep",
                    "hooks": [
                        herdr,
                        {
                            "type": "command",
                            "command": (
                                "/old/python -m "
                                "agentic_rag.hooks.session_start"
                            ),
                        },
                    ],
                },
                {"hooks": [dict(herdr)]},
            ],
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "guard.sh"},
                        {
                            "type": "command",
                            "command": "/old/python -m agentic_rag.hooks.removed",
                        },
                    ],
                }
            ],
        },
    }

    merged = merge_hooks(source, PYTHON)

    assert merged["custom"] == {"preserve": True}
    assert merged["hooks"]["SessionStart"][0] == {
        "matcher": "foreign-matcher",
        "metadata": "keep",
        "hooks": [herdr],
    }
    session_commands = [
        handler["command"]
        for entry in merged["hooks"]["SessionStart"]
        for handler in entry["hooks"]
    ]
    assert session_commands.count("/foreign/herdr-agent-state.sh") == 2
    assert sum("agentic_rag.hooks." in c for c in session_commands) == 1
    assert all("/old/python" not in c for c in session_commands)
    assert merged["hooks"]["PreToolUse"] == [
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "guard.sh"}],
        }
    ]
    assert merge_hooks(merged, PYTHON) == merged
    assert source["hooks"]["SessionStart"][0]["hooks"][1]["command"].startswith(
        "/old/python"
    )


def test_install_codex_stages_validates_backs_up_and_can_restore(tmp_path):
    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    original_config = '# mine\ncustom = "keep"\n'
    original_hooks = {
        "metadata": {"keep": True},
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "herdr-agent-state.sh"}]},
                {"hooks": [{"type": "command", "command": "herdr-agent-state.sh"}]},
            ],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"command": "guard.sh"}]}
            ],
        },
    }
    paths.config_path.write_text(original_config)
    paths.hooks_path.write_text(json.dumps(original_hooks) + "\n")
    paths.prompt_path.write_text("old prompt\n")
    runner = SuccessfulCodex()

    report = install_codex(paths, run=runner)

    assert report.changed_paths == (
        paths.config_path,
        paths.hooks_path,
        paths.prompt_path,
    )
    assert len(report.backups) == 3
    assert all(backup.backup_path.exists() for backup in report.backups)
    assert report.foreign_hook_duplicates == ("herdr-agent-state.sh",)
    assert report.codex_version == "codex-cli 0.152.1"
    assert report.runtime_validation == "managed configuration validated"
    assert tomllib.loads(paths.config_path.read_text())["model_context_window"] == 600000
    installed_hooks = json.loads(paths.hooks_path.read_text())
    assert installed_hooks["metadata"] == {"keep": True}
    assert installed_hooks["hooks"]["PreToolUse"] == original_hooks["hooks"]["PreToolUse"]
    assert paths.prompt_path.read_text().startswith("# Codex compact continuation prompt")
    assert any("--strict-config" in command for command, _ in runner.calls)

    restored = restore_codex(report)

    assert restored == report.changed_paths
    assert paths.config_path.read_text() == original_config
    assert json.loads(paths.hooks_path.read_text()) == original_hooks
    assert paths.prompt_path.read_text() == "old prompt\n"


def test_install_codex_check_reports_changes_without_writing(tmp_path):
    paths = codex_paths(tmp_path)
    before = set(tmp_path.rglob("*"))

    report = install_codex(
        paths, check=True, run=SuccessfulCodex()
    )

    assert report.check is True
    assert report.changed_paths == (
        paths.config_path,
        paths.hooks_path,
        paths.prompt_path,
    )
    assert report.backups == ()
    assert set(tmp_path.rglob("*")) == before


def test_install_codex_accepts_empty_existing_files(tmp_path):
    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    for path in paths.targets:
        path.write_text("")

    report = install_codex(paths, run=SuccessfulCodex())

    assert report.changed_paths == paths.targets
    assert len(report.backups) == 3
    assert tomllib.loads(paths.config_path.read_text())["features"]["memories"] is True
    assert json.loads(paths.hooks_path.read_text())["hooks"]
    assert paths.prompt_path.read_text().strip()


@pytest.mark.parametrize("bad_path", ["config", "hooks"])
def test_install_codex_invalid_input_leaves_all_files_unchanged(
    tmp_path, bad_path
):
    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text('custom = "keep"\n')
    paths.hooks_path.write_text('{"metadata": "keep"}\n')
    paths.prompt_path.write_text("old prompt\n")
    if bad_path == "config":
        paths.config_path.write_text("not = [valid TOML")
    else:
        paths.hooks_path.write_text('{"not": "valid"')
    originals = {path: path.read_bytes() for path in paths.targets}

    with pytest.raises(RuntimeError, match="valid"):
        install_codex(paths, run=SuccessfulCodex())

    assert {path: path.read_bytes() for path in paths.targets} == originals
    assert not tuple(paths.config_path.parent.glob("*.bak.*"))
    assert not tuple(paths.config_path.parent.glob("*.tmp"))


def test_install_codex_staging_failure_leaves_live_files_unchanged(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    for path, text in zip(paths.targets, ('custom = "keep"\n', "{}\n", "old\n")):
        path.write_text(text)
    originals = {path: path.read_bytes() for path in paths.targets}
    real_stage = install_module._stage_text
    calls = 0

    def fail_second(path, text):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated staging failure")
        return real_stage(path, text)

    monkeypatch.setattr(install_module, "_stage_text", fail_second)

    with pytest.raises(OSError, match="staging"):
        install_codex(paths, run=SuccessfulCodex())

    assert {path: path.read_bytes() for path in paths.targets} == originals
    assert not tuple(paths.config_path.parent.glob("*.bak.*"))


def test_install_codex_rolls_back_a_partial_replace_failure(tmp_path, monkeypatch):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    for path, text in zip(paths.targets, ('custom = "keep"\n', "{}\n", "old\n")):
        path.write_text(text)
    originals = {path: path.read_bytes() for path in paths.targets}
    real_replace = install_module.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(install_module.os, "replace", fail_second)

    with pytest.raises(OSError, match="replace"):
        install_codex(paths, run=SuccessfulCodex())

    assert {path: path.read_bytes() for path in paths.targets} == originals


def test_install_codex_is_idempotent(tmp_path):
    paths = codex_paths(tmp_path)
    first = install_codex(paths, run=SuccessfulCodex())

    second = install_codex(paths, run=SuccessfulCodex())

    assert len(first.changed_paths) == 3
    assert second.changed_paths == ()
    assert second.backups == ()


def test_install_codex_can_replace_only_one_changed_artifact(tmp_path):
    paths = codex_paths(tmp_path)
    install_codex(paths, run=SuccessfulCodex())
    paths.hooks_path.write_text("{}\n")

    report = install_codex(paths, run=SuccessfulCodex())

    assert report.changed_paths == (paths.hooks_path,)
    assert len(report.backups) == 1
    assert json.loads(paths.hooks_path.read_text())["hooks"]


def test_install_codex_reports_when_runtime_validator_is_unavailable(tmp_path):
    paths = codex_paths(tmp_path)

    def run(command, **kwargs):
        stdout = "codex-cli old\n" if command[-1] == "--version" else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    report = install_codex(paths, check=True, run=run)

    assert report.codex_version == "codex-cli old"
    assert "rollout step" in report.runtime_validation


def test_install_codex_reports_when_runtime_probe_cannot_be_started(tmp_path):
    paths = codex_paths(tmp_path)
    calls = 0

    def run(command, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                command, 0, "codex-cli partial\n", ""
            )
        raise OSError("probe unavailable")

    report = install_codex(paths, check=True, run=run)

    assert report.codex_version == "codex-cli partial"
    assert "rollout step" in report.runtime_validation


def test_install_codex_reports_when_strict_probe_is_not_supported(tmp_path):
    paths = codex_paths(tmp_path)

    def run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli old\n", "")
        if command[-1] == "--help":
            return subprocess.CompletedProcess(
                command, 0, "--strict-config\n--listen\n", ""
            )
        return subprocess.CompletedProcess(
            command,
            2,
            "",
            "`--strict-config` is not supported for `codex app-server`",
        )

    report = install_codex(paths, check=True, run=run)

    assert "rollout step" in report.runtime_validation


def test_install_codex_runtime_rejection_leaves_live_files_unchanged(tmp_path):
    paths = codex_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text('custom = "keep"\n')
    original = paths.config_path.read_bytes()

    def run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli 0.152.1\n", "")
        if command[-1] == "--help":
            return subprocess.CompletedProcess(command, 0, "--strict-config\n--listen\n", "")
        return subprocess.CompletedProcess(command, 2, "", "unsupported key")

    with pytest.raises(RuntimeError, match="unsupported key"):
        install_codex(paths, run=run)

    assert paths.config_path.read_bytes() == original
    assert not paths.hooks_path.exists()
    assert not paths.prompt_path.exists()
