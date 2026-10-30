"""Scoped retrieval must retain every source/trust gate while avoiding RLS fanout."""
import pytest

from agentic_rag import db, store
from agentic_rag.service.context import request_scope
from tests.service.test_scope import service_store, principal


@pytest.mark.parametrize('kind,role,complete,review,state,expected', [
    ('stated', 'user', True, None, 'active', True),
    ('stated', 'assistant', True, None, 'active', False),
    ('stated', 'user', False, None, 'active', False),
    ('stated', 'user', True, None, 'removed', False),
    ('stated', 'user', True, None, 'refuted', False),
    ('proposal', 'user', True, None, 'active', False),
    ('hypothetical', 'user', True, None, 'active', False),
    ('inference', 'assistant', True, None, 'active', False),
    ('inference', 'assistant', True, 'confirmed', 'active', True),
    ('stated', 'assistant', False, 'confirmed', 'active', True),
    ('stated', 'user', True, 'refuted', 'active', False),
    ('inference', 'assistant', True, 'confirmed', 'removed', False),
])
def test_scoped_eligibility_preserves_source_review_rules(
        service_store, monkeypatch, kind, role, complete, review, state, expected):
    # Mutations: accepting assistant/incomplete/refuted evidence, or ignoring review.
    cfg, _ = service_store
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **kw: None)
    identity = '-'.join(map(str, (kind, role, complete, review, state)))
    with db.connect(cfg) as owner:
        result = store.save_claim(owner, cfg, title=identity, body='Synthetic '+identity,
            domain='alpha', dtype='memory', project='/projects/a', claim_kind=kind,
            evidence=[{'namespace':'test:eligibility', 'source_id':identity, 'role':role,
                       'quote':'Synthetic '+identity, 'complete':complete}])
        if review:
            store.review_claim(owner, result.doc_id, state=review, reason='Synthetic check')
        key = owner.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',
                            (result.doc_id,)).fetchone()['source_key']
        if state != 'active':
            store.set_source_state(owner, key, state=state, reason='Synthetic withdrawal')
    with request_scope(principal(readonly=True), cfg, read_only=True):
        with db.connect(cfg, role='reader') as reader:
            assert reader.execute('SELECT assertion_eligible(%s) ok',
                                  (result.doc_id,)).fetchone()['ok'] is expected
            assert reader.execute('SELECT assertion_eligible(%s,now(),true) ok',
                                  (result.doc_id,)).fetchone()['ok'] is True


def test_scoped_claim_search_skips_bad_source_and_keeps_team_boundary(service_store, monkeypatch):
    # Mutations: returning false on the first unusable source or bypassing document RLS.
    cfg, docs = service_store
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **kw: None)
    with db.connect(cfg) as owner:
        result = store.save_claim(owner, cfg, title='Independent sources',
            body='Synthetic independent sources', domain='alpha', dtype='memory',
            project='/projects/a', claim_kind='stated', evidence=[
                {'namespace':'test:multiple', 'source_id':'bad', 'role':'assistant',
                 'quote':'Synthetic independent sources', 'complete':True},
                {'namespace':'test:multiple', 'source_id':'good', 'role':'user',
                 'quote':'Synthetic independent sources', 'complete':True}])
    with request_scope(principal(readonly=True), cfg, read_only=True):
        with db.connect(cfg, role='reader') as reader:
            assert reader.execute('SELECT claim_eligible(%s) ok',
                                  (result.doc_id,)).fetchone()['ok'] is True
            assert reader.execute('SELECT id FROM documents WHERE id=%s',
                                  (docs['foreign'],)).fetchall() == []
            assert reader.execute('SELECT count(*) n FROM claim_evidence WHERE document_id=%s',
                                  (docs['foreign'],)).fetchone()['n'] == 0
