import io
import json
import subprocess
import sys

from agentic_rag.continuity import store
from agentic_rag.hooks import agy, common, prompt_recall
from agentic_rag.integrations.agy.prompt import CHECKPOINT_LINE_PREFIX


def _user(idx, text):
    return {"step_index": idx, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-09-05T23:14:37Z",
            "content": f"<USER_REQUEST>\n{text}\n</USER_REQUEST>"}


def _model(idx, text):
    return {"step_index": idx, "source": "MODEL", "type": "PLANNER_RESPONSE",
            "status": "DONE", "created_at": "2026-09-05T23:14:39Z", "content": text}


def _transcript(tmp_path, *steps):
    path = tmp_path / "transcript_full.jsonl"
    path.write_text("".join(json.dumps(s) + "\n" for s in steps))
    return path


def _payload(tmp_path, transcript, **over):
    payload = {
        "conversationId": "conv-1",
        "workspacePaths": [str(tmp_path)],
        "transcriptPath": str(transcript),
        "artifactDirectoryPath": str(tmp_path / "brain"),
        "modelName": "gemini-3.8-flash-high",
        "invocationNum": 0,
        "initialNumSteps": 1,
    }
    payload.update(over)
    return payload


def _messages(result):
    return [step["ephemeralMessage"] for step in result.get("injectSteps", [])]


def _project(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True,
                   capture_output=True, text=True)


# ------------------------------------------------------------- session-start

def test_session_start_injects_memory_as_ephemeral_message(conn, hook_env, tmp_path):
    transcript = _transcript(tmp_path, _user(0, "hi"))
    conn.execute("INSERT INTO domains(name, description) VALUES ('nature', 'field notes')")
    conn.commit()

    result = agy.run("session-start", _payload(tmp_path, transcript))

    text, = _messages(result)
    assert text.startswith("# agentic-rag memory")
    assert "nature (0 docs)" in text
    assert "hookSpecificOutput" not in json.dumps(result)


def test_session_start_db_down_is_visible_not_silent(hook_env, tmp_path):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    transcript = _transcript(tmp_path, _user(0, "hi"))

    result = agy.run("session-start", _payload(tmp_path, transcript))

    text, = _messages(result)
    assert text.startswith("⚠️ agentic-rag unavailable")
    assert "agy.session_start" in (tmp_path / "hooks.log").read_text()


# ------------------------------------------------------------ pre-invocation

def test_pre_invocation_treats_compact_request_as_pre_compact(
        conn, hook_env, tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(common, "spawn_worker", lambda: spawned.append(True))
    _project(tmp_path)
    transcript = _transcript(tmp_path, _user(0, "remember X"), _model(1, "OK"),
                             _user(2, "/compact"))

    result = agy.run("pre-invocation", _payload(tmp_path, transcript))

    checkpoint = store.latest_for_session(conn, "conv-1")
    assert checkpoint is not None
    assert checkpoint.source == "PreCompact" and checkpoint.trigger == "manual"
    assert checkpoint.cursor == "agy-step-2"
    assert checkpoint.project_root == str(tmp_path.resolve())
    assert checkpoint.compacted_at is None
    text, = _messages(result)
    assert "Version: 1.0" in text
    assert text.rstrip().endswith(f"{CHECKPOINT_LINE_PREFIX}{checkpoint.id}")
    assert conn.execute(
        "SELECT count(*) AS n FROM mining_queue WHERE kind = 'checkpoint_enrich'"
    ).fetchone()["n"] == 1
    assert spawned == [True]

    replay = agy.run("pre-invocation", _payload(tmp_path, transcript))
    assert _messages(replay) == [text]
    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints").fetchone()["n"] == 1


def test_pre_invocation_later_invocations_and_plain_turns_are_silent(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "spawn_worker", lambda: None)
    transcript = _transcript(tmp_path, _user(0, "please refactor the parser"))

    assert agy.run("pre-invocation", _payload(tmp_path, transcript, invocationNum=2)) == {}
    assert agy.run("pre-invocation", _payload(tmp_path, transcript)) == {}
    assert store.latest_for_session(conn, "conv-1") is None
    assert agy.run("pre-invocation", _payload(
        tmp_path, transcript, transcriptPath=str(tmp_path / "missing.jsonl"))) == {}


def test_pre_invocation_recalls_stored_error_signals(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "spawn_worker", lambda: None)
    monkeypatch.setattr(prompt_recall, "recall_context",
                        lambda prompt, project: f"RECALL for {prompt!r} in {project}")
    transcript = _transcript(tmp_path, _user(0, "Traceback (most recent call last)\nKeyError: 'x'"))

    result = agy.run("pre-invocation", _payload(tmp_path, transcript))

    text, = _messages(result)
    assert text.startswith("RECALL for ") and "Traceback" in text
    assert text.endswith(str(tmp_path))


def test_pre_invocation_auto_compaction_marker_records_boundary_and_restores(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "spawn_worker", lambda: None)
    marker = {"step_index": 5, "source": "SYSTEM", "type": "CHECKPOINT", "status": "DONE",
              "content": "<CONTEXT_SUMMARY>\nGoal: ship the parser.\n</CONTEXT_SUMMARY>"}
    transcript = _transcript(tmp_path, _user(4, "go on"), marker, _user(6, "continue"))

    result = agy.run("pre-invocation", _payload(tmp_path, transcript))

    checkpoint = store.latest_for_session(conn, "conv-1")
    assert checkpoint.cursor == "agy-step-5" and checkpoint.trigger == "auto"
    assert checkpoint.compacted_at is not None
    assert checkpoint.handoff == "Goal: ship the parser."
    text, = _messages(result)
    assert text.startswith("# agentic-rag memory")
    assert "Continuation checkpoint" in text
    assert "Goal: ship the parser." in text

    replay = agy.run("pre-invocation", _payload(tmp_path, transcript))
    assert replay == {}


# ---------------------------------------------------------------------- stop

def test_stop_attaches_compact_summary_and_enqueues_mining(
        conn, hook_env, tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(common, "spawn_worker", lambda: spawned.append(True))
    transcript = _transcript(tmp_path, _user(0, "remember X"), _model(1, "OK"),
                             _user(2, "/compact"))
    agy.run("pre-invocation", _payload(tmp_path, transcript))
    with transcript.open("a") as fh:
        fh.write(json.dumps(_model(3, "### Conversation Summary\n- X noted")) + "\n")

    result = agy.run("stop", _payload(tmp_path, transcript, terminationReason="NO_TOOL_CALL",
                                      fullyIdle=True, executionNum=0))

    assert result == {}
    checkpoint = store.latest_for_session(conn, "conv-1")
    assert checkpoint.compacted_at is not None
    assert checkpoint.handoff == "### Conversation Summary\n- X noted"
    row = conn.execute("SELECT * FROM mining_queue WHERE kind = 'mine'").fetchone()
    assert row["session_id"] == "conv-1"
    assert row["payload"] == {"project": str(tmp_path)}
    assert row["transcript_path"] == str(transcript)
    assert len(spawned) >= 2


def test_stop_without_compaction_only_enqueues(conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "spawn_worker", lambda: None)
    transcript = _transcript(tmp_path, _user(0, "hello"), _model(1, "hi"))

    assert agy.run("stop", _payload(tmp_path, transcript)) == {}

    assert conn.execute("SELECT count(*) AS n FROM mining_queue").fetchone()["n"] == 1
    assert store.latest_for_session(conn, "conv-1") is None


# ------------------------------------------------------------------ contract

def test_unknown_event_kill_switch_and_garbage_stdin_exit_zero(
        hook_env, monkeypatch, capsys):
    assert agy.run("nonsense", {"conversationId": "c"}) == {}
    monkeypatch.setenv("AGENTIC_RAG_HOOKS_DISABLE", "1")
    assert agy.run("session-start", {"conversationId": "c"}) == {}
    monkeypatch.delenv("AGENTIC_RAG_HOOKS_DISABLE")
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert agy.main(["stop"]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_hook_failure_is_logged_and_never_raises(hook_env, tmp_path, monkeypatch):
    def boom(payload):
        raise RuntimeError("token sk-abcdefghijklmnop1234 leaked")
    monkeypatch.setitem(agy._HANDLERS, "stop", boom)

    assert agy.run("stop", {"conversationId": "c"}) == {}
    log = (tmp_path / "hooks.log").read_text()
    assert "[agy.stop]" in log and "sk-abcdefghijklmnop1234" not in log
