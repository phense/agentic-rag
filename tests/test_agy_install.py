import json
import re

import pytest

from agentic_rag.integrations.agy import install as agy_install

PY = "/venv/bin/python"


def test_check_mode_reports_without_writing(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text('{"lint": {"Stop": [{"command": "x"}]}}')
    before = hooks.read_text()

    report = agy_install.install_agy(hooks, python=PY, check=True)

    assert report.check is True and report.changed is True
    assert report.backup is None and report.installed is None
    assert len(report.commands) == 3
    assert any("has not run" in w for w in report.warnings)
    assert hooks.read_text() == before
    assert list(tmp_path.iterdir()) == [hooks]


def test_install_backs_up_uniquely_writes_and_is_idempotent(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text('{"lint": {"Stop": [{"command": "x"}]}}')
    hooks.chmod(0o600)

    first = agy_install.install_agy(hooks, python=PY)

    assert first.changed is True and first.backup is not None
    assert re.fullmatch(r"hooks\.json\.bak\.[0-9a-f]{32}", first.backup.backup_path.name)
    assert first.backup.backup_path.read_text() == '{"lint": {"Stop": [{"command": "x"}]}}'
    assert (hooks.stat().st_mode & 0o777) == 0o600
    data = json.loads(hooks.read_text())
    assert data["lint"] == {"Stop": [{"command": "x"}]}
    assert set(data["agentic-rag"]) == {"enabled", "SessionStart", "PreInvocation", "Stop"}
    assert first.installed is not None

    second = agy_install.install_agy(hooks, python=PY)

    assert second.changed is False and second.backup is None
    assert len([p for p in tmp_path.iterdir() if ".bak." in p.name]) == 1


def test_install_creates_missing_file_without_backup(tmp_path):
    hooks = tmp_path / ".gemini" / "config" / "hooks.json"

    report = agy_install.install_agy(hooks, python=PY)

    assert report.changed is True and report.backup is None
    assert "agentic-rag" in json.loads(hooks.read_text())
    assert agy_install.hooks_path_for_home(tmp_path) == hooks


def test_install_rejects_corrupt_json_and_leaves_it(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text('{"lint": TRAILING GARBAGE')

    with pytest.raises(RuntimeError, match="not valid JSON"):
        agy_install.install_agy(hooks, python=PY)

    assert "TRAILING GARBAGE" in hooks.read_text()
    assert list(tmp_path.iterdir()) == [hooks]


def test_restore_puts_backup_back_and_refuses_drift(tmp_path):
    hooks = tmp_path / "hooks.json"
    hooks.write_text('{"lint": {"Stop": [{"command": "x"}]}}')
    report = agy_install.install_agy(hooks, python=PY)

    restored = agy_install.restore_agy(hooks, report.backup, report.installed)

    assert restored == (hooks,)
    assert json.loads(hooks.read_text()) == {"lint": {"Stop": [{"command": "x"}]}}

    again = agy_install.install_agy(hooks, python=PY)
    hooks.write_text('{"edited": true}')
    with pytest.raises(RuntimeError, match="changed since installation"):
        agy_install.restore_agy(hooks, again.backup, again.installed)


def test_restore_removes_a_created_file(tmp_path):
    hooks = tmp_path / "hooks.json"
    report = agy_install.install_agy(hooks, python=PY)

    assert agy_install.restore_agy(hooks, None, report.installed) == (hooks,)
    assert not hooks.exists()
