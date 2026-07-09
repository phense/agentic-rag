"""Daily agentic-rag maintenance (`rag maintenance`).

Deliberately tiny. A PostgreSQL + pgvector store needs almost none of the
maintenance the legacy file-wiki did: its dedup detectors, link-lint,
graph-rebuild, embedding-mirror sync and git-export all compensated for
markdown/SQLite weaknesses this store does not have — embeddings are written
transactionally, edges are rows (no [[wikilink]] text to break, no graph to
re-parse), and durability is a pg_dump. So this ports NONE of that. It owns only
the genuine residual needs:

  spawn_worker  the single writer (agentic_rag.worker) is otherwise spawned ONLY
                by session hooks, so on an idle machine (no Claude session, or
                Ollama was down when a doc was written) embed-retries / curation /
                the opportunistic backup silently pause. This runs the EXISTING
                flock-singleton worker once; a clean no-op if one is already live
                — no ported logic, no second pipeline (honours the single-writer,
                RAM-lean invariant).
  rotate_logs   the hooks/worker/backup/maintenance logs are append-only; bound
                their growth (size-based, one .1 generation kept).
  verify_backup weekly, REPORT-ONLY: pg_restore the newest dump into an ISOLATED
                throwaway database, sanity-check its row counts against live,
                then drop it. Never touches the live store; never auto-remediates.

Everything runs under a single-flight flock inside an always-exit-0, audited
run() so launchd is never wedged. Deliberately NOT here (data-safety-first):
periodic VACUUM/ANALYZE/REINDEX (autovacuum suffices at this scale), refuted-doc
purge, error-job requeue, and any autonomous near-dup merge — those stay manual
(`rag purge`, `rag review`) or native.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from . import backup as backup_mod
from . import db
from . import worker as worker_mod
from .config import Config, load_config

_STATE_DIR = Path.home() / ".agentic-rag" / "state"
_LOG_DIR = Path.home() / ".agentic-rag" / "log"
_LOCK_PATH = _STATE_DIR / "maintenance.lock"
_AUDIT_PATH = _LOG_DIR / "maintenance-audit.jsonl"
_LOG_PATH = _LOG_DIR / "maintenance.log"

_LOG_MAX_BYTES = 5 * 1024 * 1024   # rotate a log once it passes 5 MiB
_WORKER_TIMEOUT = 900              # 15 min hard cap on the drain tick
_VERIFY_WEEKDAY = 6               # Sunday (Mon=0) — the weekly restore-test
_SCRATCH_SUFFIX = "_verify_scratch"

PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.agentic-rag.maintenance.plist"


def _log(msg: str) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")


# ---- steps -------------------------------------------------------------------

def spawn_worker(cfg: Config, *, timeout: int = _WORKER_TIMEOUT,
                 runner=subprocess.run) -> dict:
    """Run the existing single-writer worker once. It is a flock singleton, so
    if a hook-spawned worker is already live this is a clean no-op (exit 0) — we
    never start a second pipeline."""
    proc = runner([sys.executable, "-m", "agentic_rag.worker"],
                  capture_output=True, text=True, timeout=timeout)
    return {"step": "spawn_worker", "returncode": proc.returncode,
            "ok": proc.returncode == 0}


def rotate_logs(*, log_dir: Path = _LOG_DIR,
                max_bytes: int = _LOG_MAX_BYTES) -> dict:
    """Bound append-only log growth: a log past max_bytes is moved to <log>.1
    (overwriting the previous generation) and started fresh. Touches only app
    logs under the agentic-rag log dir, never the store."""
    rotated = []
    if log_dir.exists():
        for p in sorted(log_dir.glob("*.log")):
            try:
                if p.stat().st_size > max_bytes:
                    p.replace(p.with_name(p.name + ".1"))
                    rotated.append(p.name)
            except OSError:
                continue
    return {"step": "rotate_logs", "rotated": rotated, "ok": True}


def _counts(cfg: Config, dbname: str) -> dict:
    conn = db.connect(cfg, role="owner", dbname=dbname)
    try:
        docs = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
        chunks = conn.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]
    finally:
        conn.close()
    return {"documents": docs, "chunks": chunks}


def _drop_scratch(cfg: Config, scratch: str) -> None:
    admin = psycopg.connect(db.dsn(cfg, "owner", dbname="postgres"),
                            autocommit=True)
    try:
        admin.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
    finally:
        admin.close()


def verify_backup(cfg: Config, *, runner=subprocess.run) -> dict:
    """REPORT-ONLY weekly restore-test. pg_restore the newest local dump into an
    ISOLATED throwaway database, compare its documents/chunks counts to live,
    then drop the scratch DB. Never touches the live store; no auto-remediation.

    The isolation is the load-bearing safety property: the restore target is a
    dedicated scratch database (live name + a fixed suffix), asserted distinct
    from the live db, created fresh and always dropped in the finally."""
    scratch = cfg.db_name + _SCRATCH_SUFFIX
    if scratch == cfg.db_name:                       # defensive — never the live db
        raise RuntimeError("scratch db name collides with the live db")
    dumps = backup_mod._dumps(cfg.backup_local_dir)
    if not dumps:
        return {"step": "verify_backup", "ok": False,
                "warning": "no local dump to verify"}
    dump = dumps[0]

    _drop_scratch(cfg, scratch)                       # clear any stale scratch
    admin = psycopg.connect(db.dsn(cfg, "owner", dbname="postgres"),
                            autocommit=True)
    try:
        admin.execute(f'CREATE DATABASE "{scratch}"')
    finally:
        admin.close()

    try:
        # Ignore pg_restore's exit code: restoring a role-owned/ACL'd dump into a
        # bare scratch db emits non-fatal role/GRANT errors even with
        # --no-owner/--no-privileges. The row counts below are the real signal.
        proc = runner([backup_mod._pg_bin("pg_restore", cfg), "--no-owner",
                       "--no-privileges", "-d", scratch, str(dump)],
                      capture_output=True, text=True, check=False)
        restored = _counts(cfg, scratch)
        live = _counts(cfg, cfg.db_name)
        # A healthy nightly dump loads the corpus; it may lag live slightly but
        # must not be empty or catastrophically short.
        ok = restored["documents"] > 0 and \
            restored["documents"] >= live["documents"] * 0.5
        result = {"step": "verify_backup", "ok": ok, "dump": dump.name,
                  "restored": restored, "live": live}
        if not ok:
            result["warning"] = (
                f"restore-test mismatch: restored={restored} live={live}; "
                f"pg_restore stderr: {(proc.stderr or '').strip()[:200]}")
        return result
    finally:
        _drop_scratch(cfg, scratch)


# ---- orchestration -----------------------------------------------------------

def _write_audit(report: dict) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _AUDIT_PATH.open("a") as fh:
        fh.write(json.dumps(report) + "\n")


def run(cfg: Config | None = None, *, force_verify: bool = False,
        skip_worker: bool = False, now: datetime | None = None) -> int:
    """Single-flight, always-exit-0, audited daily maintenance. Each step is
    isolated: one failing step is logged and recorded but never aborts the run,
    and a non-zero step never propagates a non-zero exit (launchd must not wedge).
    verify_backup self-gates to the weekly weekday unless force_verify."""
    cfg = cfg or load_config()
    started = now or datetime.now()
    lock = worker_mod.acquire_lock(_LOCK_PATH)
    if lock is None:
        _log("skip: another maintenance run holds the lock")
        return 0

    report: dict = {"ts": started.isoformat(timespec="seconds"),
                    "steps": [], "errors": []}
    steps: list = []
    if not skip_worker:
        steps.append(("spawn_worker", lambda: spawn_worker(cfg)))
    steps.append(("rotate_logs", lambda: rotate_logs()))
    if force_verify or started.weekday() == _VERIFY_WEEKDAY:
        steps.append(("verify_backup", lambda: verify_backup(cfg)))

    try:
        for name, fn in steps:
            try:
                res = fn()
                report["steps"].append(res)
                if res.get("ok", True):
                    _log(f"ok {name}: {res}")
                else:
                    report["errors"].append(f"{name}: {res.get('warning', 'not ok')}")
                    _log(f"WARN {name}: {res}")
            except Exception as e:  # noqa: BLE001 — one step must not abort the run
                report["errors"].append(f"{name}: {type(e).__name__}: {e}")
                _log(f"ERROR {name}: {type(e).__name__}: {e}")
    finally:
        _write_audit(report)
        lock.close()

    if report["errors"]:
        # Loud-fail signal for the operator: the audit row + log carry detail (a
        # notifier can tail maintenance-audit.jsonl). Still exit 0 by contract.
        _log(f"run completed with {len(report['errors'])} error(s)")
    return 0


# ---- launchd install ---------------------------------------------------------

_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agentic-rag.maintenance</string>
  <key>ProgramArguments</key>
  <array><string>{rag_bin}</string><string>maintenance</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>StandardOutPath</key><string>{log}</string>
</dict></plist>
"""


def install_launchd(cfg: Config, rag_bin: Path) -> Path:
    """Install the daily 04:00 maintenance job (after the 03:30 backup so the
    Sunday restore-test verifies that morning's fresh dump)."""
    log = _LOG_DIR / "maintenance.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_PLIST.format(rag_bin=rag_bin, log=log))
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)],
                   check=True, capture_output=True, text=True)
    return PLIST_PATH
