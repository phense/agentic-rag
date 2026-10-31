"""RAG-063 T063-007: derived readers revalidate canonical eligibility after changes.

Real search, context, profile, thematic, research and entity readers are used;
only the embedding/provider boundary is synthetic (embeddings unavailable).
"""
import pytest

from agentic_rag import context, entities, evidence, profiles, search, store, thematic
from agentic_rag import evidence_contract as contract
from agentic_rag.domains import seed_defaults

PROJECT = '/synthetic/evidence'


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    from agentic_rag.domains import add_domain
    add_domain(conn, 'programming')
    conn.execute('DELETE FROM thematic_summaries')
    conn.execute('DELETE FROM project_profiles')
    conn.commit()
    for module in (store, search):
        monkeypatch.setattr(module, 'try_embed_texts', lambda *a, **k: None)


def statement(conn, cfg, body, *identities, domain='general'):
    return store.save_claim(conn, cfg, title=body[:40], body=body, domain=domain, dtype='memory', project=PROJECT,
                            claim_kind='stated', evidence=[{'namespace': 'session:inv', 'source_id': identity,
                                                            'role': 'user', 'quote': body, 'complete': True,
                                                            'timestamp': '2026-01-01T00:00:00Z'}
                                                           for identity in identities])


def fact(conn, cfg, value, when, *, relation='assertion', expires=None, domain='general'):
    return store.save_assertion(conn, cfg, entity='evidence-service', attribute='port', value=value, domain=domain,
                                event_at=when, expires_at=expires, relation=relation, project=PROJECT,
                                evidence={'source_id': 'port-' + value + domain, 'role': 'user',
                                          'quote': 'evidence-service port ' + value, 'event_at': when})


def lexical(conn, cfg, query):
    hits, _ = search.search(conn, cfg, query, project=PROJECT, strategy='lexical', rerank_mode='off')
    return {h.document_id for h in hits}


def readers(conn, cfg, query, topic='deployment-architecture'):
    """Document IDs each derived reader would currently present."""
    built = context.build(conn, cfg, project=PROJECT, mode='prompt', prompt='How do we deploy ' + query + ' in this project?')
    profile = profiles.read(conn, cfg, PROJECT)
    # The profile refresh builds this default theme with history labels.
    themed = thematic.read(conn, cfg, topic, project=PROJECT, history=True)
    return {
        'search': lexical(conn, cfg, query),
        'context': set(built['document_ids']),
        'profile': {i['id'] for section in profile['sections'].values() for i in section},
        'thematic': {e['document_id'] for e in themed['entries']},
    }


def key_of(conn, doc_id):
    return evidence.sources(conn, doc_id)[0]['source_key']


def test_withdrawal_and_correction_remove_derived_acceptance_without_losing_history(conn, cfg):
    claim = statement(conn, cfg, 'We always use PostgreSQL with pgvector for deployment architecture.', 'pg-1')
    store.refresh_profile(conn, cfg, PROJECT)
    before = readers(conn, cfg, 'PostgreSQL pgvector deployment')
    assert all(claim.doc_id in ids for ids in before.values()), before
    seen = contract.inspect(conn, claim.doc_id)['version']
    store.set_source_state(conn, key_of(conn, claim.doc_id), state='removed', reason='source withdrawn')
    # Caches are stale but must not present the withdrawn claim before a refresh.
    after = readers(conn, cfg, 'PostgreSQL pgvector deployment')
    assert all(claim.doc_id not in ids for ids in after.values()), after
    view = contract.inspect(conn, claim.doc_id)
    assert view['eligibility']['reasons'] == ['no_active_support'] and view['version'] != seen
    assert view['sources']['items'][0]['quote'].startswith('We always use PostgreSQL')
    hits, _ = search.search(conn, cfg, 'PostgreSQL pgvector deployment', project=PROJECT, strategy='lexical',
                            rerank_mode='off', history=True)
    assert claim.doc_id in {h.document_id for h in hits}  # authorized history keeps the original
    # Reinstatement makes it current again under a new version, not the old one.
    store.set_source_state(conn, key_of(conn, claim.doc_id), state='active', reason='revalidated')
    assert claim.doc_id in lexical(conn, cfg, 'PostgreSQL pgvector deployment')
    assert contract.inspect(conn, claim.doc_id)['version'] not in {seen, view['version']}
    # Correction: refute the claim; a corrected claim is a new immutable claim.
    store.review_claim(conn, claim.doc_id, state='refuted', reason='corrected below')
    corrected = statement(conn, cfg, 'We always use PostgreSQL 17 with pgvector for deployment architecture.', 'pg-2')
    store.refresh_profile(conn, cfg, PROJECT)
    final = readers(conn, cfg, 'PostgreSQL pgvector deployment')
    assert all(claim.doc_id not in ids for ids in final.values()), final
    assert corrected.doc_id in final['search'] and corrected.doc_id in final['profile']


def test_supersession_and_expiry_do_not_resurrect_old_values(conn, cfg):
    old = fact(conn, cfg, '8766', '2026-01-01T00:00:00Z')
    new = fact(conn, cfg, '8767', '2026-02-01T00:00:00Z', relation='replacement')
    expired = fact(conn, cfg, '9000', '2026-03-01T00:00:00Z', expires='2026-03-02T00:00:00Z', domain='programming')
    current = lexical(conn, cfg, 'evidence-service port')
    assert new.doc_id in current and old.doc_id not in current and expired.doc_id not in current
    packet = entities.read(conn, 'evidence-service', domain='general', project=PROJECT, attribute='port')
    assert [f['value'] for f in packet['facts']] == ['8767']
    assert contract.inspect(conn, old.doc_id)['eligibility']['reasons'] == ['fact_superseded']
    assert contract.inspect(conn, expired.doc_id)['eligibility']['reasons'] == ['fact_expired']
    # Refuting the newer source withdraws it, but never revives the superseded value.
    store.set_source_state(conn, key_of(conn, new.doc_id), state='refuted', reason='newer source invalid')
    current = lexical(conn, cfg, 'evidence-service port')
    assert old.doc_id not in current and new.doc_id not in current
    packet = entities.read(conn, 'evidence-service', domain='general', project=PROJECT, attribute='port')
    assert '8766' not in [f['value'] for f in packet['facts']]
    assert contract.inspect(conn, old.doc_id)['eligibility']['current'] is False


def test_history_labels_supersession_only_within_the_same_domain(conn, cfg):
    old = fact(conn, cfg, '7001', '2026-01-01T00:00:00Z')
    other = fact(conn, cfg, '7002', '2026-02-01T00:00:00Z', relation='replacement', domain='programming')
    # Domains isolate supersession in the canonical predicate: both stay current.
    current = lexical(conn, cfg, 'evidence-service port')
    assert {old.doc_id, other.doc_id} <= current
    assert contract.inspect(conn, old.doc_id)['lifecycle']['fact']['state'] == 'current'
    store.refresh_summaries(conn, cfg, 'evidence-service port', project=PROJECT, history=True)
    packet = thematic.read(conn, cfg, 'evidence-service port', project=PROJECT, history=True)
    labels = {e['document_id']: e['temporal_status'] for e in packet['entries']}
    assert labels.get(old.doc_id) == 'current', labels


def test_research_and_service_scope_revalidate_before_presentation(conn, cfg, hook_env, monkeypatch):
    from agentic_rag import research
    import json
    claim = statement(conn, cfg, 'Storage uses PostgreSQL with pgvector in evidence research.', 'r-1', 'r-2')
    evidence.review(conn, claim.doc_id, state='confirmed', reason='synthetic fixture sources checked')
    conn.commit()
    options = dict(project=PROJECT, strategy='lexical')
    before = research.research(cfg, 'Storage PostgreSQL pgvector evidence research', **options)
    assert before['supported'] and claim.doc_id in json.dumps(before['supported'])
    for item in evidence.sources(conn, claim.doc_id):
        store.set_source_state(conn, item['source_key'], state='removed', reason='withdrawn')
    conn.commit()
    after = research.research(cfg, 'Storage PostgreSQL pgvector evidence research', **options)
    assert claim.doc_id not in json.dumps(after['supported']) and claim.doc_id not in json.dumps(after['evidence'])
