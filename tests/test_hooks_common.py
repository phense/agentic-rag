import io
import json

from agentic_rag.hooks import common


def test_read_payload_parses_json():
    assert common.read_payload(io.StringIO('{"a": 1}')) == {"a": 1}


def test_read_payload_fails_open_to_empty():
    assert common.read_payload(io.StringIO("not json")) == {}


def test_is_interactive_sources():
    assert common.is_interactive({"source": "startup"}) is True
    assert common.is_interactive({"source": "compact"}) is True
    assert common.is_interactive({}) is True            # tolerant of drift
    assert common.is_interactive({"source": "other"}) is False


def test_is_interactive_kill_switch(monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG_HOOKS_DISABLE", "1")
    assert common.is_interactive({"source": "startup"}) is False


def test_emit_context_shape():
    out = io.StringIO()
    common.emit_context(out, "SessionStart", "hello context")
    data = json.loads(out.getvalue())
    assert data == {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": "hello context"}}


def test_spawn_worker_is_detached_and_fail_open(monkeypatch, tmp_path):
    seen = {}
    class FakePopen:
        def __init__(self, cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
    monkeypatch.setattr(common.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(common, "WORKER_LOG", tmp_path / "w.log")
    common.spawn_worker()
    assert seen["cmd"][-2:] == ["-m", "agentic_rag.worker"]
    assert seen["kw"]["start_new_session"] is True
    def boom(*a, **k):
        raise OSError("no fork")
    monkeypatch.setattr(common.subprocess, "Popen", boom)
    common.spawn_worker()          # must not raise


def test_hook_errors_are_sanitized(monkeypatch, tmp_path):
    secret = "sk-abcdefghijklmnop1234"
    monkeypatch.setattr(common, "HOOK_LOG", tmp_path / "hooks.log")

    common.log_hook_error("pre_compact", f"failed with {secret}")

    logged = (tmp_path / "hooks.log").read_text()
    assert secret not in logged
    assert "[REDACTED]" in logged


def test_client_kind_prefers_explicit_argv():
    assert common.client_kind({"turn_id": "t1"}, ["--client", "claude"]) == "claude"
    assert common.client_kind({}, ["--client=codex"]) == "codex"
    assert common.client_kind({"turn_id": "t1"}, ["--client", "bogus"]) == "codex"


def test_client_kind_uses_turn_id_for_codex_and_defaults_to_claude(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert common.client_kind({"turn_id": "turn-7"}, []) == "codex"
    assert common.client_kind({"turn_id": "  "}, []) == "claude"
    assert common.client_kind({"session_id": "s"}, []) == "claude"


def test_client_kind_reads_sys_argv_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["hook", "--client", "codex"])
    assert common.client_kind({}) == "codex"
