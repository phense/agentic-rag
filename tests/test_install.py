import json
import sys
from pathlib import Path

import pytest

from agentic_rag import install
from agentic_rag.config import Config

PY = "/venv/bin/python"


def test_hook_entries_reference_all_three_hooks():
    entries = install.hook_entries(PY)
    assert set(entries) == {"SessionStart", "UserPromptSubmit", "Stop"}
    ss = entries["SessionStart"][0]
    assert ss["matcher"] == "startup|resume|clear|compact"
    assert ss["hooks"][0]["command"] == (
        f"{PY} -m agentic_rag.hooks.session_start")
    assert all(e[0]["hooks"][0]["command"].startswith(PY)
               for e in entries.values())


def test_merge_hooks_into_empty_settings():
    out = install.merge_hooks({}, PY)
    assert set(out["hooks"]) == {"SessionStart", "UserPromptSubmit", "Stop"}


def test_merge_hooks_is_idempotent_and_replaces_stale_paths():
    once = install.merge_hooks({}, "/old/python")
    twice = install.merge_hooks(once, PY)
    ss = twice["hooks"]["SessionStart"]
    assert len(ss) == 1                        # replaced, not duplicated
    assert ss[0]["hooks"][0]["command"].startswith(PY)


def test_merge_hooks_preserves_foreign_hooks_and_keys():
    settings = {
        "model": "opus",
        "hooks": {
            "SessionStart": [{"hooks": [
                {"type": "command", "command": "other-tool --init"}]}],
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "guard.sh"}]}],
        },
    }
    out = install.merge_hooks(settings, PY)
    assert out["model"] == "opus"
    ss_cmds = [h["command"] for e in out["hooks"]["SessionStart"]
               for h in e["hooks"]]
    assert "other-tool --init" in ss_cmds
    assert any("agentic_rag.hooks.session_start" in c for c in ss_cmds)
    assert out["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "guard.sh"


def test_register_mcp_registers_rw_and_readonly(monkeypatch):
    calls = []
    class P:
        returncode, stderr = 0, ""
    def run(cmd, **kw):
        calls.append(cmd)
        return P()
    install.register_mcp(PY, run=run)
    removes = [c for c in calls if c[:3] == ["claude", "mcp", "remove"]]
    adds = {c[5]: json.loads(c[6])
            for c in calls if c[:3] == ["claude", "mcp", "add-json"]}
    assert len(removes) == 2
    assert adds["agentic-rag"] == {
        "type": "stdio", "command": PY,
        "args": ["-m", "agentic_rag.mcp_server"]}
    # the spec-§5 subagent server: same binary, readonly env
    assert adds["agentic-rag-ro"] == {
        "type": "stdio", "command": PY,
        "args": ["-m", "agentic_rag.mcp_server"],
        "env": {"RAG_READONLY": "1"}}


def test_register_mcp_raises_on_add_failure():
    import pytest
    class P:
        def __init__(self, rc):
            self.returncode, self.stderr = rc, "boom"
    def run(cmd, **kw):
        return P(0 if cmd[2] == "remove" else 1)
    with pytest.raises(RuntimeError, match="boom"):
        install.register_mcp(PY, run=run)


def test_install_aborts_on_corrupt_settings(tmp_path, monkeypatch):
    import pytest
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus", TRAILING GARBAGE')
    monkeypatch.setattr(install, "register_mcp", lambda python, run: None)
    with pytest.raises(RuntimeError, match="not valid JSON"):
        install.install(Config(), settings_path=settings,
                        with_launchd=False)
    # the corrupt original must survive untouched
    assert "TRAILING GARBAGE" in settings.read_text()


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_install_writes_settings_and_reresolves_launchd(tmp_path,
                                                        monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"model": "opus"}')
    monkeypatch.setattr(install, "register_mcp",
                        lambda python, run: None)
    seen = {}
    def fake_launchd(cfg, rag_bin):
        seen["rag_bin"] = rag_bin
        return tmp_path / "plist"
    monkeypatch.setattr(install.backup, "install_launchd", fake_launchd)
    rep = install.install(Config(), settings_path=settings)
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert "SessionStart" in data["hooks"]
    assert (settings.with_suffix(".json.bak")).exists()
    # the launchd gate: rag_bin re-resolved from the CURRENT interpreter
    assert str(seen["rag_bin"]).endswith("/rag")
    assert rep.plist_path == tmp_path / "plist"


def test_install_skips_launchd_off_darwin(tmp_path, monkeypatch):
    monkeypatch.setattr(install.sys, "platform", "linux")
    monkeypatch.setattr(install, "register_mcp", lambda python, run: None)
    called = False
    def fake_launchd(cfg, rag_bin):
        nonlocal called
        called = True
        return tmp_path / "plist"
    monkeypatch.setattr(install.backup, "install_launchd", fake_launchd)
    settings = tmp_path / "settings.json"
    rep = install.install(Config(), settings_path=settings, with_launchd=True)
    assert rep.plist_path is None
    assert called is False
