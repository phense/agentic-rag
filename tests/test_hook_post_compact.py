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


def _claude_payload(**over):
    payload = _payload(compact_summary="Goal: finish the adapter.\nNext: run tests.")
    del payload["turn_id"]
    payload["permission_mode"] = "default"
    payload.update(over)
    return payload


def _seed_claude(conn, *, cursor="event-9", trigger="auto"):
    return store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id="session-1", turn_id=None, cursor=cursor,
        source="PreCompact", trigger=trigger, cwd="/work/project",
        project_root="/work/project",
    ))


def test_post_compact_claude_marks_newest_same_trigger_and_stores_handoff(
        conn, hook_env):
    older = _seed_claude(conn, cursor="event-a")
    manual = _seed_claude(conn, cursor="event-b", trigger="manual")
    newest = _seed_claude(conn, cursor="event-c")
    stdout = io.StringIO()

    post_compact.run(_claude_payload(), stdout)

    saved = store.get(conn, newest.id)
    assert saved.compacted_at is not None
    assert saved.handoff == "Goal: finish the adapter.\nNext: run tests."
    assert saved.handoff_at is not None
    assert store.get(conn, older.id).compacted_at is None
    assert store.get(conn, manual.id).compacted_at is None
    assert stdout.getvalue() == ""


def test_post_compact_claude_replay_is_idempotent_and_change_replaces(
        conn, hook_env):
    checkpoint = _seed_claude(conn)

    post_compact.run(_claude_payload(), io.StringIO())
    post_compact.run(_claude_payload(), io.StringIO())
    post_compact.run(_claude_payload(compact_summary="revised summary"),
                     io.StringIO())

    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_compacted'"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_handoff'"
    ).fetchone()["n"] == 2
    assert store.get(conn, checkpoint.id).handoff == "revised summary"


def test_post_compact_claude_bounds_and_strips_handoff(conn, hook_env):
    checkpoint = _seed_claude(conn)
    hook_env.write_text(
        hook_env.read_text() + "\n[continuity]\nhandoff_max_chars = 500\n")
    secret = "sk-ant-api03-" + "b" * 40
    summary = f"token {secret}\n" + "z" * 2000

    post_compact.run(_claude_payload(compact_summary=summary), io.StringIO())

    saved = store.get(conn, checkpoint.id)
    assert len(saved.handoff) <= 500
    assert saved.handoff.endswith("…[truncated]")
    assert secret not in saved.handoff


def test_post_compact_claude_without_checkpoint_or_summary_is_silent(
        conn, hook_env):
    stdout = io.StringIO()
    post_compact.run(_claude_payload(), stdout)          # no checkpoint
    assert stdout.getvalue() == ""

    checkpoint = _seed_claude(conn)
    post_compact.run(_claude_payload(compact_summary=None), stdout)

    saved = store.get(conn, checkpoint.id)
    assert saved.compacted_at is not None
    assert saved.handoff is None
    assert stdout.getvalue() == ""


def test_post_compact_claude_handoff_failure_keeps_boundary(
        conn, hook_env, monkeypatch, tmp_path):
    checkpoint = _seed_claude(conn)
    monkeypatch.setattr(post_compact.common, "HOOK_LOG", tmp_path / "hooks.log")

    def boom(*args, **kwargs):
        raise RuntimeError("handoff store down sk-ant-api03-" + "c" * 40)
    monkeypatch.setattr(post_compact.store, "attach_handoff", boom)
    stdout = io.StringIO()

    post_compact.run(_claude_payload(), stdout)

    assert store.get(conn, checkpoint.id).compacted_at is not None
    assert stdout.getvalue() == ""
    log = (tmp_path / "hooks.log").read_text()
    assert "post_compact.handoff" in log
    assert "sk-ant-api03-" not in log


def test_post_compact_claude_rematches_newest_checkpoint_even_when_compacted(
        conn, hook_env):
    # Pinned decision (spec §5.4 deviation): the newest same-trigger
    # PreCompact row wins, compacted or not.  When a later PreCompact failed
    # to persist, the next PostCompact re-matches the previous checkpoint and
    # replaces its handoff instead of silently losing the newer summary.
    older_uncompacted = _seed_claude(conn, cursor="event-a")
    newest = _seed_claude(conn, cursor="event-b")
    post_compact.run(_claude_payload(compact_summary="first summary"),
                     io.StringIO())
    assert store.get(conn, newest.id).compacted_at is not None

    post_compact.run(_claude_payload(compact_summary="second summary"),
                     io.StringIO())

    saved = store.get(conn, newest.id)
    assert saved.handoff == "second summary"
    assert store.get(conn, older_uncompacted.id).compacted_at is None
    assert store.get(conn, older_uncompacted.id).handoff is None
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_compacted'"
    ).fetchone()["n"] == 1
