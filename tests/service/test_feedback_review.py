"""Review regressions on owned PostgreSQL: coherent results and private ACLs."""
from dataclasses import replace
import uuid

import psycopg
from psycopg import sql
import pytest

from agentic_rag import db, feedback, query_cache, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.context import CURRENT, request_scope
from agentic_rag.service.queued_transaction import GROUP
from agentic_rag.service.schema import validate_schema
from .test_scope import principal, service_store


@pytest.fixture
def review_store(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(query_cache, 'model_digest', lambda *a, **k: None)
    with isolated_database(Config(feedback_enabled=True)) as cfg:
        with db.connect(cfg) as conn:
            saved = store.save_document(conn, cfg, title='Snapshot racing memory',
                body='Uniqueprobe071 original visible snippet', domain='general', dtype='memory', project='/p')
        yield cfg, saved.doc_id


def racing_search(monkeypatch, cfg, document_id, *, domain='general', project='/p'):
    from agentic_rag import search
    original = search.search
    def interleave(conn, config, *args, **kwargs):
        hits, warnings = original(conn, config, *args, **kwargs)
        assert hits and 'original visible' in hits[0].snippet
        # Commit a real audited canonical write on another connection, outside
        # the scoped/queued caller. Only the deterministic interleaving is fake.
        scope, group = CURRENT.set(None), GROUP.set(None)
        try:
            with db.connect(cfg) as writer:
                store.save_document(writer, cfg, title='Snapshot racing memory changed',
                    body='Uniqueprobe071 replacement content', domain=domain, dtype='memory',
                    project=project, doc_id=document_id)
        finally:
            GROUP.reset(group)
            CURRENT.reset(scope)
        return hits, warnings
    monkeypatch.setattr(search, 'search', interleave)


def test_returned_content_and_retained_version_share_one_snapshot(review_store, monkeypatch):
    # Mutation caught: READ COMMITTED search followed by a later version read.
    cfg, document_id = review_store
    with db.connect(cfg) as conn:
        before = feedback.document_snapshot(conn, document_id)['version']
    racing_search(monkeypatch, cfg, document_id)
    p = replace(principal(), read_domains=frozenset({'general'}), write_domains=frozenset({'general'}),
                read_projects=frozenset({'/p'}), write_projects=frozenset({'/p'}))
    with request_scope(p, cfg):
        with db.connect(cfg, role='writer') as conn:
            captured = feedback.capture(conn, cfg, query='Uniqueprobe071', domain='general', project='/p',
                                        idempotency_key=str(uuid.uuid4()), k=1)
        with db.connect(cfg, role='reader') as conn:
            current = feedback.document_snapshot(conn, document_id)['version']
            retained = feedback.get(conn, cfg, event_id=captured['event']['id'])
    assert current != before
    assert 'original visible' in captured['results'][0]['snippet']
    assert captured['event']['results'][0]['version'] == before
    assert retained['stale'] is True


@pytest.fixture
def acl_roles():
    roles = ['feedback_acl_' + uuid.uuid4().hex[:12] for _ in range(2)]
    with psycopg.connect(db.dsn(Config(), dbname='postgres'), autocommit=True) as conn:
        for role in roles:
            conn.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT {} TO {}').format(*map(sql.Identifier, roles)))
        try:
            yield roles
        finally:
            for role in reversed(roles):
                conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_037_strips_custom_default_grants_from_all_feedback_tables(acl_roles, tmp_path):
    # Mutation caught: revoking only fixed roles leaves unrelated inherited ACLs.
    group, member = acl_roles
    with isolated_database(Config(), initialize=False) as cfg:
        prefix = tmp_path/'036'; prefix.mkdir()
        for file in sorted(db.SQL_DIR.glob('*.sql'))[:36]:
            (prefix/file.name).write_bytes(file.read_bytes())
        with db.connect(cfg) as conn:
            db.apply_migrations(conn, prefix)
            old_acl = conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl']
            conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE ON TABLES TO {}').format(sql.Identifier(group)))
            conn.commit()
            assert db.apply_migrations(conn, db.SQL_DIR) == ['037_retrieval_feedback.sql']
            for table in ('retrieval_feedback_events', 'retrieval_feedback', 'retrieval_feedback_usage', 'retrieval_feedback_approvals'):
                for role in (group, member):
                    assert not conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') exposed", (role, table)).fetchone()['exposed'], (role, table)
            validate_schema(conn)
            assert conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl'] == old_acl


@pytest.mark.parametrize('exposure', ['column_group', 'owner_membership', 'limited_owner'])
def test_private_operator_refuses_later_registry_exposure(acl_roles, review_store, tmp_path, exposure):
    # Mutation caught: owner login alone is insufficient when others can read it.
    from agentic_rag.benchmark import feedback as private, corrections
    cfg, document_id = review_store
    query = 'privately reconstructed query'
    with db.connect(cfg, role='writer') as conn:
        event = feedback.capture(conn, cfg, query=query, domain='general', project='/p', idempotency_key=str(uuid.uuid4()))
        record = feedback.submit(conn, cfg, event_id=event['event']['id'], kind='missing_evidence',
                                 expected_id=document_id, idempotency_key=str(uuid.uuid4()))
    private.approve(cfg, feedback_id=record['id'], expected_revision=1, query=query)
    export = tmp_path/'healthy.json'
    private.export_feedback(cfg, domain='general', project='/p', output_path=export)
    group, member = acl_roles
    with db.connect(cfg) as conn:
        owner = conn.execute('SELECT current_user name').fetchone()['name']
        if exposure == 'column_group':
            conn.execute(sql.SQL('GRANT SELECT(query) ON retrieval_feedback_approvals TO {}').format(sql.Identifier(group)))
            assert conn.execute("SELECT has_column_privilege(%s,'retrieval_feedback_approvals','query','SELECT') exposed", (member,)).fetchone()['exposed']
        elif exposure == 'owner_membership':
            conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(owner), sql.Identifier(member)))
            assert conn.execute("SELECT pg_has_role(%s,%s,'MEMBER') exposed", (member, owner)).fetchone()['exposed']
        else:
            conn.execute('ALTER TABLE retrieval_feedback_approvals OWNER TO rag_reader')
            assert conn.execute("SELECT has_table_privilege('rag_reader','retrieval_feedback_approvals','SELECT') exposed").fetchone()['exposed']
        conn.commit()
    try:
        operations = [
            lambda: private.approve(cfg, feedback_id=record['id'], expected_revision=1, query=query),
            lambda: private.summary(cfg, domain='general', project='/p'),
            lambda: private.export_feedback(cfg, domain='general', project='/p', output_path=tmp_path/'refused.json'),
            lambda: corrections.evaluate_export(cfg, export_path=export, output_path=tmp_path/'refused-report.json'),
        ]
        for operation in operations:
            with pytest.raises(ValueError, match='operator_.*(exposed|owner_required)'):
                operation()
        assert not (tmp_path/'refused.json').exists() and not (tmp_path/'refused-report.json').exists()
    finally:
        if exposure == 'owner_membership':
            with db.connect(cfg) as conn:
                conn.execute(sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(owner), sql.Identifier(member)))


def test_temporal_upgrade_inventory_and_old_reader_on_owned_database(tmp_path, monkeypatch):
    # Run the existing contract without requesting its shared cfg/conn fixtures.
    from .test_temporal_upgrade import test_populated_old_store_new_reads_and_actual_old_code_rollback
    with isolated_database(Config()) as cfg:
        with db.connect(cfg) as conn:
            test_populated_old_store_new_reads_and_actual_old_code_rollback(conn, cfg, tmp_path, monkeypatch)


def test_queued_capture_snapshot_replay_and_origin_remain_atomic(service_store, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from agentic_rag.service.client import RemoteClient
    from .test_api import app_fixture
    from .test_client import client_config
    cfg, documents = service_store
    cfg = replace(cfg, feedback_enabled=True)
    document_id = documents['allowed']
    with db.connect(cfg) as conn:
        store.save_document(conn, cfg, title='Snapshot racing memory',
            body='Uniqueprobe071 original visible snippet', domain='alpha', dtype='memory',
            project='/projects/a', doc_id=document_id)
        before = feedback.document_snapshot(conn, document_id)['version']
    racing_search(monkeypatch, cfg, document_id, domain='alpha', project='/projects/a')
    app, _ = app_fixture(tmp_path, cfg)
    remote = client_config(tmp_path, cfg)
    arguments = dict(query='Uniqueprobe071', domain='alpha', project='/projects/a',
                     idempotency_key=str(uuid.uuid4()), k=1)
    with TestClient(app, base_url='https://testserver') as sender, RemoteClient(remote, sender=sender) as client:
        captured = client.invoke('memory_feedback_search', arguments, seconds=15)
        assert captured.get('event'), captured
        assert client.queued_tools and 'original visible' in captured['results'][0]['snippet']
        assert captured['event']['results'][0]['version'] == before
        replay = client.invoke('memory_feedback_search', arguments, seconds=15)
        assert replay['event']['id'] == captured['event']['id'] and replay['event']['stale'] is True
        assert replay['results'] == [] and client.spool.pending_requests() == []
    with db.connect(cfg) as conn:
        event = conn.execute('SELECT * FROM retrieval_feedback_events WHERE id=%s', (captured['event']['id'],)).fetchone()
        requests = conn.execute("SELECT * FROM service_requests WHERE tool='memory_feedback_search' AND result->'event'->>'id'=%s ORDER BY created_at", (captured['event']['id'],)).fetchall()
        assert len(requests) == 2 and all(r['state'] == 'completed' and r['arguments'] is None for r in requests)
        assert event['origin_request_id'] is not None and event['origin_request_id'] == requests[0]['origin_request_id']
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='feedback_capture' AND summary=%s", (captured['event']['id'],)).fetchone()['n'] == 1
