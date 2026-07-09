"""Tests for the tiny `rag maintenance` job.

No real Postgres or subprocess: every external seam (worker spawn, pg_restore,
psycopg admin, db.connect, dump discovery) is monkeypatched. The load-bearing
test is verify_backup's ISOLATION — it must only ever create/drop/restore a
scratch database, never the live one.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from agentic_rag import maintenance as m
from agentic_rag.config import Config


def _cp(rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout="", stderr=stderr)


@pytest.fixture
def cfg():
    return Config(db_name="agentic_rag_unit")


@pytest.fixture(autouse=True)
def _tmp_paths(tmp_path, monkeypatch):
    """Redirect the home-dir log/audit/lock writes into tmp."""
    monkeypatch.setattr(m, "_LOG_DIR", tmp_path / "log")
    monkeypatch.setattr(m, "_LOG_PATH", tmp_path / "log" / "maintenance.log")
    monkeypatch.setattr(m, "_AUDIT_PATH", tmp_path / "log" / "maintenance-audit.jsonl")
    monkeypatch.setattr(m, "_LOCK_PATH", tmp_path / "state" / "maintenance.lock")
    return tmp_path


# ---- rotate_logs -------------------------------------------------------------

def test_rotate_logs_rotates_only_oversized(tmp_path):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    big = log_dir / "worker.log"
    big.write_bytes(b"x" * 200)
    small = log_dir / "hooks.log"
    small.write_bytes(b"y" * 10)
    res = m.rotate_logs(log_dir=log_dir, max_bytes=100)
    assert res["rotated"] == ["worker.log"]
    assert (log_dir / "worker.log.1").exists()
    assert not big.exists()                 # moved aside; a fresh one starts on next write
    assert small.exists() and small.read_bytes() == b"y" * 10


# ---- spawn_worker ------------------------------------------------------------

def test_spawn_worker_runs_the_existing_worker_module(cfg):
    seen = {}

    def fake_runner(argv, **kw):
        seen["argv"] = argv
        seen["timeout"] = kw.get("timeout")
        return _cp(rc=0)

    res = m.spawn_worker(cfg, runner=fake_runner)
    assert seen["argv"][1:] == ["-m", "agentic_rag.worker"]  # the EXISTING worker
    assert seen["timeout"] == m._WORKER_TIMEOUT
    assert res["ok"] is True


# ---- run() orchestration -----------------------------------------------------

class _FakeLock:
    def close(self):
        pass


def test_run_single_flight_noop_when_locked(cfg, monkeypatch):
    monkeypatch.setattr(m.worker_mod, "acquire_lock", lambda path: None)
    called = []
    monkeypatch.setattr(m, "spawn_worker", lambda *a, **k: called.append("w"))
    assert m.run(cfg) == 0
    assert called == []                     # locked → no steps ran
    assert not m._AUDIT_PATH.exists()


def test_run_exits_zero_and_audits_even_when_a_step_raises(cfg, monkeypatch):
    monkeypatch.setattr(m.worker_mod, "acquire_lock", lambda path: _FakeLock())
    monkeypatch.setattr(m, "spawn_worker", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(m, "rotate_logs", lambda *a, **k: {"step": "rotate_logs", "ok": True})
    rc = m.run(cfg, now=datetime(2026, 7, 6))   # a Monday → no verify
    assert rc == 0                              # launchd must never wedge
    audit = json.loads(m._AUDIT_PATH.read_text().strip())
    assert any("spawn_worker" in e and "boom" in e for e in audit["errors"])


def test_verify_gated_to_weekly_weekday(cfg, monkeypatch):
    monkeypatch.setattr(m.worker_mod, "acquire_lock", lambda path: _FakeLock())
    ran = []
    monkeypatch.setattr(m, "spawn_worker", lambda *a, **k: {"step": "spawn_worker", "ok": True})
    monkeypatch.setattr(m, "rotate_logs", lambda *a, **k: {"step": "rotate_logs", "ok": True})
    monkeypatch.setattr(m, "verify_backup", lambda *a, **k: ran.append("v") or {"step": "verify_backup", "ok": True})

    m.run(cfg, now=datetime(2026, 7, 6))     # Monday
    assert ran == []
    m.run(cfg, now=datetime(2026, 7, 5))     # Sunday
    assert ran == ["v"]
    m.run(cfg, now=datetime(2026, 7, 6), force_verify=True)  # forced on a Monday
    assert ran == ["v", "v"]


# ---- verify_backup ISOLATION (the load-bearing safety test) ------------------

class _FakeAdmin:
    def __init__(self, log):
        self._log = log

    def execute(self, sql, *a):
        self._log.append(sql)

    def close(self):
        pass


class _FakeCountConn:
    def __init__(self, n):
        self._n = n

    def execute(self, sql, *a):
        return self

    def fetchone(self):
        return {"n": self._n}

    def close(self):
        pass


def test_verify_backup_only_ever_touches_a_scratch_db(cfg, tmp_path, monkeypatch):
    admin_sql: list[str] = []
    restore_argv: list = []

    monkeypatch.setattr(m.backup_mod, "_dumps",
                        lambda d: [Path("agentic_rag-20260706-182612.dump")])
    monkeypatch.setattr(m.backup_mod, "_pg_bin", lambda name, cfg=None: name)
    monkeypatch.setattr(m.psycopg, "connect",
                        lambda dsn, autocommit=False: _FakeAdmin(admin_sql))
    # scratch restores fewer docs than live but well above the 50% floor
    counts = {cfg.db_name: 100, cfg.db_name + m._SCRATCH_SUFFIX: 98}
    monkeypatch.setattr(m.db, "connect",
                        lambda c, role="owner", dbname=None: _FakeCountConn(counts[dbname]))

    def fake_runner(argv, **kw):
        restore_argv.extend(argv)
        return _cp(rc=0)

    res = m.verify_backup(cfg, runner=fake_runner)

    scratch = cfg.db_name + m._SCRATCH_SUFFIX
    # The live db name must NEVER appear in any CREATE/DROP DATABASE statement.
    for sql in admin_sql:
        if "DATABASE" in sql:
            assert cfg.db_name not in sql.replace(scratch, "")
    assert any(f'CREATE DATABASE "{scratch}"' in s for s in admin_sql)
    assert sum(f'DROP DATABASE IF EXISTS "{scratch}"' in s for s in admin_sql) >= 1
    # pg_restore targets the scratch db, not live
    assert "-d" in restore_argv
    assert restore_argv[restore_argv.index("-d") + 1] == scratch
    assert res["step"] == "verify_backup" and res["ok"] is True


def test_verify_backup_flags_a_short_restore(cfg, monkeypatch):
    monkeypatch.setattr(m.backup_mod, "_dumps", lambda d: [Path("d.dump")])
    monkeypatch.setattr(m.backup_mod, "_pg_bin", lambda name, cfg=None: name)
    monkeypatch.setattr(m.psycopg, "connect",
                        lambda dsn, autocommit=False: _FakeAdmin([]))
    counts = {cfg.db_name: 100, cfg.db_name + m._SCRATCH_SUFFIX: 3}  # catastrophic short
    monkeypatch.setattr(m.db, "connect",
                        lambda c, role="owner", dbname=None: _FakeCountConn(counts[dbname]))
    res = m.verify_backup(cfg, runner=lambda argv, **kw: _cp(rc=0))
    assert res["ok"] is False and "mismatch" in res["warning"]


def test_verify_backup_no_dump(cfg, monkeypatch):
    monkeypatch.setattr(m.backup_mod, "_dumps", lambda d: [])
    res = m.verify_backup(cfg, runner=lambda argv, **kw: _cp(rc=0))
    assert res["ok"] is False and "no local dump" in res["warning"]
