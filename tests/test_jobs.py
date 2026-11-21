import json

import pytest

from agentic_rag import jobs
from agentic_rag.config import Config
from agentic_rag.continuity import store
from agentic_rag.continuity.model import CheckpointSnapshot

CFG = Config(mine_debounce_seconds=600)


def _q(conn, **where):
    cond = " AND ".join(f"{k} = %({k})s" for k in where)
    return conn.execute(
        f"SELECT * FROM mining_queue WHERE {cond} ORDER BY id", where
    ).fetchall()


def test_enqueue_mine_inserts_with_debounce_and_project(conn):
    ok = jobs.enqueue_mine(conn, CFG, session_id="s1",
                           transcript_path="/t/s1.jsonl", project="/proj")
    assert ok is True
    row = _q(conn, session_id="s1")[0]
    assert row["kind"] == "mine"
    assert row["payload"] == {"project": "/proj"}
    assert row["last_uuid"] is None
    delta = conn.execute(
        "SELECT extract(epoch FROM (next_attempt_at - now())) AS d"
        " FROM mining_queue WHERE session_id = 's1'").fetchone()["d"]
    assert 540 < delta <= 600


def test_enqueue_mine_is_idempotent_while_open(conn):
    jobs.enqueue_mine(conn, CFG, session_id="s1",
                      transcript_path="/t/s1.jsonl", project=None)
    ok = jobs.enqueue_mine(conn, CFG, session_id="s1",
                           transcript_path="/t/s1.jsonl", project=None)
    assert ok is False
    assert len(_q(conn, session_id="s1")) == 1


def test_enqueue_mine_carries_last_uuid_from_done_job(conn):
    conn.execute(
        "INSERT INTO mining_queue(kind, session_id, transcript_path, status,"
        " last_uuid) VALUES ('mine', 's1', '/t/s1.jsonl', 'done', 'uuid-42')")
    conn.commit()
    jobs.enqueue_mine(conn, CFG, session_id="s1",
                      transcript_path="/t/s1.jsonl", project=None)
    row = _q(conn, session_id="s1", status="pending")[0]
    assert row["last_uuid"] == "uuid-42"


def test_enqueue_curate_idempotent(conn):
    assert jobs.enqueue_curate(conn, reason="stale") is True
    assert jobs.enqueue_curate(conn, reason="stale again") is False
    rows = _q(conn, kind="curate")
    assert len(rows) == 1


def test_enrichment_enqueue_deduplicates_checkpoint(conn):
    checkpoint = store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id="s", turn_id="t2", cursor="u2", source="PreCompact",
        trigger="auto", cwd="/work", project_root="/work",
    ))

    assert jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path="/t", after_cursor="u1",
    )
    assert not jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path="/t", after_cursor="u1",
    )

    row = _q(conn, kind="checkpoint_enrich")[0]
    assert row["session_id"] == "s"
    assert row["transcript_path"] == "/t"
    assert row["last_uuid"] == "u1"
    assert row["payload"] == {"checkpoint_id": checkpoint.id}


def test_requeue_legacy_provider_failures_is_exact_and_preserves_job_data(conn):
    original = {
        "session_id": "legacy-session", "transcript_path": "/tmp/legacy.jsonl",
        "payload": '{"project":"/work"}', "last_uuid": "turn-7",
    }
    conn.execute(
        "INSERT INTO mining_queue(kind, session_id, transcript_path, payload, status, "
        "attempts, last_uuid, last_error, finished_at) VALUES "
        "('mine', %(session_id)s, %(transcript_path)s, %(payload)s, 'error', 3, "
        "%(last_uuid)s, 'claude binary not found (''claude''); is the CLI on PATH?', now()),"
        "('mine', 's2', '/tmp/b', '{}', 'error', 3, NULL, 'claude exited 1: ', now()),"
        "('mine', 'other', '/tmp/c', '{}', 'error', 3, NULL, 'bad transcript', now())",
        original,
    )
    conn.commit()

    assert jobs.count_legacy_provider_failures(conn) == 2
    assert jobs.requeue_legacy_provider_failures(conn, expected_count=3) is False
    assert jobs.requeue_legacy_provider_failures(conn, expected_count=2) is True

    rows = conn.execute("SELECT * FROM mining_queue ORDER BY id").fetchall()
    assert [(r["status"], r["attempts"]) for r in rows] == [
        ("pending", 0), ("pending", 0), ("error", 3)]
    assert rows[0]["session_id"] == original["session_id"]
    assert rows[0]["transcript_path"] == original["transcript_path"]
    assert rows[0]["payload"] == {"project": "/work"}
    assert rows[0]["last_uuid"] == original["last_uuid"]
    assert rows[0]["finished_at"] is None
    assert "legacy Claude provider failure" in rows[0]["last_error"]


def test_due_jobs_exist_respects_next_attempt_at(conn):
    assert jobs.due_jobs_exist(conn) is False
    jobs.enqueue_curate(conn, reason="now")           # immediate
    assert jobs.due_jobs_exist(conn) is True
    conn.execute(
        "UPDATE mining_queue SET next_attempt_at = now() + interval '1 hour'")
    conn.commit()
    assert jobs.due_jobs_exist(conn) is False


def test_last_curation_at_reads_audit(conn):
    assert jobs.last_curation_at(conn) is None
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary)"
        " VALUES ('mining', 'curation_pass', '0 items')")
    conn.commit()
    assert jobs.last_curation_at(conn) is not None


DUP = "conflicting duplicate transcript identity; recovery required"
META = "source identity has conflicting metadata"


def _mine(conn, session, status, error=None, cursor=None, payload='{}'):
    return conn.execute(
        "INSERT INTO mining_queue(kind, session_id, transcript_path, payload, status, attempts,"
        " last_uuid, last_error, finished_at) VALUES ('mine', %s, %s, %s, %s, 3, %s, %s,"
        " CASE WHEN %s IN ('done','error') THEN now() END) RETURNING id",
        (session, f"/tmp/{session}.jsonl", payload, status, cursor, error, status)).fetchone()["id"]


def test_recoverable_mine_errors_select_newest_exact_error_without_open_job(conn):
    old = _mine(conn, "a", "error", DUP, "c1", '{"rerun_requested":true}')
    newest = _mine(conn, "a", "error", DUP, "c2")
    _mine(conn, "b", "error", DUP)
    _mine(conn, "b", "pending")                       # open job: skip session
    _mine(conn, "c", "error", DUP)
    _mine(conn, "c", "done")                          # later success: skip session
    _mine(conn, "d", "error", DUP + " ")              # not the exact text
    meta = _mine(conn, "e", "error", META)
    conn.commit()
    assert [r["id"] for r in jobs.recoverable_mine_errors(conn, "duplicate-identity")] == [newest]
    assert [r["id"] for r in jobs.recoverable_mine_errors(conn, "source-metadata")] == [meta]
    assert old != newest


def test_requeue_recoverable_mine_errors_is_exact_audited_and_keeps_history(conn):
    old = _mine(conn, "a", "error", DUP, "c1")
    newest = _mine(conn, "a", "error", DUP, "mw1:cursor", '{"project":"/work"}')
    other = _mine(conn, "b", "error", DUP)
    conn.commit()
    # The id set must match the locked re-selection exactly.
    assert not jobs.requeue_recoverable_mine_errors(
        conn, error_class="duplicate-identity", job_ids=[newest])
    assert not jobs.requeue_recoverable_mine_errors(
        conn, error_class="duplicate-identity", job_ids=[newest, old])
    assert not jobs.requeue_recoverable_mine_errors(
        conn, error_class="duplicate-identity", job_ids=[newest, other], excluded_ids=[old])
    assert not jobs.requeue_recoverable_mine_errors(
        conn, error_class="duplicate-identity", job_ids=[newest], excluded_ids=[newest, other])
    with pytest.raises(ValueError, match="at least one"):
        jobs.requeue_recoverable_mine_errors(conn, error_class="duplicate-identity", job_ids=[])
    assert conn.execute("SELECT count(*) n FROM audit_log").fetchone()["n"] == 0
    assert jobs.requeue_recoverable_mine_errors(
        conn, error_class="duplicate-identity", job_ids=[newest], excluded_ids=[other])
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM mining_queue")}
    assert rows[old]["status"] == "error" and rows[old]["last_error"] == DUP
    assert rows[other]["status"] == "error" and rows[other]["last_error"] == DUP
    job = rows[newest]
    assert (job["status"], job["attempts"], job["finished_at"]) == ("pending", 0, None)
    assert job["last_uuid"] == "mw1:cursor" and job["payload"] == {"project": "/work"}
    assert job["last_error"].startswith("requeued: duplicate-identity fixed in code")
    audit = conn.execute("SELECT actor, op, document_id, summary FROM audit_log").fetchall()
    assert len(audit) == 1 and audit[0]["op"] == "mining_queue_requeue"
    assert audit[0]["actor"] == "cli" and audit[0]["document_id"] is None
    assert json.loads(audit[0]["summary"]) == {
        "error_class": "duplicate-identity", "job_ids": [newest], "sessions": ["a"],
        "excluded_ids": [other]}
    # Requeued work is now open, so it is no longer a candidate.
    assert [r["id"] for r in jobs.recoverable_mine_errors(conn, "duplicate-identity")] == [other]


def test_preflight_skips_transcript_for_an_accepted_batch(conn, tmp_path):
    cfg = Config()
    missing = {"id": 1, "session_id": "a", "transcript_path": str(tmp_path / "gone.jsonl"),
               "last_uuid": "mw1:x"}
    with pytest.raises(FileNotFoundError):
        jobs.preflight_mine_job(conn, cfg, missing)
    conn.execute(
        "INSERT INTO mining_batches(session_id, input_cursor, output_cursor, extraction, domains)"
        " VALUES ('a', 'mw1:x', 'mw1:y', '{}', '[]')")
    conn.commit()
    assert jobs.preflight_mine_job(conn, cfg, missing).startswith("replays accepted batch")
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"uuid": "u1", "message": {"role": "user", "content": "hi"}}) + "\n")
    fresh = {**missing, "session_id": "b", "transcript_path": str(path), "last_uuid": None}
    assert jobs.preflight_mine_job(conn, cfg, fresh) == "cursor resolves in transcript"
    with pytest.raises(ValueError, match="recovery required"):
        jobs.preflight_mine_job(conn, cfg, {**fresh, "last_uuid": "mw1:broken"})


def test_requeue_recoverable_mine_errors_rejects_unknown_class(conn):
    with pytest.raises(KeyError):
        jobs.recoverable_mine_errors(conn, "anything")
