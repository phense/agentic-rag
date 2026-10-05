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
        self._log.append(sql.as_string() if hasattr(sql, "as_string") else sql)
        return self

    def fetchone(self):
        return (123, True)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


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
    admin_sql = []
    restore_argv = []
    monkeypatch.setattr(m.backup_mod, "_dumps", lambda d: [Path("d.dump")])
    monkeypatch.setattr(m.backup_mod, "_pg_bin", lambda name, cfg=None: name)
    monkeypatch.setattr(m.psycopg, "connect", lambda *a, **k: _FakeAdmin(admin_sql))
    counts_seen = []
    def counts(config, name):
        counts_seen.append(name)
        return {"documents": 98, "chunks": 200, "audit_log": 150}
    monkeypatch.setattr(m, "_counts", counts)
    def runner(argv, **kw):
        restore_argv.extend(argv)
        assert kw['timeout'] == 900
        return _cp()
    res = m.verify_backup(cfg, runner=runner)
    scratch = counts_seen[0]
    assert scratch.startswith("rag_verify_") and scratch != cfg.db_name
    assert counts_seen == [scratch]
    assert any(f'CREATE DATABASE "{scratch}"' in s for s in admin_sql)
    assert any(f'DROP DATABASE "{scratch}"' in s for s in admin_sql)
    assert not any('DROP DATABASE IF EXISTS' in s for s in admin_sql)
    assert restore_argv[restore_argv.index("-d") + 1] == "dbname=" + scratch
    assert {"--single-transaction", "--exit-on-error"}.issubset(restore_argv)
    assert res['ok'] is True and res['fidelity_verified'] is False


def test_verify_backup_no_dump(cfg, monkeypatch):
    monkeypatch.setattr(m.backup_mod, "_dumps", lambda d: [])
    res = m.verify_backup(cfg, runner=lambda argv, **kw: _cp(rc=0))
    assert res["ok"] is False and "no local dump" in res["warning"]


def test_verify_backup_rejects_nonzero_restore_with_plausible_counts(cfg, monkeypatch):
    """A failed restore must never succeed merely because many rows loaded."""
    monkeypatch.setattr(m.backup_mod, '_dumps', lambda d: [Path('d.dump')])
    monkeypatch.setattr(m.backup_mod, '_pg_bin', lambda name, cfg=None: name)
    monkeypatch.setattr(m.psycopg, 'connect', lambda *a, **k: _FakeAdmin([]))
    monkeypatch.setattr(m, '_counts', lambda *a: {'documents': 98, 'chunks': 200})
    result = m.verify_backup(cfg, runner=lambda *a, **k: _cp(1, 'restore failed'))
    assert result['ok'] is False
    assert result['returncode'] == 1


def test_verify_backup_reports_unverified_fidelity_without_live_comparison(cfg, monkeypatch):
    """A successful restore cannot prove fidelity to an unrelated live snapshot."""
    monkeypatch.setattr(m.backup_mod, '_dumps', lambda d: [Path('d.dump')])
    monkeypatch.setattr(m.backup_mod, '_pg_bin', lambda name, cfg=None: name)
    monkeypatch.setattr(m.psycopg, 'connect', lambda *a, **k: _FakeAdmin([]))
    seen = []
    def counts(config, name):
        seen.append(name)
        return {'documents': 98, 'chunks': 200}
    monkeypatch.setattr(m, '_counts', counts)
    result = m.verify_backup(cfg, runner=lambda *a, **k: _cp())
    assert result['ok'] is True
    assert result['fidelity_verified'] is False
    assert 'unverified' in result['warning']
    assert cfg.db_name not in seen


@pytest.mark.parametrize('failure', ['timeout', 'raised', 'ownership'])
def test_verify_backup_failure_is_reported_and_cleanup_is_guarded(cfg, monkeypatch, failure):
    sql_seen = []
    monkeypatch.setattr(m.backup_mod, '_dumps', lambda d: [Path('d.dump')])
    monkeypatch.setattr(m.backup_mod, '_pg_bin', lambda name, cfg=None: name)
    class Admin(_FakeAdmin):
        def fetchone(self):
            if failure == 'ownership' and any('datdba' in s for s in self._log):
                return (124, False)
            return (123, True)
    monkeypatch.setattr(m.psycopg, 'connect', lambda *a, **k: Admin(sql_seen))
    monkeypatch.setattr(m, '_counts', lambda *a: {'documents': 0, 'chunks': 0})
    def runner(*a, **k):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('pg_restore', 900)
        if failure == 'raised':
            raise OSError('private database content must not leak')
        return _cp()
    result = m.verify_backup(cfg, runner=runner)
    assert result['ok'] is False
    assert 'private database content' not in str(result)
    drops = [s for s in sql_seen if 'DROP DATABASE' in s]
    assert len(drops) == (0 if failure == 'ownership' else 1)
    if failure == 'ownership':
        assert 'cleanup' in result['warning']


def test_verify_backup_creation_failure_does_not_drop_foreign_database(cfg, monkeypatch):
    sql_seen = []
    monkeypatch.setattr(m.backup_mod, '_dumps', lambda d: [Path('d.dump')])
    class Admin(_FakeAdmin):
        def execute(self, sql, *args):
            super().execute(sql, *args)
            raise RuntimeError('database already exists')
    monkeypatch.setattr(m.psycopg, 'connect', lambda *a, **k: Admin(sql_seen))
    result = m.verify_backup(cfg)
    assert result['ok'] is False
    assert not any('DROP DATABASE' in s for s in sql_seen)


def test_restore_diagnostic_never_returns_raw_data():
    assert m._restore_diagnostic('COPY private-data; password=privatepassword permission denied') == 'permission denied'
    assert m._restore_diagnostic('secret user row in failed INSERT') == 'details omitted'
