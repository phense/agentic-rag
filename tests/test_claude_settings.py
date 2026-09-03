import shlex

import pytest

from agentic_rag.integrations.claude import settings

PY = "/venv with space/bin/python"


def test_owned_entries_cover_six_events_with_matchers_and_timeouts():
    entries = settings.owned_hook_entries(PY)

    assert set(entries) == {
        "SessionStart", "UserPromptSubmit", "Stop",
        "PreCompact", "PostCompact", "SessionEnd",
    }
    assert entries["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    assert entries["PreCompact"][0]["matcher"] == "manual|auto"
    assert entries["PostCompact"][0]["matcher"] == "manual|auto"
    assert "matcher" not in entries["SessionEnd"][0]
    timeouts = {event: entry[0]["hooks"][0]["timeout"]
                for event, entry in entries.items()}
    assert timeouts == {"SessionStart": 10, "UserPromptSubmit": 5, "Stop": 10,
                        "PreCompact": 3, "PostCompact": 3, "SessionEnd": 1}
    command = entries["PreCompact"][0]["hooks"][0]["command"]
    assert command == f"{shlex.quote(PY)} -m agentic_rag.hooks.pre_compact"
    assert all("additionalContextLimit" not in e[0]["hooks"][0]
               for e in entries.values())


def test_merge_settings_is_idempotent_replaces_stale_and_preserves_foreign():
    original = {
        "model": "claude-fable-5-1[1m]",
        "permissions": {"defaultMode": "auto"},
        "hooks": {
            "SessionStart": [
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": "bash herdr.sh session",
                     "timeout": 10}]},
                {"matcher": "startup|resume|clear|compact", "hooks": [
                    {"type": "command",
                     "command": "/old/python -m agentic_rag.hooks.session_start",
                     "timeout": 10}]},
            ],
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "guard.sh"}]}],
        },
    }

    once = settings.merge_settings(original, PY)
    twice = settings.merge_settings(once, PY)

    assert twice == once
    assert original["hooks"]["SessionStart"][1]["hooks"][0]["command"].startswith(
        "/old/python")                       # input untouched
    assert once["model"] == "claude-fable-5-1[1m]"
    assert once["permissions"] == {"defaultMode": "auto"}
    assert once["autoCompactWindow"] == 500000
    ss = once["hooks"]["SessionStart"]
    assert ss[0]["hooks"][0]["command"] == "bash herdr.sh session"
    owned = [h["command"] for e in ss for h in e["hooks"]
             if "agentic_rag.hooks." in h["command"]]
    assert len(owned) == 1 and owned[0].startswith(shlex.quote(PY))
    assert once["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    assert set(once["hooks"]) >= {"PreCompact", "PostCompact", "SessionEnd"}


def test_merge_settings_rejects_non_object_hooks():
    with pytest.raises(ValueError, match="hooks"):
        settings.merge_settings({"hooks": []}, PY)
    with pytest.raises(ValueError, match="SessionStart"):
        settings.merge_settings({"hooks": {"SessionStart": {}}}, PY)


def test_policy_warnings_cover_model_toggle_and_overrides():
    data = {"model": "claude-opus-5", "autoCompactEnabled": False,
            "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"}}
    environ = {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "40"}

    warnings = settings.policy_warnings(data, environ)

    assert any("[1m]" in w and "claude-opus-5" in w for w in warnings)
    assert any("autoCompactEnabled" in w for w in warnings)
    assert any("settings env CLAUDE_CODE_AUTO_COMPACT_WINDOW" in w for w in warnings)
    assert any("environment variable CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" in w
               for w in warnings)
    assert settings.policy_warnings(
        {"model": "claude-fable-5-1[1m]"}, {}) == ()
    assert any("no model" in w for w in settings.policy_warnings({}, {}))


def test_managed_settings_is_the_single_policy_source():
    assert settings.managed_settings() == (("autoCompactWindow", 500000),)
