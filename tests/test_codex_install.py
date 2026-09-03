from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

from agentic_rag.integrations.codex.config import merge_config
from agentic_rag.integrations.codex.hooks import (
    duplicate_herdr_commands,
    merge_hooks,
)
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


def seed_codex_files(paths: CodexPaths) -> dict[Path, bytes]:
    paths.config_path.parent.mkdir(parents=True)
    for path, text in zip(
        paths.targets, ('custom = "keep"\n', "{}\n", "old prompt\n")
    ):
        path.write_text(text)
    return {path: path.read_bytes() for path in paths.targets}


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
    expected = {
        "SessionStart": ("startup|resume|clear|compact", 10, 10000),
        "UserPromptSubmit": (None, 5, 5000),
        "Stop": (None, 10, None),
        "PreCompact": ("manual|auto", 3, None),
        "PostCompact": ("manual|auto", 3, None),
        "SessionEnd": (None, 3, None),
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
        matcher, timeout, context_limit = expected[event]
        entry = entries[-1]
        assert entry.get("matcher") == matcher
        assert owned[0]["timeout"] == timeout
        assert "additionalContextLimit" not in entry
        assert owned[0].get("additionalContextLimit") == context_limit


def test_merge_hooks_shell_quotes_python_executable():
    python = "/tmp/venv with spaces/bin/py;not-a-command"

    merged = merge_hooks({}, python)

    commands = [
        handler["command"]
        for entries in merged["hooks"].values()
        for entry in entries
        for handler in entry["hooks"]
    ]
    assert all(
        command.startswith("'/tmp/venv with spaces/bin/py;not-a-command' -m ")
        for command in commands
    )


def test_duplicate_herdr_diagnostic_contains_only_safe_basename_and_count():
    secret = "do-not-leak-this-token"
    hooks = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"command": f"TOKEN={secret} /x/herdr-agent-state.sh"}]},
                {"hooks": [{"command": f"/x/herdr-agent-state.sh --key={secret}"}]},
            ]
        }
    }

    diagnostics = duplicate_herdr_commands(hooks)

    assert [(item.basename, item.count) for item in diagnostics] == [
        ("herdr-agent-state.sh", 2)
    ]
    assert secret not in repr(diagnostics)


def test_install_report_never_contains_inline_foreign_hook_secret(tmp_path):
    secret = "do-not-leak-this-token"
    paths = codex_paths(tmp_path)
    paths.hooks_path.parent.mkdir(parents=True)
    paths.hooks_path.write_text(json.dumps({
        "hooks": {
            "SessionStart": [
                {"hooks": [{"command": f"TOKEN={secret} /x/herdr-agent-state.sh"}]},
                {"hooks": [{"command": f"/x/herdr-agent-state.sh --key={secret}"}]},
            ]
        }
    }))

    report = install_codex(paths, check=True, run=SuccessfulCodex())

    assert secret not in repr(report.foreign_hook_duplicates)
    assert [
        (item.basename, item.count)
        for item in report.foreign_hook_duplicates
    ] == [("herdr-agent-state.sh", 2)]


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
    assert [
        (item.basename, item.count)
        for item in report.foreign_hook_duplicates
    ] == [("herdr-agent-state.sh", 2)]
    assert report.codex_version == "codex-cli 0.152.1"
    assert report.runtime_validation == "managed configuration and hooks validated"
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
    assert "ephemeral isolated CODEX_HOME" in report.probe_isolation
    assert set(tmp_path.rglob("*")) == before


def test_probe_isolates_and_bounds_every_codex_subprocess(tmp_path, monkeypatch):
    paths = codex_paths(tmp_path)
    real_codex_home = tmp_path / "real-codex-home"
    real_codex_home.mkdir()
    sentinel = real_codex_home / "sentinel"
    sentinel.write_text("untouched")
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))
    runner = SuccessfulCodex()

    report = install_codex(paths, check=True, run=runner)

    probe_homes = {kwargs["env"]["CODEX_HOME"] for _, kwargs in runner.calls}
    assert len(probe_homes) == 1
    assert str(real_codex_home) not in probe_homes
    assert all(kwargs["timeout"] == 10 for _, kwargs in runner.calls)
    assert not Path(probe_homes.pop()).exists()
    assert sentinel.read_text() == "untouched"
    assert not paths.config_path.parent.exists()
    assert "ephemeral isolated CODEX_HOME" in report.probe_isolation


def test_runtime_probe_loads_generated_hooks_json(tmp_path):
    paths = codex_paths(tmp_path)
    seen = {}

    def run(command, **kwargs):
        if "app-server" in command and "--strict-config" in command:
            probe_home = Path(kwargs["env"]["CODEX_HOME"])
            seen["hooks"] = json.loads(
                (probe_home / "hooks.json").read_text(encoding="utf-8"))
            seen["config"] = (probe_home / "config.toml").read_text(
                encoding="utf-8")
        return SuccessfulCodex()(command, **kwargs)

    report = install_codex(paths, check=True, run=run)

    assert report.runtime_validation == "managed configuration and hooks validated"
    session_handler = seen["hooks"]["hooks"]["SessionStart"][0]["hooks"][0]
    assert session_handler["additionalContextLimit"] == 10000
    assert "additionalContextLimit" not in seen["hooks"]["hooks"]["SessionStart"][0]
    assert "model_context_window = 600000" in seen["config"]


def test_probe_timeout_reports_local_only_validation(tmp_path):
    paths = codex_paths(tmp_path)

    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    report = install_codex(paths, check=True, run=run)

    assert "rollout step" in report.runtime_validation
    assert "ephemeral isolated CODEX_HOME" in report.probe_isolation


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


def test_concurrent_edit_during_probe_aborts_without_overwrite(tmp_path):
    paths = codex_paths(tmp_path)
    originals = seed_codex_files(paths)
    edited = b'custom = "concurrent"\n'
    runner = SuccessfulCodex()

    def run(command, **kwargs):
        if not runner.calls:
            paths.config_path.write_bytes(edited)
        return runner(command, **kwargs)

    with pytest.raises(RuntimeError, match="changed concurrently"):
        install_codex(paths, run=run)

    assert paths.config_path.read_bytes() == edited
    assert paths.hooks_path.read_bytes() == originals[paths.hooks_path]
    assert paths.prompt_path.read_bytes() == originals[paths.prompt_path]


def test_partial_failure_does_not_rollback_never_replaced_concurrent_edit(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    originals = seed_codex_files(paths)
    prompt_edit = b"concurrent third-target edit\n"
    real_replace = install_module.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            paths.prompt_path.write_bytes(prompt_edit)
            raise OSError("simulated replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(install_module.os, "replace", fail_second)

    with pytest.raises(OSError, match="replace"):
        install_codex(paths, run=SuccessfulCodex())

    assert paths.config_path.read_bytes() == originals[paths.config_path]
    assert paths.hooks_path.read_bytes() == originals[paths.hooks_path]
    assert paths.prompt_path.read_bytes() == prompt_edit


def test_partial_failure_does_not_overwrite_replaced_target_concurrent_edit(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    concurrent = b'custom = "edited-after-replace"\n'
    real_replace = install_module.os.replace
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            paths.config_path.write_bytes(concurrent)
            raise OSError("simulated replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(install_module.os, "replace", fail_second)

    with pytest.raises(RuntimeError, match="manual recovery"):
        install_codex(paths, run=SuccessfulCodex())

    assert paths.config_path.read_bytes() == concurrent
    assert tuple(paths.config_path.parent.glob("config.toml.bak.*"))


def _create_concurrent_entry(path: Path, kind: str, text: str) -> None:
    if kind == "file":
        path.write_text(text)
    else:
        path.symlink_to(path.parent / f"missing-{text}")


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_publish_create_if_absent_preserves_entry_interposed_after_claim(
    tmp_path, monkeypatch, kind
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    originals = seed_codex_files(paths)
    real_publish = getattr(
        install_module,
        "_publish_no_replace",
        lambda source, target: os.link(source, target),
    )
    injected = False

    def interpose(source, target):
        nonlocal injected
        if target == paths.config_path and not injected:
            injected = True
            _create_concurrent_entry(target, kind, "forward-concurrent")
        return real_publish(source, target)

    monkeypatch.setattr(
        install_module, "_publish_no_replace", interpose, raising=False
    )

    with pytest.raises(RuntimeError, match="manual recovery"):
        install_codex(paths, run=SuccessfulCodex())

    if kind == "file":
        assert paths.config_path.read_text() == "forward-concurrent"
    else:
        assert paths.config_path.is_symlink()
    displaced = tuple(paths.config_path.parent.glob(".config.toml.displaced.*"))
    assert any(path.read_bytes() == originals[paths.config_path] for path in displaced)


def test_absent_target_publish_conflict_retains_unpublished_recovery(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    real_publish = install_module._publish_no_replace
    injected = False

    def interpose(source, target):
        nonlocal injected
        if target == paths.config_path and not injected:
            injected = True
            target.write_text("concurrent creation")
        return real_publish(source, target)

    monkeypatch.setattr(install_module, "_publish_no_replace", interpose)

    with pytest.raises(RuntimeError, match="manual recovery"):
        install_codex(paths, run=SuccessfulCodex())

    assert paths.config_path.read_text() == "concurrent creation"
    recovery = tuple(paths.config_path.parent.glob(".config.toml.unpublished.*"))
    assert len(recovery) == 1
    assert b"model_context_window = 600000" in recovery[0].read_bytes()


def test_publish_conflict_cleanup_retains_stage_if_recovery_rename_fails(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    real_publish = install_module._publish_no_replace
    real_replace = install_module.os.replace
    injected = False

    def interpose_publish(source, target):
        nonlocal injected
        if target == paths.config_path and not injected:
            injected = True
            target.write_text("concurrent creation")
        return real_publish(source, target)

    def fail_recovery_rename(source, target):
        if ".unpublished." in Path(target).name:
            raise OSError("simulated recovery rename failure")
        return real_replace(source, target)

    monkeypatch.setattr(install_module, "_publish_no_replace", interpose_publish)
    monkeypatch.setattr(install_module.os, "replace", fail_recovery_rename)

    with pytest.raises(RuntimeError, match="manual recovery"):
        install_codex(paths, run=SuccessfulCodex())

    assert paths.config_path.read_text() == "concurrent creation"
    recovery = tuple(paths.config_path.parent.glob(".config.toml.*.tmp"))
    assert len(recovery) == 1
    assert b"model_context_window = 600000" in recovery[0].read_bytes()


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_rollback_publish_preserves_entry_interposed_after_claim(
    tmp_path, monkeypatch, kind
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    originals = seed_codex_files(paths)
    real_publish = getattr(
        install_module,
        "_publish_no_replace",
        lambda source, target: os.link(source, target),
    )
    config_publishes = 0

    def interpose(source, target):
        nonlocal config_publishes
        if target == paths.config_path:
            config_publishes += 1
            if config_publishes == 2:
                _create_concurrent_entry(target, kind, "rollback-concurrent")
        if target == paths.hooks_path and ".tmp" in source.name:
            raise OSError("force rollback")
        return real_publish(source, target)

    monkeypatch.setattr(
        install_module, "_publish_no_replace", interpose, raising=False
    )

    with pytest.raises(RuntimeError, match="manual recovery"):
        install_codex(paths, run=SuccessfulCodex())

    if kind == "file":
        assert paths.config_path.read_text() == "rollback-concurrent"
    else:
        assert paths.config_path.is_symlink()
    displaced = tuple(paths.config_path.parent.glob(".config.toml.displaced.*"))
    assert any(path.read_bytes() == originals[paths.config_path] for path in displaced)
    assert paths.hooks_path.read_bytes() == originals[paths.hooks_path]


def test_claim_rejects_symlink_inserted_after_staging(tmp_path, monkeypatch):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    real_claim = getattr(
        install_module,
        "_claim_entry",
        lambda target, displaced: os.rename(target, displaced),
    )
    injected = False

    def interpose(target, displaced):
        nonlocal injected
        if target == paths.config_path and not injected:
            injected = True
            target.unlink()
            target.symlink_to(tmp_path / "missing-concurrent-target")
        return real_claim(target, displaced)

    monkeypatch.setattr(install_module, "_claim_entry", interpose, raising=False)

    with pytest.raises(RuntimeError, match="symbolic link"):
        install_codex(paths, run=SuccessfulCodex())

    assert paths.config_path.is_symlink()


@pytest.mark.parametrize("leaf", ["config_path", "hooks_path", "prompt_path"])
@pytest.mark.parametrize("broken", [False, True])
def test_install_codex_rejects_existing_leaf_symlinks(
    tmp_path, leaf, broken
):
    paths = codex_paths(tmp_path)
    originals = seed_codex_files(paths)
    link = getattr(paths, leaf)
    link.unlink()
    target = tmp_path / f"{leaf}-target"
    if not broken:
        target.write_text("do not change")
    link.symlink_to(target)

    with pytest.raises(RuntimeError, match="symbolic link"):
        install_codex(paths, run=SuccessfulCodex())

    assert link.is_symlink()
    if not broken:
        assert target.read_text() == "do not change"
    for path in paths.targets:
        if path != link:
            assert path.read_bytes() == originals[path]


def test_restore_rejects_a_new_leaf_symlink(tmp_path):
    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    report = install_codex(paths, run=SuccessfulCodex())
    paths.config_path.unlink()
    target = tmp_path / "restore-target"
    target.write_text("do not change")
    paths.config_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="symbolic link"):
        restore_codex(report)

    assert paths.config_path.is_symlink()
    assert target.read_text() == "do not change"


@pytest.mark.parametrize("substitution", ["regular", "symlink"])
def test_restore_aborts_if_backup_reappears_after_staging(
    tmp_path, monkeypatch, substitution
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    report = install_codex(paths, run=SuccessfulCodex())
    managed_before = {
        path: install_module._snapshot(path) for path in paths.targets
    }
    challenged = report.backups[0]
    authenticated = install_module._snapshot(challenged.backup_path)
    real_stage = install_module._stage_bytes
    staged_count = 0

    def interpose(path, content, *, mode=None):
        nonlocal staged_count
        staged = real_stage(path, content, mode=mode)
        staged_count += 1
        if staged_count == len(report.backups):
            challenged.backup_path.unlink(missing_ok=True)
            if substitution == "regular":
                challenged.backup_path.write_text("concurrent backup substitute")
            else:
                challenged.backup_path.symlink_to(
                    tmp_path / "missing-backup-substitute"
                )
        return staged

    monkeypatch.setattr(install_module, "_stage_bytes", interpose)

    with pytest.raises(RuntimeError, match="backup path"):
        restore_codex(report)

    for target, before in managed_before.items():
        after = install_module._snapshot(target)
        assert after.content == before.content
        assert after.identity == before.identity
    if substitution == "regular":
        assert challenged.backup_path.read_text() == "concurrent backup substitute"
    else:
        assert challenged.backup_path.is_symlink()
        assert challenged.backup_path.readlink() == (
            tmp_path / "missing-backup-substitute"
        )
    recovery = tuple(
        challenged.backup_path.parent.glob(
            f".{challenged.backup_path.name}.restore-backup.*"
        )
    )
    assert recovery
    assert any(
        install_module._snapshot(path) == authenticated for path in recovery
    )


def test_restore_publish_never_overwrites_concurrent_entry(tmp_path, monkeypatch):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    report = install_codex(paths, run=SuccessfulCodex())
    installed_before = {
        path: install_module._snapshot(path) for path in paths.targets
    }
    real_publish = install_module._publish_no_replace
    injected = False

    def interpose(source, target):
        nonlocal injected
        if target == paths.config_path and not injected:
            injected = True
            target.write_text("concurrent restore edit")
        return real_publish(source, target)

    monkeypatch.setattr(install_module, "_publish_no_replace", interpose)

    with pytest.raises(RuntimeError, match="manual recovery"):
        restore_codex(report)

    assert paths.config_path.read_text() == "concurrent restore edit"
    assert tuple(paths.config_path.parent.glob(".config.toml.restore.*"))
    for target in (paths.hooks_path, paths.prompt_path):
        assert install_module._snapshot(target) == installed_before[target]
    assert all(record.backup_path.exists() for record in report.backups)
    for record in report.backups:
        claims = tuple(
            record.backup_path.parent.glob(
                f".{record.backup_path.name}.restore-backup.*"
            )
        )
        assert any(
            install_module._snapshot(path).identity == record.identity
            for path in claims
        )


def test_restore_rollback_preserves_same_size_edit_after_publication(
    tmp_path, monkeypatch
):
    from agentic_rag.integrations.codex import install as install_module

    paths = codex_paths(tmp_path)
    seed_codex_files(paths)
    report = install_codex(paths, run=SuccessfulCodex())
    restore_order = tuple(reversed(report.changed_paths))
    first_target, second_target = restore_order[:2]
    backups = {record.target_path: record for record in report.backups}
    installed_before = install_module._snapshot(first_target)
    original = install_module._snapshot(backups[first_target].backup_path)
    assert original.content == b"old prompt\n"
    concurrent = b"user edit!\n"
    assert len(concurrent) == len(original.content)

    real_publish = install_module._publish_no_replace
    managed_publishes = 0
    concurrent_snapshot = None

    def interpose(source, target):
        nonlocal managed_publishes, concurrent_snapshot
        if target not in paths.targets:
            return real_publish(source, target)
        managed_publishes += 1
        if managed_publishes == 1:
            assert target == first_target
            result = real_publish(source, target)
            published = install_module._snapshot(target)
            with target.open("r+b", buffering=0) as stream:
                stream.write(concurrent)
            concurrent_snapshot = install_module._snapshot(target)
            assert concurrent_snapshot.identity.inode == published.identity.inode
            assert concurrent_snapshot.identity.size == published.identity.size
            assert concurrent_snapshot.identity.mode == published.identity.mode
            assert concurrent_snapshot.identity.digest != published.identity.digest
            return result
        if managed_publishes == 2:
            assert target == second_target
            raise OSError("simulated second restore publication failure")
        return real_publish(source, target)

    monkeypatch.setattr(install_module, "_publish_no_replace", interpose)

    with pytest.raises(RuntimeError, match="manual recovery"):
        restore_codex(report)

    assert concurrent_snapshot is not None
    assert managed_publishes >= 2
    assert install_module._snapshot(first_target) == concurrent_snapshot

    installed_recovery = tuple(
        first_target.parent.glob(f".{first_target.name}.restore.*")
    )
    assert any(
        install_module._snapshot(path) == installed_before
        for path in installed_recovery
    )

    original_record = backups[first_target]
    assert (
        install_module._snapshot(original_record.backup_path).identity
        == original_record.identity
    )
    authenticated_originals = tuple(
        original_record.backup_path.parent.glob(
            f".{original_record.backup_path.name}.restore-backup.*"
        )
    )
    assert any(
        install_module._snapshot(path).identity == original_record.identity
        for path in authenticated_originals
    )

    staged_originals = tuple(
        first_target.parent.glob(f".{first_target.name}.*.tmp")
    )
    assert any(
        install_module._snapshot(path).content == original.content
        for path in staged_originals
    )


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


def test_runtime_rejection_redacts_before_bounding_diagnostic(tmp_path):
    paths = codex_paths(tmp_path)
    secret = "sk-abcdefghijklmnop1234"

    def run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")
        if command[-1] == "--help":
            return subprocess.CompletedProcess(
                command, 0, "--strict-config\n--listen\n", ""
            )
        return subprocess.CompletedProcess(
            command, 2, "", "x" * 489 + " " + secret
        )

    with pytest.raises(RuntimeError) as raised:
        install_codex(paths, check=True, run=run)

    message = str(raised.value)
    assert "sk-" not in message
    assert "[REDACTED]" in message
