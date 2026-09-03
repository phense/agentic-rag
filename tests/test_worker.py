import errno
import json
import sys

import pytest

from agentic_rag import worker
from agentic_rag.config import Config
from agentic_rag.llm import LLMJobError, LLMUnavailableError


def _job(conn, kind, **cols):
    cols = {"kind": kind, "status": "pending", **cols}
    keys = ", ".join(cols)
    ph = ", ".join(f"%({k})s" for k in cols)
    return conn.execute(
        f"INSERT INTO mining_queue({keys}) VALUES ({ph}) RETURNING id",
        cols).fetchone()["id"]


def test_acquire_lock_is_exclusive(tmp_path):
    lock = tmp_path / "worker.lock"
    first = worker.acquire_lock(lock)
    assert first is not None
    assert worker.acquire_lock(lock) is None        # contention → skip
    first.close()
    again = worker.acquire_lock(lock)
    assert again is not None
    again.close()


def test_acquire_lock_inaccessible_location_returns_none(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "w.log")
    blocker = tmp_path / "blocker"
    blocker.write_text("")          # a FILE where the parent dir should be
    assert worker.acquire_lock(blocker / "state" / "worker.lock") is None


@pytest.mark.skipif(sys.platform == "win32",
                    reason="fcntl is POSIX-only; Windows uses the msvcrt "
                           "branch of _flock_nb")
def test_acquire_lock_flock_oserror_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "w.log")
    def no_flock(fd, op):
        raise OSError(errno.ENOLCK, "no locks available")
    monkeypatch.setattr(worker.fcntl, "flock", no_flock)
    assert worker.acquire_lock(tmp_path / "worker.lock") is None
    assert "lock unavailable" in (tmp_path / "w.log").read_text()


def test_acquire_lock_none_on_lock_contention(tmp_path, monkeypatch):
    # The platform lock primitive signals "already held" with BlockingIOError
    # (POSIX flock raises it directly; the Windows msvcrt shim re-raises as
    # one). acquire_lock must translate that to "another worker is live → skip"
    # WITHOUT logging it as an error (contention is normal, not a failure).
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "w.log")
    def busy(fd):
        raise BlockingIOError("locked")
    monkeypatch.setattr(worker, "_flock_nb", busy)
    assert worker.acquire_lock(tmp_path / "worker.lock") is None
    assert not (tmp_path / "w.log").exists()


def test_acquire_lock_none_and_logs_on_lock_oserror(tmp_path, monkeypatch):
    # A real lock failure (ENOLCK / lock-less FS) must also mean "do not run",
    # but this one is logged so the operator can see it.
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "w.log")
    def broken(fd):
        raise OSError(errno.ENOLCK, "no locks available")
    monkeypatch.setattr(worker, "_flock_nb", broken)
    assert worker.acquire_lock(tmp_path / "worker.lock") is None
    assert "lock unavailable" in (tmp_path / "w.log").read_text()


def test_requeue_orphans_respects_max_attempts(conn, cfg):
    _job(conn, "mine", session_id="s1", transcript_path="/t",
         status="processing", attempts=1)
    _job(conn, "curate", status="processing", attempts=3)
    conn.commit()
    cfg2 = Config(db_name=cfg.db_name, worker_max_attempts=3)
    assert worker.requeue_orphans(conn, cfg2) == 2
    rows = {r["kind"]: r for r in conn.execute(
        "SELECT * FROM mining_queue").fetchall()}
    assert rows["mine"]["status"] == "pending"      # retried next drain
    assert rows["curate"]["status"] == "error"      # attempts exhausted
    assert "worker died" in rows["mine"]["last_error"]


def test_claim_next_claims_oldest_due_only(conn):
    stale = _job(conn, "curate")
    _job(conn, "mine", session_id="s-future")
    conn.execute(
        "UPDATE mining_queue SET next_attempt_at = now() + interval '1 hour'"
        " WHERE session_id = 's-future'")
    conn.commit()
    job = worker.claim_next(conn)
    assert job["id"] == stale
    assert job["attempts"] == 1
    assert worker.claim_next(conn) is None          # the future job not due


def test_claim_next_prioritizes_maintenance_then_checkpoint_over_mining(conn):
    mine = _job(conn, "mine", session_id="s-mine", transcript_path="/mine")
    checkpoint = _job(
        conn, "checkpoint_enrich", session_id="s-checkpoint",
        transcript_path="/checkpoint",
        payload=json.dumps({"checkpoint_id": "cp-1"}),
    )
    curate = _job(conn, "curate")
    conn.commit()

    assert worker.claim_next(conn)["id"] == curate
    assert worker.claim_next(conn)["id"] == checkpoint
    assert worker.claim_next(conn)["id"] == mine


def test_worker_dispatches_checkpoint_enrich(conn, cfg, monkeypatch):
    seen = {}

    def fake_enrich(*args, **kwargs):
        seen["call"] = (args, kwargs)
        return "u2"

    monkeypatch.setattr(
        worker.enrich, "enrich_checkpoint", fake_enrich,
    )
    job = {
        "id": 1, "kind": "checkpoint_enrich", "session_id": "s",
        "transcript_path": "/t", "payload": {"checkpoint_id": "cp-1"},
        "last_uuid": "u1", "attempts": 1,
    }
    def on_provider_success():
        pass

    assert worker.process_job(
        conn, cfg, job, runner="runner",
        on_provider_success=on_provider_success,
    ) == "u2"
    args, kwargs = seen["call"]
    assert args[:3] == (conn, cfg, job)
    assert kwargs["runner"] == "runner"
    assert kwargs["on_provider_success"] is on_provider_success


def test_drain_mine_job_completes_and_stamps_last_uuid(conn, cfg, tmp_path,
                                                       monkeypatch):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({
        "uuid": "u9", "type": "user",
        "message": {"role": "user", "content": "hello"}}) + "\n")
    _job(conn, "mine", session_id="s1", transcript_path=str(p),
         payload=json.dumps({"project": "/p"}))
    seen = {}
    def fake_mine(c, cf, **kw):
        seen.update(kw)
        from agentic_rag.mining import MineResult
        return MineResult(saved=2, new_last_uuid="u9")
    monkeypatch.setattr(worker.mining, "mine_session", fake_mine)
    rep = worker.drain(conn, cfg)
    assert rep["done"] == 1
    assert seen["session_id"] == "s1" and seen["project"] == "/p"
    row = conn.execute("SELECT status, last_uuid, finished_at"
                       " FROM mining_queue").fetchone()
    assert row["status"] == "done"
    assert row["last_uuid"] == "u9"
    assert row["finished_at"] is not None


def test_drain_failure_backs_off_then_errors(conn, cfg, monkeypatch):
    cfg2 = Config(db_name=cfg.db_name, worker_max_attempts=2,
                  worker_backoff_seconds=100)
    _job(conn, "mine", session_id="s1", transcript_path="/t.jsonl")
    def boom(c, cf, **kw):
        raise RuntimeError("haiku unavailable")
    monkeypatch.setattr(worker.mining, "mine_session", boom)
    rep1 = worker.drain(conn, cfg2)
    assert rep1["failed"] == 1
    row = conn.execute("SELECT * FROM mining_queue").fetchone()
    assert row["status"] == "pending"               # first failure → retry
    assert row["attempts"] == 1
    assert "haiku unavailable" in row["last_error"]
    delta = conn.execute(
        "SELECT extract(epoch FROM (next_attempt_at - now())) AS d"
        " FROM mining_queue").fetchone()["d"]
    assert 50 < delta <= 100                        # backoff * 2^0
    conn.execute("UPDATE mining_queue SET next_attempt_at = now()")
    conn.commit()
    worker.drain(conn, cfg2)
    row = conn.execute("SELECT status, attempts FROM mining_queue").fetchone()
    assert row["status"] == "error"                 # max attempts reached
    assert row["attempts"] == 2


def test_ordinary_job_failure_sanitizes_queue_error_and_worker_log(
        conn, cfg, tmp_path, monkeypatch):
    secret = "sk-abcdefghijklmnop1234"
    log_path = tmp_path / "worker.log"
    monkeypatch.setattr(worker, "LOG_PATH", log_path)
    _job(conn, "mine", session_id="s1", transcript_path="/t.jsonl")

    def boom(*args, **kwargs):
        raise RuntimeError(f"processing failed with {secret}")

    monkeypatch.setattr(worker.mining, "mine_session", boom)

    assert worker.drain(conn, cfg)["failed"] == 1

    last_error = conn.execute(
        "SELECT last_error FROM mining_queue"
    ).fetchone()["last_error"]
    logged = log_path.read_text()
    assert secret not in last_error
    assert secret not in logged
    assert "[REDACTED]" in last_error
    assert "[REDACTED]" in logged


@pytest.mark.parametrize(
    ("error_type", "result_key"),
    ((RuntimeError, "failed"), (LLMUnavailableError, "provider_unavailable")),
)
def test_job_failure_redacts_before_bounding_queue_error(
        conn, cfg, tmp_path, monkeypatch, error_type, result_key):
    secret = "sk-abcdefghijklmnop1234"
    message = "x" * 489 + " " + secret
    _job(conn, "mine", session_id="s1", transcript_path="/t.jsonl")
    monkeypatch.setattr(
        worker.mining,
        "mine_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(error_type(message)),
    )
    monkeypatch.setattr(
        worker.provider_health, "HEALTH_PATH", tmp_path / "provider-health.json"
    )

    result = worker.drain(conn, cfg)

    assert result[result_key] == 1
    last_error = conn.execute(
        "SELECT last_error FROM mining_queue"
    ).fetchone()["last_error"]
    assert "sk-" not in last_error
    assert "[REDACTED]" in last_error
    assert len(last_error) <= 500


def test_provider_outage_preserves_attempt_and_stops_drain(
        conn, cfg, tmp_path, monkeypatch):
    _job(conn, "mine", session_id="s1", transcript_path="/a")
    _job(conn, "mine", session_id="s2", transcript_path="/b")
    monkeypatch.setattr(
        worker.mining, "mine_session",
        lambda *a, **k: (_ for _ in ()).throw(
            LLMUnavailableError("codex login required")))
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(worker.provider_health, "HEALTH_PATH", health)
    cfg2 = Config(db_name=cfg.db_name, llm_provider="codex",
                  provider_backoff_seconds=3600)

    rep = worker.drain(conn, cfg2)

    rows = conn.execute(
        "SELECT status, attempts FROM mining_queue ORDER BY id").fetchall()
    assert rep == {"done": 0, "failed": 0, "provider_unavailable": 1}
    assert [(r["status"], r["attempts"]) for r in rows] == [
        ("pending", 0), ("pending", 0)]
    delay = conn.execute(
        "SELECT extract(epoch FROM (next_attempt_at - now())) AS d"
        " FROM mining_queue ORDER BY id LIMIT 1").fetchone()["d"]
    assert 3500 < delay <= 3600
    assert worker.provider_health.read_health(health).available is False


def test_job_error_keeps_ordinary_retry_policy(conn, cfg, monkeypatch):
    _job(conn, "mine", session_id="s1", transcript_path="/a")
    monkeypatch.setattr(
        worker.mining, "mine_session",
        lambda *a, **k: (_ for _ in ()).throw(
            LLMJobError("bad structured output")))
    rep = worker.drain(conn, cfg)
    row = conn.execute(
        "SELECT status, attempts FROM mining_queue").fetchone()
    assert rep == {"done": 0, "failed": 1, "provider_unavailable": 0}
    assert (row["status"], row["attempts"]) == ("pending", 1)


def test_successful_llm_job_records_provider_recovery(
        conn, cfg, tmp_path, monkeypatch):
    _job(conn, "mine", session_id="s1", transcript_path="/a")
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(worker.provider_health, "HEALTH_PATH", health)
    worker.provider_health.record_failure("codex", "login", path=health)

    def fake_mine(*a, **k):
        from agentic_rag.mining import MineResult
        return MineResult(saved=0, new_last_uuid="u1")

    monkeypatch.setattr(worker.mining, "mine_session", fake_mine)
    cfg2 = Config(db_name=cfg.db_name, llm_provider="codex")
    rep = worker.drain(conn, cfg2)
    assert rep == {"done": 1, "failed": 0, "provider_unavailable": 0}
    assert worker.provider_health.read_health(health).available is True


def test_drain_dispatches_embed_and_backup(conn, cfg, monkeypatch):
    _job(conn, "embed", payload=json.dumps({"document_id": "d-1"}))
    _job(conn, "backup")
    calls = []
    monkeypatch.setattr(worker.store, "reembed_document",
                        lambda c, cf, did: calls.append(("embed", did)) or 1)
    monkeypatch.setattr(worker.backup, "run_backup",
                        lambda cf: calls.append(("backup", None)))
    rep = worker.drain(conn, cfg)
    assert rep["done"] == 2
    assert ("embed", "d-1") in calls and ("backup", None) in calls


def test_main_skips_when_lock_held(tmp_path, monkeypatch):
    lock = tmp_path / "worker.lock"
    monkeypatch.setattr(worker, "LOCK_PATH", lock)
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "worker.log")
    held = worker.acquire_lock(lock)
    def exploding_connect(*a, **k):
        raise AssertionError("must not touch the DB when lock is held")
    monkeypatch.setattr(worker.db, "connect", exploding_connect)
    assert worker.main([]) == 0
    held.close()


def test_main_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "worker.log")
    def broken_connect(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(worker.db, "connect", broken_connect)
    assert worker.main([]) == 0                     # logged, not raised
    assert "db down" in (tmp_path / "worker.log").read_text()


def test_main_skips_post_drain_curation_after_provider_outage(
        tmp_path, monkeypatch):
    class Conn:
        def close(self):
            pass

    conn = Conn()
    monkeypatch.setattr(worker, "LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "worker.log")
    monkeypatch.setattr(worker, "load_config", lambda: Config())
    monkeypatch.setattr(worker.db, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(worker, "requeue_orphans", lambda *a, **k: 0)
    monkeypatch.setattr(
        worker, "drain", lambda *a, **k:
        {"done": 0, "failed": 0, "provider_unavailable": 1})
    monkeypatch.setattr(
        worker.curation, "run_pass",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not make another LLM call")))
    monkeypatch.setattr(worker, "_opportunistic_backup", lambda *a: None)
    assert worker.main([]) == 0
