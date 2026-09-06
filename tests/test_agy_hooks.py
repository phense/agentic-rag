import shlex

import pytest

from agentic_rag.integrations.agy import hooks

PY = "/venv with space/bin/python"


def test_owned_hook_covers_three_flat_events_with_timeouts():
    owned = hooks.owned_hook(PY)
    assert owned["enabled"] is True
    assert set(owned) == {"enabled", "SessionStart", "PreInvocation", "Stop"}
    for event, command, timeout in (
            ("SessionStart", "session-start", 10),
            ("PreInvocation", "pre-invocation", 5),
            ("Stop", "stop", 10)):
        handler, = owned[event]
        assert handler["type"] == "command"
        assert handler["command"] == (
            f"{shlex.quote(PY)} -m agentic_rag.hooks.agy {command}")
        assert handler["timeout"] == timeout
        assert "matcher" not in handler


def test_merge_is_idempotent_replaces_stale_and_preserves_foreign():
    original = {
        "lint-checker": {
            "PostToolUse": [{"matcher": "run_command", "hooks": [
                {"type": "command", "command": "./scripts/lint.sh", "timeout": 10},
                {"command": "/old/python -m agentic_rag.hooks.agy stop"},
            ]}],
            "PreInvocation": [
                {"command": "./scripts/reminder.sh"},
                {"command": "/old/python -m agentic_rag.hooks.agy pre-invocation"},
            ],
        },
        "agentic-rag": {"Stop": [{"command": "/old/python -m agentic_rag.hooks.agy stop"}]},
        "custom": {"enabled": False, "extra": "kept"},
    }

    once = hooks.merge_hooks(original, PY)
    twice = hooks.merge_hooks(once, PY)

    assert twice == once
    assert original["lint-checker"]["PreInvocation"][1]["command"].startswith("/old")
    assert once["lint-checker"]["PostToolUse"][0]["hooks"] == [
        {"type": "command", "command": "./scripts/lint.sh", "timeout": 10}]
    assert once["lint-checker"]["PreInvocation"] == [{"command": "./scripts/reminder.sh"}]
    assert once["custom"] == {"enabled": False, "extra": "kept"}
    assert once["agentic-rag"] == hooks.owned_hook(PY)
    assert list(once) == ["lint-checker", "agentic-rag", "custom"]


def test_merge_drops_foreign_groups_left_empty_and_rejects_non_object():
    data = {"probe": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"command": "/x/python -m agentic_rag.hooks.agy pre-invocation"}]}]}}
    merged = hooks.merge_hooks(data, PY)
    assert merged["probe"]["PreToolUse"] == []
    with pytest.raises(ValueError):
        hooks.merge_hooks(["not", "an", "object"], PY)


def test_owned_commands_lists_installed_handlers():
    merged = hooks.merge_hooks({}, PY)
    commands = hooks.owned_commands(merged)
    assert len(commands) == 3
    assert all("agentic_rag.hooks.agy" in c for c in commands)
    assert hooks.owned_commands({}) == ()
