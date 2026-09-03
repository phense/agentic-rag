import io
import json

from agentic_rag.continuity import store
from agentic_rag.hooks import pre_compact


def _payload(tmp_path, **over):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({
        "uuid": "event-9",
        "message": {"role": "user", "content": "keep working"},
    }) + "\n")
    payload = {
        "session_id": "session-1",
        "turn_id": "turn-7",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    }
    payload.update(over)
    return payload


def _queue_count(conn, kind):
    return conn.execute(
        "SELECT count(*) AS n FROM mining_queue WHERE kind = %s", (kind,)
    ).fetchone()["n"]


def test_pre_compact_snapshots_and_enqueues(
        conn, hook_env, tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(
        pre_compact.common, "spawn_worker", lambda: spawned.append(True))
    payload = _payload(tmp_path)

    pre_compact.run(payload)

    checkpoint = store.latest_for_session(conn, payload["session_id"])
    assert checkpoint is not None
    assert checkpoint.trigger == "auto"
    assert checkpoint.cursor == "event-9"
    assert _queue_count(conn, "checkpoint_enrich") == 1
    assert spawned == [True]


def test_pre_compact_replay_is_idempotent(conn, hook_env, tmp_path,
                                          monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path)

    pre_compact.run(payload)
    pre_compact.run(payload)

    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints"
    ).fetchone()["n"] == 1
    assert _queue_count(conn, "checkpoint_enrich") == 1


def test_pre_compact_missing_transcript_keeps_snapshot_without_enqueue(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path, transcript_path=str(tmp_path / "missing.jsonl"))

    pre_compact.run(payload)

    assert store.latest_for_session(conn, payload["session_id"]) is not None
    assert _queue_count(conn, "checkpoint_enrich") == 0


def test_pre_compact_db_down_exits_zero(hook_env, monkeypatch, capsys):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "session-1",
        "turn_id": "turn-7",
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    })))

    assert pre_compact.main() == 0
    assert capsys.readouterr().out == ""


def test_pre_compact_rejects_invalid_trigger_without_stdout(
        conn, hook_env, tmp_path, capsys):
    pre_compact.run(_payload(tmp_path, trigger="later"))

    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints"
    ).fetchone()["n"] == 0
    assert capsys.readouterr().out == ""
