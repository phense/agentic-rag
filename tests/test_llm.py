import json
import subprocess
from pathlib import Path

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


def test_command_shape_and_parsed_output(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which",
                        lambda name, path=None: None)   # keep argv[0]
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


def test_passes_utf8_encoding_to_subprocess():
    # On Windows, subprocess text mode decodes with the locale codepage
    # (cp1252), not UTF-8, so the CLI's JSON with German content (ä/ö/ü/ß)
    # would be mangled. Pin UTF-8 everywhere. Decoding stays STRICT (no
    # errors="replace"): silent U+FFFD substitution would corrupt stored
    # content — a decode failure must be loud (see the LLMError test below).
    seen = {}
    def runner(cmd, **kw):
        seen.update(kw)
        return FakeProc(stdout='{"ok": true}')
    llm.run_structured("p", SCHEMA, CFG, runner=runner, env={"PATH": "/bin"})
    assert seen.get("encoding") == "utf-8"
    assert seen.get("errors") in (None, "strict")


def test_invalid_utf8_output_raises_llm_error():
    # strict UTF-8: rather than silently substituting U+FFFD (data corruption),
    # non-UTF-8 CLI output fails loudly as a domain error the worker retries.
    def runner(cmd, **kw):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    with pytest.raises(llm.LLMError, match="UTF-8"):
        llm.run_structured("p", SCHEMA, CFG, runner=runner, env={"PATH": "/bin"})


def test_resolves_binary_via_which(monkeypatch):
    # bare "claude" as argv[0] is unresolvable on Windows (the CLI is
    # claude.cmd); resolve through PATH first (shutil.which honors PATHEXT).
    # Resolution must use the CHILD env's PATH, the same one the subprocess
    # runs with — not the parent process PATH.
    seen = {}
    def fake_which(name, path=None):
        seen["path"] = path
        return f"/opt/{name}"
    monkeypatch.setattr(llm.shutil, "which", fake_which)
    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(stdout='{"ok": true}')
    llm.run_structured("p", SCHEMA, CFG, runner=runner,
                       env={"PATH": "/opt/bin"})
    assert seen["cmd"][0] == "/opt/claude"
    assert seen["path"] == "/opt/bin"


def test_falls_back_to_configured_bin_when_not_on_path(monkeypatch):
    # which() finds nothing → keep the configured name so the existing
    # "binary not found" error path still fires with a helpful message.
    monkeypatch.setattr(llm.shutil, "which", lambda name, path=None: None)
    seen = {}
    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return FakeProc(stdout='{"ok": true}')
    llm.run_structured("p", SCHEMA, CFG, runner=runner, env={"PATH": "/bin"})
    assert seen["cmd"][0] == "claude"


def _codex_cfg(**overrides):
    values = {
        "llm_provider": "codex",
        "llm_bin": "/x/codex",
        "llm_model": "gpt-5.6-luna",
        "llm_reasoning_effort": "high",
    }
    values.update(overrides)
    return Config(**values)


def test_codex_command_is_isolated_ephemeral_read_only_luna_high(tmp_path):
    seen = {}

    def runner(cmd, **kw):
        if cmd[1:3] == ["login", "status"]:
            return FakeProc(stdout="Logged in using ChatGPT")
        seen["cmd"] = cmd
        seen["cwd"] = kw["cwd"]
        workdir = Path(kw["cwd"])
        assert list(workdir.iterdir())  # schema file exists for the child
        schema_path = Path(cmd[cmd.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text()) == SCHEMA
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            '{"ok": true}', encoding="utf-8")
        return FakeProc()

    out = llm.run_structured(
        "mine", SCHEMA, _codex_cfg(), runner=runner,
        env={"PATH": "/bin", "CODEX_HOME": "/auth"})

    assert out == {"ok": True}
    cmd = seen["cmd"]
    assert cmd[:2] == ["/x/codex", "exec"]
    assert cmd[cmd.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="high"' in cmd
    assert "--ephemeral" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in cmd
    assert "--ignore-user-config" in cmd
    assert "--ignore-rules" in cmd
    assert "SYSTEM INSTRUCTIONS" in cmd[-1]
    assert "TASK\nmine" in cmd[-1]
    assert not Path(seen["cwd"]).exists()  # TemporaryDirectory was removed


def test_codex_prompt_combines_system_and_task_without_shell():
    seen = {}

    def runner(cmd, **kw):
        if cmd[1:3] == ["login", "status"]:
            return FakeProc(stdout="Logged in using ChatGPT")
        seen["cmd"] = cmd
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            '{"ok": false}', encoding="utf-8")
        return FakeProc()

    out = llm.run_structured(
        "literal $(touch nope)", SCHEMA, _codex_cfg(),
        system="be terse", runner=runner, env={"PATH": "/bin"})
    assert out == {"ok": False}
    assert seen["cmd"][-1].endswith("TASK\nliteral $(touch nope)")


def test_codex_login_failure_is_provider_unavailable():
    def runner(cmd, **kw):
        return FakeProc(returncode=1, stderr="not logged in")

    with pytest.raises(llm.LLMUnavailableError, match="not logged in"):
        llm.run_structured(
            "p", SCHEMA, _codex_cfg(), runner=runner, env={"PATH": "/bin"})


def test_codex_missing_binary_is_provider_unavailable():
    def runner(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    with pytest.raises(llm.LLMUnavailableError, match="not found"):
        llm.check_provider(
            _codex_cfg(), runner=runner, env={"PATH": "/bin"})


def test_codex_empty_exit_one_is_provider_unavailable():
    calls = 0

    def runner(cmd, **kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeProc(stdout="Logged in using ChatGPT")
        return FakeProc(returncode=1)

    with pytest.raises(llm.LLMUnavailableError, match="exited 1"):
        llm.run_structured(
            "p", SCHEMA, _codex_cfg(), runner=runner, env={"PATH": "/bin"})


@pytest.mark.parametrize("body, match", [
    (None, "did not produce"),
    ("", "empty"),
    ("not json", "not valid JSON"),
    ('["not", "object"]', "not a JSON object"),
])
def test_codex_bad_structured_output_is_job_error(body, match):
    def runner(cmd, **kw):
        if cmd[1:3] == ["login", "status"]:
            return FakeProc(stdout="Logged in using ChatGPT")
        if body is not None:
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
                body, encoding="utf-8")
        return FakeProc()

    with pytest.raises(llm.LLMJobError, match=match):
        llm.run_structured(
            "p", SCHEMA, _codex_cfg(), runner=runner, env={"PATH": "/bin"})


def test_codex_timeout_is_provider_unavailable_and_cleans_tempdir():
    workdirs = []

    def runner(cmd, **kw):
        if cmd[1:3] == ["login", "status"]:
            return FakeProc(stdout="Logged in using ChatGPT")
        workdirs.append(Path(kw["cwd"]))
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    with pytest.raises(llm.LLMUnavailableError, match="timed out"):
        llm.run_structured(
            "p", SCHEMA, _codex_cfg(), runner=runner, env={"PATH": "/bin"})
    assert workdirs and not workdirs[0].exists()


def test_unknown_provider_refuses_before_subprocess():
    def runner(cmd, **kw):
        raise AssertionError("must not run")

    with pytest.raises(ValueError, match="provider"):
        llm.run_structured(
            "p", SCHEMA, _codex_cfg(llm_provider="other"),
            runner=runner, env={"PATH": "/bin"})
