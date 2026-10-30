"""The single writer (spec §3): a short-lived flock-singleton process that
drains the mining_queue serially, then runs a bounded curation pass and an
opportunistic backup, then exits. Spawned by hooks (Stop, SessionStart);
however many sessions run concurrently, at most one writer exists.

flock, never a PID file: the kernel releases the lock on process death, so
a jetsam-killed worker can never leave a stale lock (the 2026-07-05
ultra-memory incident class). Contention → skip immediately, never queue.

Every failure path logs to ~/.agentic-rag/log/worker.log and exits 0 — a
worker crash must never surface into a hook or a session.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import backup, curation, db, jobs, mining, provider_health, store
from .continuity import enrich
from .config import Config, load_config
from .llm import LLMUnavailableError
from .service.engine import JobBlocked, ResourcePressure
from .service.fence import OWNER_LOCK,EXECUTION_LOCK,WorkerAuthorityLost,assert_authority,worker_scope
from .secrets import strip_secrets

# The singleton lock primitive, dispatched by platform. fcntl is POSIX-only —
# a top-level `import fcntl` would make this module unimportable on Windows —
# so the import is conditional and Windows uses msvcrt instead. Both raise
# BlockingIOError on contention and a plain OSError on a genuine lock failure,
# so acquire_lock's two-branch contract (silent skip vs. logged failure) is
# identical on every platform.
if sys.platform == "win32":
    import msvcrt

    # msvcrt.locking reports "region already held" with EDEADLOCK (LK_NBLCK's
    # immediate-failure errno) or EACCES; ONLY those mean contention. Any other
    # OSError (a lock-less/odd filesystem, a real I/O error) is a genuine
    # failure and must propagate so acquire_lock logs it — matching POSIX,
    # where flock raises ENOLCK as a plain OSError, not BlockingIOError.
    _CONTENTION_ERRNOS = {errno.EACCES,
                          getattr(errno, "EDEADLOCK", errno.EACCES)}

    def _flock_nb(fd) -> None:
        """Non-blocking exclusive lock (Windows). Translate contention into
        BlockingIOError; let any other OSError propagate as a real failure."""
        try:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as e:
            if e.errno in _CONTENTION_ERRNOS:
                raise BlockingIOError(str(e)) from e
            raise
else:
    import fcntl

    def _flock_nb(fd) -> None:
        """Non-blocking exclusive lock (POSIX). Raises BlockingIOError on
        contention, OSError (e.g. ENOLCK) on a lock-less filesystem."""
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

LOCK_PATH = Path.home() / ".agentic-rag" / "state" / "worker.lock"
LOG_PATH = Path.home() / ".agentic-rag" / "log" / "worker.log"
BACKUP_MAX_AGE_H = 24
CURATION_MAX_AGE_H = 24


def _log(msg: str) -> None:
    try:
        from .bounded_log import append
        append(LOG_PATH,msg)
    except OSError:
        pass


def acquire_lock(path: Path = LOCK_PATH):
    """The singleton gate. Returns an open, flocked file — hold it for the
    process lifetime — or None when another worker is live OR the lock
    location is inaccessible. Both mean: do not run; never crash (main's
    exit-0 contract must hold even before the try block)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = path.open("a+")
    except OSError as e:
        _log(f"lock unavailable: {e!r}")
        return None
    try:
        _flock_nb(fd)
    except BlockingIOError:
        fd.close()
        return None
    except OSError as e:
        # ENOLCK / flock-less filesystem: acquire_lock is called BEFORE
        # main's try block — every lock failure must mean "do not run",
        # never a crash (the exit-0 contract)
        _log(f"lock unavailable: {e!r}")
        fd.close()
        return None
    return fd


@contextmanager
def acquire_database_lock(cfg):
    """Cross-host authority: dedicated session survives all job commits."""
    connection=db.connect(cfg,role='writer')
    try:
        locked=connection.execute('SELECT pg_try_advisory_lock(%s) ok',(OWNER_LOCK,)).fetchone()['ok']
        connection.commit()
        if not locked:
            yield None
            return
        ready=connection.execute('SELECT pg_try_advisory_lock(%s) ok',(EXECUTION_LOCK,)).fetchone()['ok']
        if ready:connection.execute('SELECT pg_advisory_unlock(%s)',(EXECUTION_LOCK,))
        connection.commit()
        yield connection if ready else None
    finally:
        connection.close()


def requeue_orphans(conn, cfg: Config) -> int:
    """The flock guarantees a single live writer, so any 'processing' row
    visible at startup belongs to a dead (SIGKILLed/jetsammed) worker.
    Without this, one orphaned curate row would disable curation forever
    (enqueue_curate skips while one is 'processing'). attempts was already
    incremented by the dead worker's claim, so the max-attempts cap holds."""
    n = conn.execute(
        "UPDATE mining_queue SET"
        " status = CASE WHEN attempts >= %(max)s THEN 'error'"
        "               ELSE 'pending' END,"
        " finished_at = CASE WHEN attempts >= %(max)s THEN now() END,"
        " last_error = 'requeued: stale processing (worker died)'"
        " WHERE status = 'processing'",
        {"max": cfg.worker_max_attempts}).rowcount
    conn.commit()
    if n:
        _log(f"requeued {n} orphaned processing job(s)")
    return n


def claim_next(conn) -> dict | None:
    row = conn.execute(
        "UPDATE mining_queue SET status = 'processing',"
        " attempts = attempts + 1"
        " WHERE id = (SELECT id FROM mining_queue WHERE status = 'pending'"
        "             AND next_attempt_at <= now()"
        "             ORDER BY CASE"
        "               WHEN kind IN ('backup', 'curate') THEN 0"
        "               WHEN kind = 'checkpoint_enrich' THEN 1"
        "               ELSE 2 END, id"
        "             LIMIT 1 FOR UPDATE SKIP LOCKED)"
        " RETURNING id, kind, session_id, transcript_path, payload,"
        "           last_uuid, attempts").fetchone()
    conn.commit()
    return dict(row) if row else None


def process_job(conn, cfg: Config, job: dict, *,
                runner=subprocess.run, on_provider_success=None) -> str | mining.MineResult | None:
    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    if cfg.service_mode=='server' and job['kind'] not in {'source_window','backup'}:
        from .service.resources import check_worker
        check_worker(cfg)
    if job["kind"] == "source_window":
        from .service.worker import process_source
        return process_source(conn,cfg,job,runner=runner)
    if job["kind"] == "mine":
        res = mining.mine_session(
            conn, cfg, session_id=job["session_id"],
            transcript_path=job["transcript_path"],
            last_uuid=job["last_uuid"], project=payload.get("project"),
            runner=runner)
        _log(f"mine {job['session_id']}: saved={res.saved}"
             f" dup={res.duplicates} contra={res.contradictions}"
             f" pin_contra={res.pin_contradictions}"
             f" skipped={res.skipped or '-'}")
        return res
    if job["kind"] == "checkpoint_enrich":
        cursor = enrich.enrich_checkpoint(
            conn, cfg, job, runner=runner,
            on_provider_success=on_provider_success,
        )
        _log(f"checkpoint_enrich {payload.get('checkpoint_id')}: done")
        return cursor
    if job["kind"] == "profile_refresh":
        store.refresh_profile(conn, cfg, payload.get("project"))
        _log("profile_refresh: done")
        return None
    if job["kind"] == "embed":
        if '_principal' in payload:
            from .service.worker import process_embed
            return process_embed(cfg,payload)
        if cfg.service_mode=='server':
            from .service.resources import check_worker
            n = store.reembed_document(conn,cfg,payload['document_id'],before_commit=lambda:check_worker(cfg))
        else:
            n = store.reembed_document(conn, cfg, payload["document_id"])
        _log(f"embed {payload['document_id']}: {n} chunks")
        return None
    if job["kind"] == "curate":
        rep = curation.run_pass(conn, cfg, runner=runner)
        _log(f"curate: {rep}")
        return None
    if job["kind"] == "backup":
        backup.run_backup(cfg)
        _log("backup: done")
        return None
    raise ValueError(f"unknown job kind: {job['kind']}")


def _complete(conn, job_id: int, result: str | mining.MineResult | None) -> None:
    mine = result if isinstance(result, mining.MineResult) else None
    if mine is None:
        conn.execute(
            "UPDATE mining_queue SET status='done',finished_at=now(),"
            "last_uuid=COALESCE(%s,last_uuid) WHERE id=%s", (result, job_id))
        conn.commit()
        return
    cursor = mine.new_last_uuid
    progress = ({"batch_id": mine.batch_id, "has_more": mine.has_more,
                 "warnings": list(mine.warnings)} if mine else {})
    conn.execute(
        "UPDATE mining_queue SET"
        " status = CASE WHEN %s OR COALESCE((payload->>'rerun_requested')::boolean,false)"
        " THEN 'pending' ELSE 'done' END,"
        " finished_at = CASE WHEN %s OR COALESCE((payload->>'rerun_requested')::boolean,false)"
        " THEN NULL ELSE now() END,"
        " last_uuid = COALESCE(%s,last_uuid), attempts=0, last_error=NULL,"
        " next_attempt_at=now(),"
        " payload=(payload - 'rerun_requested') || %s::jsonb WHERE id=%s",
        (bool(mine and mine.has_more), bool(mine and mine.has_more), cursor,
         json.dumps({"mining_progress": progress}) if mine else "{}", job_id))
    conn.commit()


def _fail(conn, cfg: Config, job: dict, error: Exception) -> None:
    conn.rollback()   # discard any half-done writes of this job
    clean = strip_secrets(str(error))[0][:500]
    if job["attempts"] >= cfg.worker_max_attempts:
        conn.execute(
            "UPDATE mining_queue SET status = 'error', finished_at = now(),"
            " last_error = %s WHERE id = %s AND status='processing'",
            (clean, job["id"]))
    else:
        delay = cfg.worker_backoff_seconds * 2 ** (job["attempts"] - 1)
        conn.execute(
            "UPDATE mining_queue SET status = 'pending', last_error = %s,"
            " next_attempt_at = now() + make_interval(secs => %s)"
            " WHERE id = %s AND status='processing'",
            (clean, delay, job["id"]))
    conn.commit()


def _provider_unavailable(conn, cfg: Config, job: dict,
                          error: LLMUnavailableError) -> None:
    """Restore a provider-blocked job without spending its attempt budget."""
    conn.rollback()
    clean = strip_secrets(str(error))[0][:500]
    conn.execute(
        "UPDATE mining_queue SET status = 'pending',"
        " attempts = GREATEST(attempts - 1, 0), finished_at = NULL,"
        " last_error = %s,"
        " next_attempt_at = now() + make_interval(secs => %s)"
        " WHERE id = %s AND status='processing'",
        (clean, cfg.provider_backoff_seconds, job["id"]))
    conn.commit()
    provider_health.record_failure(cfg.llm_provider, clean)


def drain(conn, cfg: Config, *, runner=subprocess.run,
          max_jobs: int = 50, stop=None) -> dict:
    done = failed = unavailable = 0
    for _ in range(max_jobs):
        if stop is not None and stop.is_set():break
        assert_authority()
        job = claim_next(conn)
        if job is None:
            break
        provider_succeeded = False

        def note_provider_success() -> None:
            nonlocal provider_succeeded
            provider_succeeded = True

        try:
            assert_authority()
            new_uuid = process_job(
                conn, cfg, job, runner=runner,
                on_provider_success=note_provider_success,
            )
            _complete(conn, job["id"], new_uuid)
            if job["kind"] in {"mine", "curate"} or provider_succeeded:
                provider_health.record_success(cfg.llm_provider)
            done += 1
        except WorkerAuthorityLost:
            conn.rollback()
            raise
        except ResourcePressure as exc:
            conn.rollback()
            conn.execute("UPDATE mining_queue SET status='pending',attempts=GREATEST(attempts-1,0),"
                         "next_attempt_at=now()+make_interval(secs=>60),last_error=%s "
                         "WHERE id=%s AND status='processing'",(exc.code,job['id']))
            conn.commit()
            failed += 1
            break
        except JobBlocked:
            conn.rollback()
            conn.execute("UPDATE mining_queue SET status='pending',attempts=GREATEST(attempts-1,0),next_attempt_at=now()+make_interval(secs=>60),last_error='authorization_or_predecessor_blocked' WHERE id=%s AND status='processing'",(job['id'],))
            conn.commit()
            failed += 1
        except LLMUnavailableError as e:
            _log(f"job {job['id']} ({job['kind']}) provider unavailable: {e!r}")
            _provider_unavailable(conn, cfg, job, e)
            unavailable += 1
            break
        except Exception as e:  # noqa: BLE001 — per-job fail-open
            _log(f"job {job['id']} ({job['kind']}) failed: {e!r}")
            _fail(conn, cfg, job, e)
            failed += 1
    return {"done": done, "failed": failed,
            "provider_unavailable": unavailable}


def _opportunistic_backup(cfg: Config) -> None:
    dumps = sorted(cfg.backup_local_dir.glob("*.dump"), reverse=True)
    if dumps:
        age_h = (datetime.now().timestamp()
                 - dumps[0].stat().st_mtime) / 3600
        if age_h < BACKUP_MAX_AGE_H:
            return
    backup.run_backup(cfg)
    _log("opportunistic backup: done")


def main(argv: list[str] | None = None) -> int:
    try:
        cfg=load_config()
        if cfg.service_mode=='client': return 0
    except Exception as exc:
        _log(f'worker config error: {exc!r}')
        return 0
    lock = acquire_lock(LOCK_PATH)
    if lock is None: return 0
    try:
        with acquire_database_lock(cfg) as singleton:
            if singleton is None: return 0
            with worker_scope(singleton):
                return _run_owned(cfg)
    except Exception as e:
        _log(f"worker error: {e!r}")
    finally:
        lock.close()
    return 0


def _run_owned(cfg):
    conn = db.connect(cfg, role="writer")
    try:
        requeue_orphans(conn, cfg)
        rep = drain(conn, cfg)
        _log(f"drain: {rep}")
        if not rep["provider_unavailable"]:
            last = jobs.last_curation_at(conn)
            if last is None or (datetime.now(timezone.utc)-last > timedelta(hours=CURATION_MAX_AGE_H)):
                curation.run_pass(conn,cfg)
    finally:
        conn.close()
    _opportunistic_backup(cfg)
    return 0

if __name__ == "__main__":
    sys.exit(main())
