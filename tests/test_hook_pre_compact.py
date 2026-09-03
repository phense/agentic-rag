import io
import json
import subprocess

from agentic_rag.continuity import store
from agentic_rag.transcript import build_digest
from agentic_rag.hooks import pre_compact


def _payload(tmp_path, **over):
    transcript = tmp_path / "replay.jsonl"
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
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True,
        capture_output=True, text=True,
    )
    payload = _payload(tmp_path)

    pre_compact.run(payload)
    before = store.latest_for_session(conn, payload["session_id"])
    audit_count = conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_snapshot'"
    ).fetchone()["n"]
    pre_compact.run(payload)

    after = store.latest_for_session(conn, payload["session_id"])
    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints"
    ).fetchone()["n"] == 1
    assert _queue_count(conn, "checkpoint_enrich") == 1
    assert after.git == before.git
    assert after.project_root == before.project_root
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_snapshot'"
    ).fetchone()["n"] == audit_count


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


def test_pre_compact_persists_before_optional_repository_probe(
        conn, hook_env, tmp_path, monkeypatch):
    payload = _payload(tmp_path)
    observed = []
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)

    def failing_git_probe(*args, **kwargs):
        observed.append(
            store.latest_for_session(conn, payload["session_id"]) is not None)
        raise OSError("git probe unavailable")

    monkeypatch.setattr(pre_compact.capture, "_git_state", failing_git_probe)

    pre_compact.run(payload)

    assert observed == [True]
    assert store.latest_for_session(conn, payload["session_id"]) is not None
    assert _queue_count(conn, "checkpoint_enrich") == 1


def test_pre_compact_replay_recovers_persisted_predecessor_after_enqueue_failure(
        conn, hook_env, tmp_path, monkeypatch):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({
            "uuid": "u1",
            "message": {"role": "user", "content": "old context"},
        }) + "\n" + json.dumps({
            "uuid": "u2",
            "message": {"role": "user", "content": "new context"},
        }) + "\n"
    )
    payload = _payload(tmp_path, transcript_path=str(transcript))
    store.upsert_snapshot(conn, pre_compact.capture.CheckpointSnapshot(
        session_id=payload["session_id"],
        turn_id="turn-6",
        cursor="u1",
        source="PreCompact",
        trigger="auto",
        cwd=str(tmp_path),
        project_root=None,
    ))
    real_enqueue = pre_compact.jobs.enqueue_checkpoint_enrichment
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(
        pre_compact.jobs,
        "enqueue_checkpoint_enrichment",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("queue down")),
    )

    pre_compact.run(payload)
    saved = store.latest_for_session(conn, payload["session_id"])
    assert saved.cursor == "u2"
    assert saved.predecessor_cursor == "u1"

    monkeypatch.setattr(
        pre_compact.jobs, "enqueue_checkpoint_enrichment", real_enqueue)
    pre_compact.run(payload)

    job = conn.execute(
        "SELECT * FROM mining_queue WHERE kind = 'checkpoint_enrich'"
    ).fetchone()
    assert job["last_uuid"] == "u1"
    digest = build_digest(job["transcript_path"], after_uuid=job["last_uuid"])
    assert "new context" in digest.text
    assert "old context" not in digest.text


def _claude_payload(tmp_path, **over):
    payload = _payload(tmp_path)
    del payload["turn_id"]
    payload["permission_mode"] = "default"
    payload["custom_instructions"] = None
    payload.update(over)
    return payload


def test_pre_compact_claude_prints_prompt_and_checkpoint_line(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()
    payload = _claude_payload(tmp_path)

    pre_compact.run(payload, stdout)

    checkpoint = store.latest_for_session(conn, payload["session_id"])
    out = stdout.getvalue()
    assert out.startswith("# Claude compact continuation instructions")
    assert out.rstrip().endswith(f"agentic-rag checkpoint: {checkpoint.id}")
    assert _queue_count(conn, "checkpoint_enrich") == 1


def test_pre_compact_claude_prints_prompt_without_line_when_db_down(
        hook_env, tmp_path, monkeypatch):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()

    pre_compact.run(_claude_payload(tmp_path), stdout)

    out = stdout.getvalue()
    assert out.startswith("# Claude compact continuation instructions")
    # the prompt body names the line as an instruction; only an appended
    # trailing line (starting with the prefix) would carry a checkpoint id
    assert not any(
        line.startswith(pre_compact.CHECKPOINT_LINE_PREFIX)
        for line in out.splitlines()
    )
    assert "no_such_database_xyz" not in out


def test_pre_compact_codex_stays_silent_on_stdout(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(pre_compact.common, "spawn_worker", lambda: None)
    stdout = io.StringIO()

    pre_compact.run(_payload(tmp_path), stdout)

    assert stdout.getvalue() == ""


def test_pre_compact_kill_switch_silences_claude_prompt(
        hook_env, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_RAG_HOOKS_DISABLE", "1")
    stdout = io.StringIO()

    pre_compact.run(_claude_payload(tmp_path), stdout)

    assert stdout.getvalue() == ""
