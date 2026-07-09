from agentic_rag import jobs
from agentic_rag.config import Config

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
