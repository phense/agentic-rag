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
