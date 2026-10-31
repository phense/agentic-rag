"""RAG-063: scoped revisions/history under service RLS and fail-closed schema checks."""
import psycopg
import pytest

from agentic_rag import db, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope
from agentic_rag.service.schema import ServiceSchemaError, validate_schema


def alice(*, readonly=False):
    return Principal('alice', 'vm1', 'one', frozenset({'alpha'}), frozenset() if readonly else frozenset({'alpha'}),
                     frozenset({'/projects/a'}), frozenset() if readonly else frozenset({'/projects/a'}))


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (domain,))
            shared_source = {'namespace': 'session:shared', 'source_id': 'event-1', 'role': 'user',
                             'quote': 'Shared synthetic statement', 'complete': True}
            own = store.save_claim(conn, owned, title='own', body='Own synthetic claim', domain='alpha', dtype='memory',
                                   project='/projects/a', claim_kind='stated', evidence=[shared_source])
            foreign = store.save_claim(conn, owned, title='foreign', body='Foreign synthetic claim', domain='beta',
                                       dtype='memory', project='/projects/b', claim_kind='stated',
                                       evidence=[{**shared_source, 'quote': 'Shared synthetic'},
                                                 {**shared_source, 'source_id': 'event-private', 'quote': 'Private foreign'}])
            key = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s', (own.doc_id,)).fetchone()['source_key']
            private = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s AND source_key<>%s',
                                   (foreign.doc_id, key)).fetchone()['source_key']
            store.set_source_state(conn, private, state='refuted', reason='foreign-only decision')
            store.review_claim(conn, foreign.doc_id, state='refuted', reason='foreign review')
        yield owned, own.doc_id, foreign.doc_id, key, private


def test_service_reader_sees_only_anchored_history_and_revisions(shared):
    cfg, own, foreign, key, private = shared
    with request_scope(alice(readonly=True), cfg, read_only=True):
        with db.connect(cfg, role='reader') as conn:
            assert {r['document_id'] for r in conn.execute('SELECT document_id FROM claim_history')} == {own_uuid(own)}
            assert conn.execute('SELECT count(*) n FROM claim_revisions WHERE document_id=%s', (foreign,)).fetchone()['n'] == 0
            assert conn.execute('SELECT count(*) n FROM source_history WHERE source_key=%s', (private,)).fetchone()['n'] == 0
            assert conn.execute('SELECT count(*) n FROM source_revisions WHERE source_key=%s', (private,)).fetchone()['n'] == 0
    # The owner still sees every row; nothing was hidden by deletion.
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM source_history WHERE source_key=%s', (private,)).fetchone()['n'] == 1


def own_uuid(value):
    import uuid
    return uuid.UUID(value)


def test_shared_source_write_still_requires_every_dependent(shared):
    cfg, own, foreign, key, _ = shared
    with request_scope(alice(), cfg):
        with pytest.raises(ValueError, match='source not found'):
            with db.connect(cfg, role='writer') as conn:
                store.set_source_state(conn, key, state='removed', reason='only one dependent is writable')
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()['state'] == 'active'
        assert conn.execute('SELECT count(*) n FROM source_history WHERE source_key=%s', (key,)).fetchone()['n'] == 0


def test_service_history_actor_is_authenticated_transport_actor(shared):
    cfg, own, *_ = shared
    with request_scope(alice(), cfg):
        with db.connect(cfg, role='writer') as conn:
            store.review_claim(conn, own, state='unreviewed', reason='transport actor', actor='spoofed-actor')
    with db.connect(cfg) as conn:
        row = conn.execute("SELECT actor FROM claim_history WHERE document_id=%s AND operation='review'", (own,)).fetchone()
        assert row['actor'] == 'service:machine:alice:vm1'


@pytest.mark.parametrize('breakage', [
    'GRANT INSERT ON source_history TO rag_writer',
    'GRANT UPDATE ON claim_revisions TO rag_admin',
    'ALTER TABLE claim_history DISABLE ROW LEVEL SECURITY',
    'ALTER TABLE knowledge_sources DISABLE TRIGGER source_revision',
    'DROP TRIGGER claim_evidence_revision ON claim_evidence',
    'GRANT EXECUTE ON FUNCTION rag_lock_claim_source(uuid,text) TO rag_reader',
    'DROP FUNCTION rag_lock_claim_source(uuid,text)',
])
def test_schema_validation_fails_closed_without_revision_protection(shared, breakage):
    cfg, *_ = shared
    with db.connect(cfg) as conn:
        validate_schema(conn)
        conn.execute(breakage)
        with pytest.raises(ServiceSchemaError):
            validate_schema(conn)
        conn.rollback()


def test_revoked_read_scope_hides_evidence_history_and_search(shared, monkeypatch):
    from dataclasses import replace
    from agentic_rag import evidence_contract as contract, search
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a, **k: None)
    cfg, own, foreign, key, _ = shared
    with request_scope(alice(readonly=True), cfg, read_only=True):
        with db.connect(cfg, role='reader') as conn:
            assert contract.inspect(conn, own)['document']['id'] == own
    revoked = replace(alice(readonly=True), read_projects=frozenset({'/projects/other'}))
    with request_scope(revoked, cfg, read_only=True):
        with db.connect(cfg, role='reader') as conn:
            for call in (lambda: contract.inspect(conn, own), lambda: contract.history(conn, own),
                         lambda: contract.history(conn, own, source_key=key)):
                with pytest.raises(contract.EvidenceUnavailable):
                    call()
            hits, _ = search.search(conn, cfg, 'Own synthetic claim', strategy='lexical', rerank_mode='off',
                                    project='/projects/a')
            assert hits == []
            assert conn.execute('SELECT count(*) n FROM claim_history').fetchone()['n'] == 0


def test_strict_review_of_own_claim_can_use_readable_shared_source(shared):
    """Reviewing one's claim does not require write authority over foreign dependents."""
    from agentic_rag import evidence_contract as contract
    cfg, own, foreign, key, _ = shared
    with request_scope(alice(), cfg):
        with db.connect(cfg, role='writer') as conn:
            seen = contract.inspect(conn, own)['version']
            result = store.review_claim(conn, own, state='confirmed', reason='checked my claim', expected_version=seen)
            assert result['review_state'] == 'confirmed'
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT review_state FROM claim_records WHERE document_id=%s', (foreign,)).fetchone()['review_state'] == 'refuted'
        assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s', (key,)).fetchone()['state'] == 'active'
