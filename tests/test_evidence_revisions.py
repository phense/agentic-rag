"""RAG-063 S1: portable evidence revisions and append-only scoped history."""
import psycopg
import pytest

from agentic_rag import db, evidence, store
from agentic_rag.domains import seed_defaults


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def source(identity='event1', role='user', quote='Server uses TLS.'):
    return {'source_id': identity, 'namespace': 'session:test', 'role': role, 'quote': quote,
            'complete': True, 'timestamp': '2026-01-01T00:00:00Z'}


def claim(conn, cfg, src=None, kind='stated', body='Server uses TLS.'):
    return store.save_claim(conn, cfg, title='TLS', body=body, domain='general', dtype='memory',
                            project='/synthetic/a', claim_kind=kind, evidence=[src or source()])


def revision(conn, table, column, key):
    row = conn.execute(f'SELECT revision FROM {table} WHERE {column}=%s', (key,)).fetchone()
    return row['revision'] if row else 1


def test_baseline_is_storage_revision_one_without_rewriting_originals(conn, cfg):
    one = claim(conn, cfg)
    key = evidence.sources(conn, one.doc_id)[0]['source_key']
    # No revision rows are fabricated: absence is the documented storage baseline.
    assert conn.execute('SELECT count(*) n FROM source_revisions').fetchone()['n'] == 0
    assert revision(conn, 'source_revisions', 'source_key', key) == 1
    assert conn.execute('SELECT count(*) n FROM source_history').fetchone()['n'] == 0


def test_withdraw_reinstate_advances_source_revision_and_history(conn, cfg):
    one = claim(conn, cfg)
    key = evidence.sources(conn, one.doc_id)[0]['source_key']
    store.set_source_state(conn, key, state='removed', reason='withdrawn', actor='alice')
    store.set_source_state(conn, key, state='active', reason='revalidated', actor='bob')
    # Same visible state as before, but never the same revision (ABA prevention).
    assert revision(conn, 'source_revisions', 'source_key', key) == 3
    rows = conn.execute('SELECT revision,operation,state,reason,actor,concurrency,inspected_version'
                        ' FROM source_history WHERE source_key=%s ORDER BY revision', (key,)).fetchall()
    assert [(r['revision'], r['state'], r['actor'], r['concurrency'], r['inspected_version']) for r in rows] == [
        (2, 'removed', 'alice', 'legacy', None), (3, 'active', 'bob', 'legacy', None)]
    assert {r['operation'] for r in rows} == {'source_state'}


def test_claim_review_and_attach_advance_claim_revision(conn, cfg):
    one = claim(conn, cfg, source(role='assistant'), kind='inference')
    first = revision(conn, 'claim_revisions', 'document_id', one.doc_id)
    store.review_claim(conn, one.doc_id, state='confirmed', reason='checked', actor='alice')
    store.review_claim(conn, one.doc_id, state='unreviewed', reason='again', actor='alice')
    store.review_claim(conn, one.doc_id, state='confirmed', reason='checked', actor='alice')
    after_reviews = revision(conn, 'claim_revisions', 'document_id', one.doc_id)
    assert after_reviews > first
    claim(conn, cfg, source('event2', 'assistant', 'more'), kind='inference')
    assert revision(conn, 'claim_revisions', 'document_id', one.doc_id) > after_reviews
    ops = [r['operation'] for r in conn.execute(
        'SELECT operation FROM claim_history WHERE document_id=%s ORDER BY revision', (one.doc_id,))]
    assert ops.count('review') == 3 and ops[-1] == 'attach'
    attach = conn.execute("SELECT * FROM claim_history WHERE document_id=%s AND operation='attach'"
                          " ORDER BY revision DESC LIMIT 1", (one.doc_id,)).fetchone()
    assert attach['source_key'] and attach['span_hash'] and attach['concurrency'] == 'legacy'


def test_direct_sql_change_is_recorded_as_direct_not_as_inspected(conn, cfg):
    one = claim(conn, cfg)
    key = evidence.sources(conn, one.doc_id)[0]['source_key']
    conn.execute("UPDATE knowledge_sources SET state='refuted',reason='manual SQL' WHERE source_key=%s", (key,))
    row = conn.execute('SELECT concurrency,inspected_version,revision FROM source_history WHERE source_key=%s', (key,)).fetchone()
    assert row == {'concurrency': 'direct', 'inspected_version': None, 'revision': 2}


def test_history_is_append_only_and_limited_roles_cannot_forge(conn, cfg):
    one = claim(conn, cfg)
    key = evidence.sources(conn, one.doc_id)[0]['source_key']
    store.set_source_state(conn, key, state='refuted', reason='corrected')
    with pytest.raises(psycopg.Error):
        conn.execute("UPDATE source_history SET reason='rewritten'")
    conn.rollback()
    with pytest.raises(psycopg.Error):
        conn.execute('DELETE FROM claim_history')
    conn.rollback()
    for role in ('reader', 'writer'):
        with db.connect(cfg, role=role) as limited:
            for statement in ("INSERT INTO source_revisions(source_key,revision) VALUES ('x',99)",
                              'UPDATE claim_revisions SET revision=1',
                              "INSERT INTO source_history(source_key,revision,operation,actor,concurrency) VALUES ('x',9,'source_state','x','strict')"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    limited.execute(statement)
                limited.rollback()
            assert limited.execute('SELECT count(*) n FROM source_history').fetchone()['n'] == 1


def test_failed_gateway_transaction_leaves_no_revision_or_history(conn, cfg):
    one = claim(conn, cfg)
    key = evidence.sources(conn, one.doc_id)[0]['source_key']
    conn.execute("CREATE FUNCTION pg_temp.fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'audit down'; END$$")
    conn.execute('CREATE TRIGGER fail_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_audit()')
    conn.commit()
    try:
        with pytest.raises(psycopg.Error):
            store.set_source_state(conn, key, state='removed', reason='will fail')
        with pytest.raises(psycopg.Error):
            store.review_claim(conn, one.doc_id, state='refuted', reason='will fail')
    finally:
        conn.execute('DROP TRIGGER fail_audit ON audit_log')
        conn.commit()
    assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()['state'] == 'active'
    assert conn.execute('SELECT count(*) n FROM source_history').fetchone()['n'] == 0
    assert conn.execute('SELECT count(*) n FROM claim_history WHERE operation=%s', ('review',)).fetchone()['n'] == 0
    assert revision(conn, 'source_revisions', 'source_key', key) == 1


def test_supported_source_version_includes_current_release():
    from agentic_rag.service import upgrade
    assert '0.6.15' in upgrade.SUPPORTED_VERSIONS
    assert '0.6.16' in upgrade.SUPPORTED_VERSIONS
    # RAG-065: the actual 0.6.17 release is an accepted source for 0.6.18.
    assert '0.6.17' in upgrade.SUPPORTED_VERSIONS
    # RAG-066: 0.6.18 became an accepted source for 0.6.19.
    assert '0.6.18' in upgrade.SUPPORTED_VERSIONS
    # RAG-067: the previous and current releases support verified backups; future versions are refused.
    assert '0.6.19' in upgrade.SUPPORTED_VERSIONS
    assert '0.6.20' in upgrade.SUPPORTED_VERSIONS
    assert '0.6.21' not in upgrade.SUPPORTED_VERSIONS
