"""Tests for native Antigravity plugin packaging, lifecycle dispatch, and MCP safety."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from agentic_rag import cli, install, mcp_server
from agentic_rag.config import Config
from agentic_rag.hooks import agy, common
from agentic_rag.plugins import lifecycle, mcp as plugin_mcp, package

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_antigravity_plugin_package_lifecycle_and_dual_mcp(tmp_path):
    target = tmp_path / "plugins" / "agentic-rag"
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("")

    plan = package.manage("antigravity", target, python=sys.executable, config=cfg_path)
    assert plan["preview"] is True
    assert not target.exists()
    assert plan["files"] == [
        ".antigravity-plugin/plugin.json",
        "hooks.json",
        "mcp_config.json",
    ]

    package.manage("antigravity", target, python=sys.executable, config=cfg_path, apply=True)
    manifest = json.loads((target / ".antigravity-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "agentic-rag"
    assert manifest["$schema"] == "https://antigravity.google/schemas/v1/plugin.json"

    mcp_doc = json.loads((target / "mcp_config.json").read_text())
    servers = mcp_doc["mcpServers"]
    assert set(servers) == {"agentic-rag", "agentic-rag-ro"}
    assert servers["agentic-rag"]["args"] == ["-m", "agentic_rag.plugins.mcp"]
    assert servers["agentic-rag"]["env"] == {"AGENTIC_RAG_CONFIG": str(cfg_path)}
    assert servers["agentic-rag-ro"]["args"] == ["-m", "agentic_rag.plugins.mcp", "--read-only"]
    assert servers["agentic-rag-ro"]["env"] == {
        "AGENTIC_RAG_CONFIG": str(cfg_path),
        "RAG_READONLY": "1",
    }

    hooks_doc = json.loads((target / "hooks.json").read_text())
    owned = hooks_doc["agentic-rag"]
    assert owned["enabled"] is True
    assert set(owned) == {"enabled", "SessionStart", "PreInvocation", "Stop"}
    expected_cfg = f"AGENTIC_RAG_CONFIG={shlex.quote(str(cfg_path))}"
    for event, timeout in (("SessionStart", 10), ("PreInvocation", 5), ("Stop", 30)):
        handler, = owned[event]
        assert handler["type"] == "command"
        assert handler["timeout"] == timeout
        assert f"--host antigravity --event {event}" in handler["command"]
        assert expected_cfg in handler["command"]

    foreign = target / "notes.txt"
    foreign.write_text("keep")
    assert package.manage("antigravity", target, action="doctor")["status"] == "ok"
    package.manage("antigravity", target, action="update", apply=True)
    assert foreign.read_text() == "keep"

    package.manage("antigravity", target, action="uninstall", apply=True)
    assert foreign.read_text() == "keep"
    assert not (target / "hooks.json").exists()
    assert not (target / "mcp_config.json").exists()
    assert (target / package.RECORD).exists()


def test_antigravity_readonly_plugin_omits_write_mcp_and_hooks(tmp_path):
    target = tmp_path / "agentic-rag-ro"
    package.manage("antigravity", target, python=sys.executable, read_only=True, apply=True)

    mcp_doc = json.loads((target / "mcp_config.json").read_text())
    assert list(mcp_doc["mcpServers"]) == ["agentic-rag-ro"]
    assert mcp_doc["mcpServers"]["agentic-rag-ro"]["env"]["RAG_READONLY"] == "1"
    assert json.loads((target / "hooks.json").read_text()) == {}


def test_antigravity_lifecycle_dispatch_and_subagent_suppression(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agy, "run", lambda event, payload: calls.append((event, payload)) or {"injectSteps": []}
    )
    out = io.StringIO()
    lifecycle.dispatch("antigravity", "SessionStart", {"conversationId": "c1", "cwd": "/tmp/x"}, out)
    assert json.loads(out.getvalue()) == {"injectSteps": []}
    assert calls == [("session-start", {"conversationId": "c1", "cwd": "/tmp/x"})]

    for blocked in (
        {"is_sidechain": True},
        {"isSidechain": True},
        {"is_subagent": True},
        {"isSubagent": True},
        {"parent_session_id": "p1"},
        {"parentSessionId": "p1"},
        {"parentConversationId": "c0"},
        {"subagent_id": "s1"},
        {"subagentId": "s1"},
        {"fork": True},
        {"isFork": True},
        {"agent_type": "subagent"},
        {"agentType": "subagent"},
        {"agent_type": "maintenance"},
        {"agentType": "maintenance"},
        {"stop_hook_active": True},
        {"stopHookActive": True},
    ):
        buf = io.StringIO()
        lifecycle.dispatch("antigravity", "Stop", blocked, buf)
        assert json.loads(buf.getvalue()) == {}
    assert len(calls) == 1

    with pytest.raises(ValueError, match="unsupported native event"):
        lifecycle.dispatch("antigravity", "PreCompact", {"conversationId": "c1"}, io.StringIO())


def test_antigravity_lifecycle_main_returns_valid_json_on_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["lifecycle", "--host", "antigravity", "--event", "Stop"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"not-json")))
    monkeypatch.setattr(common, "log_hook_error", lambda *a: None)
    assert lifecycle.main() == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_agy_hook_uses_cwd_fallback_and_suppresses_subagents(monkeypatch):
    assert agy._cwd({"cwd": "/repo/project"}) == "/repo/project"
    assert agy._cwd({"workspacePaths": ["/ws/a"], "cwd": "/repo/project"}) == "/ws/a"
    assert agy.inject("hello") == {"injectSteps": [{"systemMessage": {"systemMessage": "hello"}}]}

    monkeypatch.setitem(agy._HANDLERS, "stop", lambda p: (_ for _ in ()).throw(AssertionError("called")))
    for blocked in (
        {"conversationId": "c1", "subagent_id": "child"},
        {"conversationId": "c1", "subagentId": "child"},
        {"conversationId": "c1", "parentConversationId": "parent"},
        {"conversationId": "c1", "isSubagent": True},
        {"conversationId": "c1", "agentType": "subagent"},
        {"conversationId": "c1", "stopHookActive": True},
    ):
        assert agy.run("stop", blocked) == {}


def test_agy_install_supports_custom_config_dir_rollback_and_overlap_warnings(tmp_path):
    provider_root = tmp_path / "provider"
    (provider_root / "antigravity-acp").mkdir(parents=True)
    config_dir = provider_root / "config"
    plugin_hooks = config_dir / "plugins" / "agentic-rag" / "hooks.json"
    plugin_hooks.parent.mkdir(parents=True)

    # Empty hooks.json from a --read-only plugin does not warn about duplicate execution.
    plugin_hooks.write_text("{}\n")
    rep_ro = install.install(Config(), agy=True, agy_config_dir=config_dir, check=True)
    assert not any("duplicate hook execution" in w for w in rep_ro.agy_report.warnings)

    # Non-empty native plugin hooks warn about duplicate execution.
    plugin_hooks.write_text('{"agentic-rag": {"enabled": true}}\n')
    rep = install.install(Config(), agy=True, agy_config_dir=config_dir, check=True)
    assert rep.agy_report is not None
    assert rep.agy_report.hooks_path == config_dir / "hooks.json"
    assert not any("has not run" in w for w in rep.agy_report.warnings)
    assert any("duplicate hook execution" in w for w in rep.agy_report.warnings)

    # Full write, rollback record, and restore round-trip on custom config dir.
    hooks_file = config_dir / "hooks.json"
    hooks_file.write_text('{"foreign": {"Stop": [{"command": "true"}]}}\n')
    written = install.install(
        Config(), agy=True, agy_config_dir=config_dir, state_dir=tmp_path / "state"
    )
    assert written.agy_report is not None and written.agy_report.changed
    assert written.rollback_path is not None
    assert "agentic-rag" in json.loads(hooks_file.read_text())

    restored = install.install(Config(), agy=True, restore_path=written.rollback_path)
    assert restored.restored_paths == (hooks_file,)
    assert json.loads(hooks_file.read_text()) == {"foreign": {"Stop": [{"command": "true"}]}}

    with pytest.raises(ValueError, match="mutually exclusive"):
        install.install(Config(), agy=True, agy_home=tmp_path, agy_config_dir=config_dir)


def test_cli_agy_config_dir_validation(capsys):
    with pytest.raises(SystemExit):
        cli.main(["install", "--agy-config-dir", "/tmp/x"])
    with pytest.raises(SystemExit):
        cli.main(["install", "--agy", "--agy-home", "/tmp/h", "--agy-config-dir", "/tmp/x"])
    with pytest.raises(SystemExit):
        cli.main(["install", "--agy", "--agy-config-dir", "/tmp/x", "--restore", "/tmp/rec.json"])


def test_plugin_mcp_readonly_enforces_flag_and_env_boundary(monkeypatch):
    read_names = {fn.__name__ for fn in mcp_server.READ_TOOLS}
    write_names = {fn.__name__ for fn in mcp_server.WRITE_TOOLS}

    monkeypatch.delenv("RAG_READONLY", raising=False)
    ro_server = plugin_mcp.build(read_only=True)
    ro_tools = set(ro_server._tool_manager._tools)
    assert read_names <= ro_tools
    assert not (write_names & ro_tools)
    assert "memory_request_cancel" not in ro_tools

    # RAG_READONLY=1 in environment must also enforce read-only even when read_only=False.
    monkeypatch.setenv("RAG_READONLY", "1")
    env_ro_server = plugin_mcp.build(read_only=False)
    env_ro_tools = set(env_ro_server._tool_manager._tools)
    assert read_names <= env_ro_tools
    assert not (write_names & env_ro_tools)
    assert "memory_request_cancel" not in env_ro_tools

    # Verify main() sets RAG_READONLY=1 when --read-only is passed.
    seen = {}

    class DummyServer:
        def run(self, *, transport):
            seen["transport"] = transport
            seen["rag_readonly"] = os.environ.get("RAG_READONLY")

    prev = os.environ.get("RAG_READONLY")
    monkeypatch.delenv("RAG_READONLY", raising=False)
    monkeypatch.setattr(sys, "argv", ["mcp", "--read-only"])
    monkeypatch.setattr(plugin_mcp, "build", lambda ro: seen.update(arg_ro=ro) or DummyServer())
    try:
        plugin_mcp.main()
    finally:
        if prev is None:
            os.environ.pop("RAG_READONLY", None)
        else:
            os.environ["RAG_READONLY"] = prev
    assert seen == {"arg_ro": True, "transport": "stdio", "rag_readonly": "1"}


@pytest.mark.skipif(shutil.which("agy") is None, reason="agy CLI not installed")
def test_agy_cli_validates_static_template_and_generated_plugins(tmp_path):
    static_dir = REPO_ROOT / "plugins" / "antigravity"
    res_static = subprocess.run(
        ["agy", "plugin", "validate", "--strict", "--json", str(static_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_static.returncode == 0, res_static.stdout + res_static.stderr
    static_report = json.loads(res_static.stdout)
    assert static_report["components"]["hooks"] == 1
    assert static_report["components"]["mcpServers"] == 2

    home = tmp_path / "home"
    plugin_dir = home / ".gemini" / "config" / "plugins" / "agentic-rag"
    package.manage("antigravity", plugin_dir, python=sys.executable, apply=True)

    res_gen = subprocess.run(
        ["agy", "plugin", "validate", "--strict", "--json", str(plugin_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_gen.returncode == 0, res_gen.stdout + res_gen.stderr

    ro_dir = tmp_path / "agentic-rag-ro"
    package.manage("antigravity", ro_dir, python=sys.executable, read_only=True, apply=True)
    res_ro = subprocess.run(
        ["agy", "plugin", "validate", "--strict", "--json", str(ro_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_ro.returncode == 0, res_ro.stdout + res_ro.stderr
    ro_report = json.loads(res_ro.stdout)
    assert ro_report["components"]["hooks"] == 0
    assert ro_report["components"]["mcpServers"] == 1

    env = {**os.environ, "HOME": str(home)}
    res_list = subprocess.run(
        ["agy", "plugin", "list", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_list.returncode == 0, res_list.stdout + res_list.stderr
    listed = json.loads(res_list.stdout)
    assert len(listed) == 1
    assert listed[0]["name"] == "agentic-rag"
    assert set(listed[0]["mcpServers"]) == {"agentic-rag", "agentic-rag-ro"}
    assert listed[0]["hooks"] == ["agentic-rag"]
