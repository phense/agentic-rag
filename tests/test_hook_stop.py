import io
import json

from agentic_rag.hooks import stop_enqueue


def _payload(tmp_path, **over):
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n")
    p = {"session_id": "sess-9", "transcript_path": str(t),
         "cwd": "/Users/example/proj", "hook_event_name": "Stop"}
    p.update(over)
    return p


def test_stop_enqueues_mine_job_and_spawns_worker(conn, hook_env, tmp_path,
                                                  monkeypatch):
    spawned = []
    monkeypatch.setattr(stop_enqueue.common, "spawn_worker",
                        lambda: spawned.append(True))
    stop_enqueue.run(_payload(tmp_path))
    row = conn.execute("SELECT * FROM mining_queue").fetchone()
    assert row["kind"] == "mine"
    assert row["session_id"] == "sess-9"
    assert row["payload"] == {"project": "/Users/example/proj"}
    assert spawned == [True]


def test_stop_missing_transcript_is_a_silent_noop(conn, hook_env,
                                                  monkeypatch):
    monkeypatch.setattr(stop_enqueue.common, "spawn_worker",
                        lambda: (_ for _ in ()).throw(AssertionError()))
    stop_enqueue.run({"session_id": "s", "transcript_path": "/nope.jsonl"})
    assert conn.execute(
        "SELECT count(*) AS n FROM mining_queue").fetchone()["n"] == 0


def test_stop_db_down_never_raises(hook_env, tmp_path, monkeypatch):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    stop_enqueue.run(_payload(tmp_path))     # must not raise
    # the failure is logged to the ISOLATED hook log (hook_env fixture)
    assert "stop_enqueue" in (tmp_path / "hooks.log").read_text()


def test_stop_main_exits_zero_on_garbage_stdin(hook_env, monkeypatch,
                                               capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("garbage"))
    assert stop_enqueue.main() == 0
    assert capsys.readouterr().out == ""     # Stop injects nothing
