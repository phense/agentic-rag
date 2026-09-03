import json
import os
import re
from pathlib import Path

import pytest

from agentic_rag.integrations.claude import install as claude_install

PY = "/venv/bin/python"


def test_check_mode_reports_without_writing(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "claude-opus-5"}')
    before = settings.read_text()

    report = claude_install.install_claude(
        settings, python=PY, check=True, environ={})

    assert report.check is True
    assert report.changed is True
    assert report.backup is None and report.installed is None
    assert report.managed == (("autoCompactWindow", 500000),)
    assert any("[1m]" in w for w in report.warnings)
    assert settings.read_text() == before
    assert list(tmp_path.iterdir()) == [settings]


def test_install_backs_up_uniquely_writes_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "claude-fable-5-1[1m]", "env": {"X": "1"}}')
    settings.chmod(0o600)

    first = claude_install.install_claude(settings, python=PY, environ={})

    assert first.changed is True
    assert first.backup is not None
    assert re.fullmatch(r"settings\.json\.bak\.[0-9a-f]{32}",
                        first.backup.backup_path.name)
    assert first.backup.backup_path.read_text() == (
        '{"model": "claude-fable-5-1[1m]", "env": {"X": "1"}}')
    assert (first.backup.backup_path.stat().st_mode & 0o777) == 0o600
    assert (settings.stat().st_mode & 0o777) == 0o600
    data = json.loads(settings.read_text())
    assert data["env"] == {"X": "1"}
    assert data["autoCompactWindow"] == 500000
    assert set(data["hooks"]) >= {"PreCompact", "PostCompact", "SessionEnd"}
    assert first.installed is not None
    assert first.warnings == ()

    second = claude_install.install_claude(settings, python=PY, environ={})

    assert second.changed is False
    assert second.backup is None
    assert len([p for p in tmp_path.iterdir() if ".bak." in p.name]) == 1


def test_install_creates_missing_settings_without_backup(tmp_path):
    settings = tmp_path / "nested" / "settings.json"

    report = claude_install.install_claude(settings, python=PY, environ={})

    assert report.changed is True
    assert report.backup is None
    assert json.loads(settings.read_text())["autoCompactWindow"] == 500000


def test_install_rejects_corrupt_json_and_leaves_it(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus", TRAILING GARBAGE')

    with pytest.raises(RuntimeError, match="not valid JSON"):
        claude_install.install_claude(settings, python=PY, environ={})

    assert "TRAILING GARBAGE" in settings.read_text()
    assert list(tmp_path.iterdir()) == [settings]


def test_install_refuses_concurrent_edit_between_snapshot_and_publish(
        tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "m"}')
    original_stage = claude_install._stage_text

    def edit_then_stage(path, text):
        path.write_text('{"model": "edited concurrently"}')
        return original_stage(path, text)
    monkeypatch.setattr(claude_install, "_stage_text", edit_then_stage)

    with pytest.raises(RuntimeError, match="changed concurrently"):
        claude_install.install_claude(settings, python=PY, environ={})

    assert json.loads(settings.read_text()) == {"model": "edited concurrently"}
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".settings")]


def test_restore_puts_backup_back_and_refuses_drift(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "before"}')
    report = claude_install.install_claude(settings, python=PY, environ={})

    restored = claude_install.restore_claude(
        settings, report.backup, report.installed)

    assert restored == (settings,)
    assert settings.read_text() == '{"model": "before"}'

    again = claude_install.install_claude(settings, python=PY, environ={})
    settings.write_text(settings.read_text() + "\n")
    with pytest.raises(RuntimeError, match="changed since installation"):
        claude_install.restore_claude(settings, again.backup, again.installed)


def test_restore_removes_a_file_the_install_created(tmp_path):
    settings = tmp_path / "settings.json"
    report = claude_install.install_claude(settings, python=PY, environ={})

    restored = claude_install.restore_claude(settings, None, report.installed)

    assert restored == (settings,)
    assert not settings.exists()
