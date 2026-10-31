from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agentic_rag import backup
from agentic_rag.config import Config


def _mk(dir: Path, when: datetime) -> Path:
    p = dir / f"agentic_rag-{when:%Y%m%d-%H%M%S}.dump"
    p.write_bytes(b"x")
    return p


def test_rotate_keeps_daily_and_weekly(tmp_path):
    now = datetime(2026, 7, 5, 3, 30)
    files = [_mk(tmp_path, now - timedelta(days=i)) for i in range(30)]
    deleted = backup.rotate(tmp_path, keep_daily=5, keep_weekly=2)
    kept = sorted(p.name for p in tmp_path.glob("*.dump"))
    assert len(kept) == 5 + 2
    assert files[0].name in kept          # newest survives
    assert set(p.name for p in deleted).isdisjoint(kept)


def test_rotate_ignores_foreign_files(tmp_path):
    (tmp_path / "unrelated.txt").write_text("keep me")
    _mk(tmp_path, datetime(2026, 7, 1))
    backup.rotate(tmp_path, keep_daily=1)
    assert (tmp_path / "unrelated.txt").exists()


def test_run_backup_local_and_cloud(tmp_path, cfg, dbinit, monkeypatch):
    # never touch the real ~/.agentic-rag/state in tests
    monkeypatch.setattr(backup, "WARNING_STATE", tmp_path / "state" / "warn")
    c = Config(db_name=cfg.db_name,
               backup_local_dir=tmp_path / "local",
               backup_cloud_dir=tmp_path / "cloud",
               backup_keep_local=7, backup_keep_daily=14, backup_keep_weekly=8)
    res = backup.run_backup(c)
    assert res.local_path.exists() and res.local_path.stat().st_size > 0
    assert res.cloud_path is not None and res.cloud_path.exists()
    assert res.warnings == []
    assert not backup.WARNING_STATE.exists()


def test_run_backup_cloud_missing_warns(tmp_path, cfg, dbinit, monkeypatch):
    monkeypatch.setattr(backup, "WARNING_STATE", tmp_path / "state" / "warn")
    c = Config(db_name=cfg.db_name,
               backup_local_dir=tmp_path / "local",
               # parent /nonexistent does not exist and must NOT be created:
               backup_cloud_dir=Path("/nonexistent-volume/agentic-rag-backups"))
    res = backup.run_backup(c)
    assert res.local_path.exists()
    assert res.cloud_path is None
    assert any("cloud" in w.lower() for w in res.warnings)
    assert backup.WARNING_STATE.exists()


def test_pg_failure_surfaces_stderr(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "WARNING_STATE", tmp_path / "state" / "warn")
    c = Config(db_name="definitely_missing_db_xyz",
               backup_local_dir=tmp_path / "local",
               backup_cloud_dir=tmp_path / "cloud")
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        backup.run_backup(c)


def test_restore_refuses_without_confirmation(tmp_path, cfg):
    with pytest.raises(RuntimeError, match="confirmation"):
        backup.restore(Config(db_name=cfg.db_name), tmp_path / "x.dump")


def test_restore_roundtrip(tmp_path, cfg, dbinit, conn, monkeypatch):
    monkeypatch.setattr(backup, "WARNING_STATE", tmp_path / "state" / "warn")
    conn.execute("INSERT INTO domains(name) VALUES ('probe')")
    conn.commit()
    before_acl = _relation_acl(conn)
    before_defaults = _default_acl(conn)
    conn.rollback()
    c = Config(db_name=cfg.db_name, backup_local_dir=tmp_path,
               backup_cloud_dir=tmp_path / "no-cloud")
    res = backup.run_backup(c)
    conn.autocommit = True
    conn.execute("DELETE FROM domains WHERE name = 'probe'")  # owner may delete
    backup.restore(c, res.local_path, assume_yes=True)
    import psycopg
    check = psycopg.connect(f"dbname={cfg.db_name}")
    assert check.execute(
        "SELECT 1 FROM domains WHERE name = 'probe'").fetchone()
    check.close()
    # CREATE during an in-place restore must not inherit extra default grants.
    assert _relation_acl(conn) == before_acl
    assert _default_acl(conn) == before_defaults
    from agentic_rag.service.schema import validate_schema
    validate_schema(conn)


def _relation_acl(conn):
    return conn.execute("""SELECT c.relname, a.grantor::regrole::text grantor,
        a.grantee, a.privilege_type, a.is_grantable
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,
            acldefault(CASE WHEN c.relkind='S' THEN 'S'::\"char\" ELSE 'r'::\"char\" END,c.relowner))) a
        WHERE n.nspname='public' AND c.relkind IN ('r','S')
        ORDER BY c.relname,grantor,a.grantee,a.privilege_type""").fetchall()


def _default_acl(conn):
    return conn.execute("""SELECT defaclrole, defaclnamespace, defaclobjtype, defaclacl::text
        FROM pg_default_acl ORDER BY defaclrole,defaclnamespace,defaclobjtype""").fetchall()


@pytest.mark.parametrize('failure', ['producer_exit', 'producer_mid', 'sql_error', 'sql_mid'])
def test_failed_restore_rolls_back_rows_and_default_privileges(tmp_path, cfg, conn, monkeypatch, failure):
    # A complete-looking stream from a failed producer must never be committed.
    c = Config(db_name=cfg.db_name, backup_local_dir=tmp_path, backup_cloud_dir=None)
    archive = backup.run_backup(c).local_path
    conn.execute("INSERT INTO domains(name) VALUES ('after-backup')")
    conn.commit()
    before_acl, before_defaults = _relation_acl(conn), _default_acl(conn)
    conn.rollback()
    real_bin = backup._pg_bin
    wrapper = tmp_path / 'pg-restore-failure'
    wrapper.write_text('#!/usr/bin/python3\nimport subprocess,sys\n'
                       f'p=subprocess.run([{real_bin("pg_restore", c)!r},*sys.argv[1:]],stdout=subprocess.PIPE)\n'
                       'if p.returncode: sys.exit(p.returncode)\n'
                       'out=p.stdout\n'
                       'if "--list" in sys.argv:\n sys.stdout.buffer.write(out); sys.exit(0)\n'
                       f'mode={failure!r}\n'
                       'if mode=="producer_mid":\n sys.stdout.buffer.write(out[:len(out)//2]); sys.exit(19)\n'
                       'if mode=="sql_mid":\n i=out.index(b"\\nCOPY "); out=out[:i]+b"\\nSELECT 1/0;\\n"+out[i:]\n'
                       'sys.stdout.buffer.write(out); sys.stdout.flush()\n'
                       'if mode=="producer_exit": sys.exit(19)\n'
                       'if mode=="sql_error": print("SELECT 1/0;",flush=True)\n')
    wrapper.chmod(0o700)
    monkeypatch.setattr(backup, '_pg_bin', lambda name, config=None:
                        str(wrapper) if name == 'pg_restore' else real_bin(name, config))
    with pytest.raises(RuntimeError, match='restore failed'):
        backup.restore(c, archive, assume_yes=True)
    assert conn.execute("SELECT 1 FROM domains WHERE name='after-backup'").fetchone()
    assert _relation_acl(conn) == before_acl
    assert _default_acl(conn) == before_defaults


def test_restore_rejects_large_objects_before_changing_target(tmp_path, cfg, conn):
    oid = conn.execute("SELECT lo_from_bytea(0,'synthetic-large-object'::bytea) oid").fetchone()['oid']
    conn.commit()
    try:
        archive = backup.run_backup(Config(db_name=cfg.db_name, backup_local_dir=tmp_path,
                                           backup_cloud_dir=None)).local_path
        conn.execute("INSERT INTO domains(name) VALUES ('after-large-object-backup')")
        conn.commit()
        before_acl, before_defaults = _relation_acl(conn), _default_acl(conn)
        conn.rollback()
        with pytest.raises(RuntimeError, match='large objects require an empty restore target'):
            backup.restore(cfg, archive, assume_yes=True)
        assert conn.execute("SELECT 1 FROM domains WHERE name='after-large-object-backup'").fetchone()
        assert bytes(conn.execute('SELECT lo_get(%s) value', (oid,)).fetchone()['value']) == b'synthetic-large-object'
        assert _relation_acl(conn) == before_acl
        assert _default_acl(conn) == before_defaults
    finally:
        conn.rollback()
        conn.execute('SELECT lo_unlink(%s)', (oid,))
        conn.commit()


def _function_acl(conn):
    return conn.execute("""SELECT p.oid::regprocedure::text name, a.grantee, a.privilege_type,
        a.is_grantable FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE n.nspname='public' ORDER BY name,a.grantee,a.privilege_type""").fetchall()


def test_restore_preserves_function_acl_with_custom_operator_defaults(tmp_path, cfg, conn):
    conn.execute('ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO rag_reader')
    conn.commit()
    try:
        before_functions, before_defaults = _function_acl(conn), _default_acl(conn)
        conn.rollback()
        archive = backup.run_backup(Config(db_name=cfg.db_name, backup_local_dir=tmp_path,
                                           backup_cloud_dir=None)).local_path
        backup.restore(cfg, archive, assume_yes=True)
        assert _function_acl(conn) == before_functions
        assert _default_acl(conn) == before_defaults
    finally:
        conn.rollback()
        conn.execute('ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM rag_reader')
        conn.commit()


def test_pg_bin_prefers_path(monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda n: "/usr/bin/" + n)
    assert backup._pg_bin("pg_dump") == "/usr/bin/pg_dump"


def test_pg_bin_uses_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _: None)
    bindir = tmp_path / "pgbin"
    bindir.mkdir()
    fake = bindir / "pg_dump"
    fake.write_text("")
    cfg = Config(pg_bin_dir=bindir)
    assert backup._pg_bin("pg_dump", cfg) == str(fake)


def test_pg_bin_missing_raises(monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _: None)
    monkeypatch.setattr(backup, "_PG_FALLBACK_DIRS", {})
    with pytest.raises(RuntimeError, match="not found"):
        backup._pg_bin("pg_dump", Config())


def test_run_backup_no_cloud_configured(tmp_path, cfg, dbinit, monkeypatch):
    monkeypatch.setattr(backup, "WARNING_STATE", tmp_path / "state" / "warn")
    c = Config(db_name=cfg.db_name, backup_local_dir=tmp_path / "local",
               backup_cloud_dir=None)
    res = backup.run_backup(c)
    assert res.local_path.exists()
    assert res.cloud_path is None
    assert res.warnings == []                 # unset cloud is not a warning
    assert not backup.WARNING_STATE.exists()


def test_preseeded_warning_state_cleared_on_cloud_success(
        tmp_path, cfg, dbinit, monkeypatch):
    # a stale warning from a failed night must disappear after the first
    # successful cloud backup — otherwise SessionStart warns forever
    warn = tmp_path / "state" / "warn"
    warn.parent.mkdir(parents=True)
    warn.write_text("2026-07-04 cloud backup dir unavailable")
    monkeypatch.setattr(backup, "WARNING_STATE", warn)
    c = Config(db_name=cfg.db_name,
               backup_local_dir=tmp_path / "local",
               backup_cloud_dir=tmp_path / "cloud")
    res = backup.run_backup(c)
    assert res.cloud_path is not None and res.cloud_path.exists()
    assert not warn.exists()
