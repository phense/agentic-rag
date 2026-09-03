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

import errno
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import backup, curation, db, mining, provider_health, store
from .continuity import enrich
from .config import Config, load_config
from .llm import LLMUnavailableError
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


def _log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} "
                     f"{msg}\n")
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
                runner=subprocess.run, on_provider_success=None) -> str | None:
    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
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
        return res.new_last_uuid
    if job["kind"] == "checkpoint_enrich":
        cursor = enrich.enrich_checkpoint(
            conn, cfg, job, runner=runner,
            on_provider_success=on_provider_success,
        )
        _log(f"checkpoint_enrich {payload.get('checkpoint_id')}: done")
        return cursor
    if job["kind"] == "embed":
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


def _complete(conn, job_id: int, last_uuid: str | None) -> None:
    conn.execute(
        "UPDATE mining_queue SET status = 'done', finished_at = now(),"
        " last_uuid = COALESCE(%s, last_uuid) WHERE id = %s",
        (last_uuid, job_id))
    conn.commit()


def _fail(conn, cfg: Config, job: dict, error: Exception) -> None:
    conn.rollback()   # discard any half-done writes of this job
    if job["attempts"] >= cfg.worker_max_attempts:
        conn.execute(
            "UPDATE mining_queue SET status = 'error', finished_at = now(),"
            " last_error = %s WHERE id = %s",
            (str(error)[:500], job["id"]))
    else:
        delay = cfg.worker_backoff_seconds * 2 ** (job["attempts"] - 1)
        conn.execute(
            "UPDATE mining_queue SET status = 'pending', last_error = %s,"
            " next_attempt_at = now() + make_interval(secs => %s)"
            " WHERE id = %s",
            (str(error)[:500], delay, job["id"]))
    conn.commit()


def _provider_unavailable(conn, cfg: Config, job: dict,
                          error: LLMUnavailableError) -> None:
    """Restore a provider-blocked job without spending its attempt budget."""
    conn.rollback()
    clean = strip_secrets(str(error)[:500])[0]
    conn.execute(
        "UPDATE mining_queue SET status = 'pending',"
        " attempts = GREATEST(attempts - 1, 0), finished_at = NULL,"
        " last_error = %s,"
        " next_attempt_at = now() + make_interval(secs => %s)"
        " WHERE id = %s",
        (clean, cfg.provider_backoff_seconds, job["id"]))
    conn.commit()
    provider_health.record_failure(cfg.llm_provider, clean)


def drain(conn, cfg: Config, *, runner=subprocess.run,
          max_jobs: int = 50) -> dict:
    done = failed = unavailable = 0
    for _ in range(max_jobs):
        job = claim_next(conn)
        if job is None:
            break
        provider_succeeded = False

        def note_provider_success() -> None:
            nonlocal provider_succeeded
            provider_succeeded = True

        try:
            new_uuid = process_job(
                conn, cfg, job, runner=runner,
                on_provider_success=note_provider_success,
            )
            _complete(conn, job["id"], new_uuid)
            if job["kind"] in {"mine", "curate"} or provider_succeeded:
                provider_health.record_success(cfg.llm_provider)
            done += 1
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
    lock = acquire_lock(LOCK_PATH)
    if lock is None:
        return 0        # another writer is live — skip, never queue
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            requeue_orphans(conn, cfg)
            rep = drain(conn, cfg)
            _log(f"drain: {rep}")
            if not rep["provider_unavailable"]:
                curation.run_pass(conn, cfg)
        finally:
            conn.close()
        _opportunistic_backup(cfg)
    except Exception as e:  # noqa: BLE001 — never surface into a hook
        _log(f"worker error: {e!r}")
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
