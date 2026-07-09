import json
import subprocess

import pytest

from agentic_rag import llm
from agentic_rag.config import Config

CFG = Config()
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"]}


class FakeProc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def test_api_key_passes_through_to_child():
    # auth-agnostic: the claude CLI uses whatever it is logged into. An
    # ANTHROPIC_API_KEY in the source env MUST reach the child unchanged so the
    # CLI can use it (the RAG neither imposes nor refuses metered auth).
    seen = {}
    def runner(cmd, **kw):
        seen["env"] = kw["env"]
        return FakeProc(stdout='{"ok": true}')
    out = llm.run_structured("p", SCHEMA, CFG, runner=runner,
                             env={"ANTHROPIC_API_KEY": "sk-x", "PATH": "/bin"})
    assert out == {"ok": True}
    assert seen["env"]["ANTHROPIC_API_KEY"] == "sk-x"


def test_session_markers_are_stripped():
    seen = {}
    def runner(cmd, **kw):
        seen["env"] = kw["env"]
        return FakeProc(stdout='{"ok": true}')
    llm.run_structured("p", SCHEMA, CFG, runner=runner,
                       env={"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "x",
                            "PATH": "/bin"})
    assert "CLAUDECODE" not in seen["env"]
    assert "CLAUDE_CODE_SESSION_ID" not in seen["env"]


def test_disables_agentic_rag_hooks_in_child():
    # ROOT-CAUSE guard for the session-digest cascade bug: a system-spawned
    # `claude -p` inherits ~/.claude/settings.json, so on completion the CHILD
    # fires its OWN Stop hook, which enqueues the child's transcript for mining
    # -> mining that spawns another `claude -p` -> self-amplifying loop (nested
    # "SESSION DIGEST" headers, truncated at max_chars). The child env MUST set
    # the kill switch every agentic-rag hook honors (common.is_interactive).
    seen = {}
    def runner(cmd, **kw):
        seen["env"] = kw["env"]
        return FakeProc(stdout='{"ok": true}')
    # kill switch set even when the SOURCE env has no such key
    llm.run_structured("p", SCHEMA, CFG, runner=runner, env={"PATH": "/bin"})
    assert seen["env"].get("AGENTIC_RAG_HOOKS_DISABLE") == "1"


def test_disables_hooks_on_production_env_none_path(monkeypatch):
    # the production path: env=None falls back to os.environ; the kill switch
    # must still be injected into the child even if the parent lacks it.
    monkeypatch.delenv("AGENTIC_RAG_HOOKS_DISABLE", raising=False)
    seen = {}
    def runner(cmd, **kw):
        seen["env"] = kw["env"]
        return FakeProc(stdout='{"ok": true}')
    llm.run_structured("p", SCHEMA, CFG, runner=runner)
    assert seen["env"].get("AGENTIC_RAG_HOOKS_DISABLE") == "1"


def test_command_shape_and_parsed_output():
    seen = {}
    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(stdout='{"ok": false}')
    out = llm.run_structured("mine this", SCHEMA, CFG, runner=runner,
                             system="be terse", env={"PATH": "/bin"})
    assert out == {"ok": False}
    cmd = seen["cmd"]
    assert cmd[0] == "claude"
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert cmd[cmd.index("-p") + 1] == "mine this"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert cmd[cmd.index("--system-prompt") + 1] == "be terse"


def test_nonzero_exit_raises_llm_error():
    def runner(cmd, **kw):
        return FakeProc(returncode=1, stderr="usage limit reached")
    with pytest.raises(llm.LLMError, match="usage limit"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={})


def test_timeout_raises_llm_error():
    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    with pytest.raises(llm.LLMError, match="timed out"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={})


def test_missing_binary_raises_llm_error():
    def runner(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    with pytest.raises(llm.LLMError, match="not found"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={})


def test_non_json_stdout_raises_llm_error():
    def runner(cmd, **kw):
        return FakeProc(stdout="I refuse to answer in JSON")
    with pytest.raises(llm.LLMError, match="not valid JSON"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={})


def test_non_object_json_raises_llm_error():
    def runner(cmd, **kw):
        return FakeProc(stdout='["a", "list"]')
    with pytest.raises(llm.LLMError, match="not a JSON object"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={})
