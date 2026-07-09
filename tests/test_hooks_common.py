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
