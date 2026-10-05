"""Populated018/019 migration, retry and recovery without historical rewrites."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from agentic_rag import db, search, store, validity
from agentic_rag.continuity import store as checkpoints
from agentic_rag.continuity.model import CheckpointSnapshot
from scripts.verify_contextual_indexing import snapshot, verified_backup
from scripts.diagnose_domain_assertions import report
from test_maintenance_restore import owned_source

PROJECT = '/synthetic/domain-upgrade'


def legacy_module(tmp_path):
    path = Path(__file__).parent / 'fixtures/domain_assertions_source_019.py'
    spec = importlib.util.spec_from_file_location('agentic_rag._domain_source_validity', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def put(conn, cfg, domain, value, when, **kwargs):
    return store.save_assertion(conn, cfg, entity='Original server', attribute='status', value=value,
        domain=domain, project=PROJECT, event_at=when,
        evidence={'source_id':domain+when, 'role':'user', 'quote':'server status '+value}, **kwargs)


def tables(conn):
    return [r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]


def privileges(conn):
    return conn.execute("SELECT grantee,table_name,privilege_type,is_grantable FROM information_schema.table_privileges "
                        "WHERE table_schema='public' ORDER BY grantee,table_name,privilege_type,is_grantable").fetchall()


@pytest.mark.parametrize('schema', [18, 19])
def test_populated_upgrade_strict_backup_interruption_retry_and_read_only_recovery(tmp_path, schema, monkeypatch):
    old = legacy_module(tmp_path)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)
    with owned_source(tmp_path, schema) as cfg:
        with db.connect(cfg) as conn:
            with patch.object(validity, 'save', old.save):
                programming = put(conn, cfg, 'programming', 'stopped', '2026-01-01T00:00:00Z')
                general = put(conn, cfg, 'general', 'stopped', '2026-01-02T00:00:00Z')
                put(conn, cfg, 'general', 'running', '2026-02-01T00:00:00Z', relation='replacement')
            guarded = []
            for kind, identity in [('proposal', 'proposal'), ('stated', 'withdrawn')]:
                claim = store.save_claim(conn, cfg, title='Public TLS '+identity,
                    body='Public server uses TLS '+identity, domain='general', dtype='memory', project=PROJECT,
                    claim_kind=kind, evidence=[{'source_id':identity, 'namespace':'guard-tests', 'role':'user',
                                             'quote':'Public server uses TLS '+identity, 'complete':True}])
                if identity == 'withdrawn':
                    source_key = store.get_document(conn, claim.doc_id)['claim_sources'][0]['source_key']
                    store.set_source_state(conn, source_key, state='removed', reason='public withdrawal rehearsal')
                guarded.append(claim.doc_id)
                assert conn.execute('SELECT assertion_eligible(%s) eligible', (claim.doc_id,)).fetchone()['eligible'] is False
            checkpoints.upsert_snapshot(conn, CheckpointSnapshot(session_id='public-upgrade', cursor='one', source='codex', turn_id=None, trigger='manual', cwd=PROJECT, project_root=PROJECT))
            assert conn.execute('SELECT assertion_eligible(%s) eligible', (programming.doc_id,)).fetchone()['eligible'] is False
            preserved_tables = [t for t in tables(conn) if t != 'schema_migrations']
            original = snapshot(conn, preserved_tables)
            original_grants = privileges(conn)
            migrations = conn.execute('SELECT * FROM schema_migrations ORDER BY filename').fetchall()
            function_acl = conn.execute("SELECT oid,proowner,proacl FROM pg_proc WHERE oid='assertion_eligible(uuid,timestamptz,boolean)'::regprocedure").fetchone()
            mixed = conn.execute('SELECT count(*) n FROM edges e JOIN documents s ON s.id=e.src_id JOIN documents d ON d.id=e.dst_id '
                                 "WHERE e.predicate='supersedes' AND s.domain<>d.domain").fetchone()['n']
            assert mixed == 1
            conn.rollback()
        assert report(cfg)['cross_domain_temporal_edges'] == 1
        # Exported source snapshot, strict owned restore, full row and role-grant comparison.
        backup = verified_backup(cfg, tmp_path / 'strict-source.dump')
        assert backup['all_public_table_rows_match'] and backup['application_table_privileges_match']
        with db.connect(cfg) as conn:
            conn.execute((db.SQL_DIR / '020_domain_assertions.sql').read_text())
            assert conn.execute('SELECT assertion_eligible(%s) eligible', (programming.doc_id,)).fetchone()['eligible'] is True
            conn.rollback()  # Interrupted DDL is safely retryable.
            assert conn.execute('SELECT assertion_eligible(%s) eligible', (programming.doc_id,)).fetchone()['eligible'] is False
            applied = db.apply_migrations(conn, db.SQL_DIR)
            assert applied == (['019_embedding_reuse.sql'] if schema == 18 else []) + ['020_domain_assertions.sql']
            assert db.apply_migrations(conn, db.SQL_DIR) == []
            assert snapshot(conn, preserved_tables) == original
            assert [r for r in privileges(conn) if r['table_name'] in preserved_tables + ['schema_migrations']] == original_grants
            assert all(row in conn.execute('SELECT * FROM schema_migrations').fetchall() for row in migrations)
            assert conn.execute("SELECT oid,proowner,proacl FROM pg_proc WHERE oid='assertion_eligible(uuid,timestamptz,boolean)'::regprocedure").fetchone() == function_acl
            assert conn.execute('SELECT assertion_eligible(%s) eligible', (programming.doc_id,)).fetchone()['eligible'] is True
            assert conn.execute('SELECT assertion_eligible(%s) eligible', (general.doc_id,)).fetchone()['eligible'] is False
            for claim_id in guarded:
                assert conn.execute('SELECT assertion_eligible(%s) eligible', (claim_id,)).fetchone()['eligible'] is False
                assert conn.execute('SELECT assertion_eligible(%s,now(),true) eligible', (claim_id,)).fetchone()['eligible'] is True
            conn.rollback()
        # Old and new reader contract reaches the same corrected shared function.
        with db.connect(cfg, role='reader') as reader:
            hits = reader.execute('SELECT document_id FROM hybrid_search(%s,NULL,%s,8)', ('server', 'programming')).fetchall()
            assert str(hits[0]['document_id']) == programming.doc_id
            assert search.search(reader, cfg, 'server', domain='programming', project=PROJECT, strategy='lexical')[0][0].document_id == programming.doc_id
            with pytest.raises(__import__('psycopg').errors.InsufficientPrivilege):
                reader.execute('UPDATE fact_assertions SET value=%s', ('changed',))
        assert report(cfg)['cross_domain_temporal_edges'] == 1
        assert report(cfg)['history_rewritten'] is False
        # Candidate code rollback is read-only with020 retained; historical writes are paused.
        with db.connect(cfg) as conn:
            assert snapshot(conn, preserved_tables) == original
            put(conn, cfg, 'programming', 'recovering', '2026-03-01T00:00:00Z', relation='replacement', commit=False)
            conn.rollback()
            assert snapshot(conn, preserved_tables) == original
