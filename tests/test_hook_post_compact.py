import io
import json

from agentic_rag.continuity import store
from agentic_rag.continuity.model import CheckpointSnapshot
from agentic_rag.hooks import post_compact


def _seed(conn, *, session_id="session-1", cursor="event-9"):
    return store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id=session_id,
        turn_id="turn-7",
        cursor=cursor,
        source="PreCompact",
        trigger="auto",
        cwd="/work/project",
        project_root="/work/project",
    ))


def _payload(**over):
    payload = {
        "session_id": "session-1",
        "turn_id": "turn-7",
        "hook_event_name": "PostCompact",
        "trigger": "auto",
    }
    payload.update(over)
    return payload


def test_post_compact_marks_boundary_without_additional_context(
        conn, hook_env):
    _seed(conn)
    stdout = io.StringIO()

    post_compact.run(_payload(), stdout)

    assert store.latest_for_session(conn, "session-1").compacted_at is not None
    assert stdout.getvalue() == ""


def test_post_compact_replay_is_idempotent(conn, hook_env):
    checkpoint = _seed(conn)

    post_compact.run(_payload(), io.StringIO())
    post_compact.run(_payload(), io.StringIO())

    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log"
        " WHERE op = 'checkpoint_compacted'"
    ).fetchone()["n"] == 1
    assert store.get(conn, checkpoint.id).compacted_at is not None


def test_delayed_post_compact_marks_matching_superseded_turn(conn, hook_env):
    older = _seed(conn, cursor="event-a")
    newer = store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id="session-1", turn_id="turn-b", cursor="event-b",
        source="PreCompact", trigger="auto", cwd="/work/project",
        project_root="/work/project",
    ))

    post_compact.run(_payload(turn_id="turn-7"), io.StringIO())

    assert store.get(conn, older.id).compacted_at is not None
    assert store.get(conn, newer.id).compacted_at is None


def test_post_compact_db_failure_emits_only_system_message(
        hook_env):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    stdout = io.StringIO()

    post_compact.run(_payload(), stdout)

    assert json.loads(stdout.getvalue()) == {
        "systemMessage": "checkpoint bookkeeping delayed"
    }
    assert "additionalContext" not in stdout.getvalue()


def test_post_compact_main_exits_zero_on_garbage_stdin(
        hook_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("garbage"))

    assert post_compact.main() == 0
    assert capsys.readouterr().out == ""
