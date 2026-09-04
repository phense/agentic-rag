import io
import json
import subprocess
import sys
import time

import pytest

from agentic_rag.hooks import session_end, stop_enqueue


def _payload(tmp_path, **over):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n")
    payload = {
        "session_id": "session-1",
        "transcript_path": str(transcript),
        "cwd": "/Users/example/proj",
        "hook_event_name": "SessionEnd",
        "reason": "other",
    }
    payload.update(over)
    return payload


def _open_mine_jobs(conn, session_id):
    return conn.execute(
        "SELECT count(*) AS n FROM mining_queue"
        " WHERE kind = 'mine' AND session_id = %s"
        " AND status IN ('pending', 'processing')",
        (session_id,),
    ).fetchone()["n"]


def test_session_end_reuses_mine_dedup(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(stop_enqueue.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path)

    stop_enqueue.run({**payload, "hook_event_name": "Stop"})
    session_end.run(payload)

    assert _open_mine_jobs(conn, payload["session_id"]) == 1


def test_session_end_enqueues_final_delta_and_spawns(
        conn, hook_env, tmp_path, monkeypatch):
    spawned = []
    monkeypatch.setattr(
        session_end.common, "spawn_worker", lambda: spawned.append(True))
    payload = _payload(tmp_path)

    session_end.run(payload)

    assert _open_mine_jobs(conn, payload["session_id"]) == 1
    assert spawned == [True]


def test_session_end_main_always_exits_zero_without_stdout(
        hook_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "session-1",
        "hook_event_name": "SessionEnd",
        "reason": "other",
    })))

    assert session_end.main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "reason", ["clear", "resume", "logout", "prompt_input_exit", "other"])
def test_session_end_claude_enqueues_for_every_reason(
        conn, hook_env, tmp_path, monkeypatch, reason):
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path, reason=reason)

    session_end.run(payload)

    assert _open_mine_jobs(conn, payload["session_id"]) == 1


def test_session_end_codex_keeps_other_only(conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)

    session_end.run(_payload(tmp_path, turn_id="turn-1", reason="clear"))
    assert _open_mine_jobs(conn, "session-1") == 0

    session_end.run(_payload(tmp_path, turn_id="turn-1", reason="other"))
    assert _open_mine_jobs(conn, "session-1") == 1


def test_session_end_wall_time_fits_claude_budget(
        conn, hook_env, tmp_path, monkeypatch):
    """Claude gives all SessionEnd hooks 1.5 s in total.  Interpreter start
    plus import (subprocess) and the enqueue itself (in-process, worker spawn
    stubbed) must stay well below that.  The printed figure is recorded in
    BACKLOG.md during rollout."""
    monkeypatch.setattr(session_end.common, "spawn_worker", lambda: None)
    payload = _payload(tmp_path)

    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-c", "import agentic_rag.hooks.session_end"],
        check=True, capture_output=True,
    )
    session_end.run(payload)
    elapsed = time.perf_counter() - start

    print(f"\nsession_end wall time (startup+import+enqueue): {elapsed:.3f}s")
    assert _open_mine_jobs(conn, payload["session_id"]) == 1
    assert elapsed < 1.0   # matches the installed SessionEnd timeout of 1 s
