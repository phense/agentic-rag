"""Real pg_restore rehearsals against owned source and scratch databases."""
from contextlib import contextmanager
from uuid import uuid4
import subprocess
import time

import psycopg
from psycopg import sql
import pytest

from agentic_rag import backup, db, domains, maintenance, pins, store
from agentic_rag.config import Config


@contextmanager
def owned_source(tmp_path, schema):
    cfg = Config(db_name='rag_restore_test_' + uuid4().hex,
                 backup_local_dir=tmp_path / 'dumps', ollama_url='http://localhost:1')
    with psycopg.connect(db.dsn(cfg, dbname='postgres'), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(cfg.db_name)))
        oid = admin.execute('SELECT oid FROM pg_database WHERE datname=%s', (cfg.db_name,)).fetchone()[0]
    try:
        schema_dir = tmp_path / 'sql'
        schema_dir.mkdir()
        for path in sorted(db.SQL_DIR.glob('*.sql'))[:schema]:
            (schema_dir / path.name).write_bytes(path.read_bytes())
        with db.connect(cfg) as conn:
            db.apply_migrations(conn, schema_dir)
            domains.seed_defaults(conn)
            domains.add_domain(conn, 'programming')
            for domain in ('general', 'programming'):
                store.save_assertion(conn, cfg, entity='Public service ' + domain, attribute='port', value='8766',
                    event_at='2026-10-01T00:00:00Z', domain=domain, project='/synthetic/backup',
                    evidence={'source_id':domain, 'role':'user', 'quote':'port 8766'})
            pins.add_pin(conn, body='Preserve public backup evidence', scope='global')
        yield cfg
    finally:
        maintenance._drop_scratch(cfg, cfg.db_name, oid)


def scratch_names(cfg):
    with psycopg.connect(db.dsn(cfg, dbname='postgres')) as admin:
        return {r[0] for r in admin.execute("SELECT datname FROM pg_database WHERE datname LIKE 'rag_verify_%'")}


@pytest.mark.parametrize('schema', [18, 19])
def test_complete_legacy_and_current_archive_restore_with_full_inventory(tmp_path, schema):
    with owned_source(tmp_path, schema) as cfg:
        expected = maintenance._counts(cfg, cfg.db_name)
        backup.run_backup(cfg)
        # Live changes after the dump are not a consistency comparison target.
        with db.connect(cfg) as conn:
            store.save_document(conn, cfg, title='After backup', body='Public later evidence',
                                domain='general', dtype='memory')
        before = scratch_names(cfg)
        result = maintenance.verify_backup(cfg)
        assert result['ok'] is True, result
        assert result['returncode'] == 0
        assert result['restored'] == expected
        assert result['restored']['documents'] == 2
        assert result['restored']['pins'] == 1
        assert result['restored']['fact_assertions'] == 2
        assert result['restored']['knowledge_sources'] > 0
        assert result['restored']['audit_log'] > 0
        assert result['fidelity_verified'] is False
        assert 'unverified' in result['warning']
        assert scratch_names(cfg) == before
        assert maintenance._counts(cfg, cfg.db_name)['documents'] == 3


@pytest.mark.parametrize('failure', ['truncated', 'interrupted'])
def test_failed_restore_rehearsal_never_succeeds_or_leaves_scratch(tmp_path, failure):
    with owned_source(tmp_path, 19) as cfg:
        if failure == 'interrupted':
            # Public test-only DDL: COPY blocks inside the restore transaction.
            with db.connect(cfg) as conn:
                conn.execute("CREATE FUNCTION restore_pause(integer) RETURNS boolean LANGUAGE plpgsql AS $$ "
                             "BEGIN PERFORM pg_advisory_xact_lock(784159261); RETURN true; END $$")
                conn.execute("CREATE TABLE restore_probe(value integer CHECK (restore_pause(value)))")
                conn.execute("INSERT INTO restore_probe VALUES (1)")
        dump = backup.run_backup(cfg).local_path
        expected = maintenance._counts(cfg, cfg.db_name)
        before = scratch_names(cfg)
        observed = []
        if failure == 'truncated':
            dump.write_bytes(dump.read_bytes()[:128])
            runner = subprocess.run
        else:
            def runner(argv, **kwargs):
                target_dsn = argv[argv.index('-d') + 1]
                with psycopg.connect(target_dsn, autocommit=True) as blocker:
                    blocker.execute('SELECT pg_advisory_lock(784159261)')
                    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            active = blocker.execute(
                                "SELECT query, xact_start, pid FROM pg_stat_activity "
                                "WHERE datname=current_database() AND wait_event_type='Lock' "
                                "AND lower(wait_event)='advisory' AND pid<>pg_backend_pid()"
                            ).fetchone()
                            if active:
                                assert 'COPY' in active[0] and 'restore_probe' in active[0]
                                assert active[1] is not None
                                observed.append('COPY blocked inside restore transaction')
                                break
                            assert proc.poll() is None, 'restore exited before the controlled block'
                            time.sleep(0.02)
                        assert observed, 'restore did not reach controlled COPY block'
                        proc.kill()
                        stdout, stderr = proc.communicate(timeout=5)
                        assert proc.returncode != 0
                        blocker.execute('SELECT pg_advisory_unlock(784159261)')
                        deadline = time.monotonic() + 5
                        while blocker.execute('SELECT 1 FROM pg_stat_activity WHERE pid=%s', (active[2],)).fetchone():
                            assert time.monotonic() < deadline, 'restore backend did not finish rollback'
                            time.sleep(0.02)
                        assert blocker.execute("SELECT to_regclass('public.restore_probe')").fetchone()[0] is None
                        observed.append('DDL and COPY rolled back')
                        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.communicate(timeout=5)
        result = maintenance.verify_backup(cfg, runner=runner)
        assert result['ok'] is False
        assert result['fidelity_verified'] is False
        if failure == 'interrupted':
            assert observed == ['COPY blocked inside restore transaction', 'DDL and COPY rolled back']
            assert result['returncode'] != 0
        assert scratch_names(cfg) == before
        assert maintenance._counts(cfg, cfg.db_name) == expected
