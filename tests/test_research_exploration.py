"""Real reader/gateway regressions for Issue69, no inference provider."""
import json
import pytest

from agentic_rag import store
from agentic_rag.research import ResearchBudget, _research
from agentic_rag.search import search
from tests.test_research import claim

PROJECT = '/projects/alpha'


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def seeded(seed):
    # Narrow only the initial retrieval. Graph, SQL, eligibility and citations stay real.
    def retrieve(conn, cfg, query, **options):
        return search(conn, cfg, seed.doc_id, **options)
    return retrieve


def assert_originals(conn, result):
    for item in result['evidence']:
        row = conn.execute('SELECT content FROM chunks WHERE id=%s', (item['chunk_id'],)).fetchone()
        assert row['content'][item['start']:item['end']] == item['text']


def test_three_hop_frontier_reaches_original_without_revisiting_cycles(conn, cfg):
    # Catches fixed first-three-seed traversal and exhaustion after corrective queries.
    end = claim(conn, cfg, 'beacon-final', 'Beacon final resolution replaces the stale socket.')
    middle = claim(conn, cfg, 'beacon-middle', 'Beacon middle links the final resolution.',
                   edges=[store.EdgeSpec('references', end.slug, 'verified final source', 'high')])
    bridge = claim(conn, cfg, 'beacon-bridge', 'Beacon bridge links the middle source.',
                   edges=[store.EdgeSpec('references', middle.slug, 'verified middle source', 'high')])
    seed = claim(conn, cfg, 'beacon-seed', 'Beacon initial incident requires a resolution.',
                 edges=[store.EdgeSpec('references', bridge.slug, 'verified bridge source', 'high')])
    result = _research(conn, cfg, 'Beacon resolution', project=PROJECT, domain='programming',
                       strategy='lexical', retrieve=seeded(seed), budget=ResearchBudget(steps=1))
    assert end.doc_id in {e['document_id'] for e in result['evidence']}
    assert_originals(conn, result)
    traversals = [d for d in result['decisions'] if d['kind'] == 'graph']
    assert len({d['seed_document_id'] for d in traversals}) == len(traversals)
    assert max(p['hop'] for e in result['evidence'] for p in e.get('paths', [])) == 3
    assert result['abstained']  # Literal excerpts never prove semantic completeness.


def test_confirmed_alias_reuses_existing_identity_and_original_facts(conn, cfg):
    # Catches missing entity expansion or inferred/non-source-backed equivalence.
    fact = store.save_assertion(conn, cfg, entity='orion', attribute='port', value='8766',
        event_at='2026-01-01T00:00:00Z', domain='general', project=PROJECT,
        evidence={'namespace':'research-entities', 'source_id':'port', 'role':'user',
                  'quote':'orion port is now 8766', 'complete':True})
    alias = store.save_entity_alias(conn, cfg, alias='orion-old', target='orion',
        domain='general', project=PROJECT, effective_at='2026-02-01T00:00:00Z', confirm=True,
        evidence={'namespace':'research-entities', 'source_id':'alias', 'role':'user',
                  'quote':'orion-old is another name for orion.', 'complete':True})
    assert alias['state'] == 'accepted'
    result = _research(conn, cfg, 'orion-old port', project=PROJECT, domain='general', strategy='lexical')
    assert fact.doc_id in {e['document_id'] for e in result['evidence']}
    paths = [p for e in result['evidence'] if e['document_id']==fact.doc_id for p in e.get('paths', [])]
    assert any(p['kind']=='entity' and alias['document_id'] in p['alias_document_ids'] for p in paths)
    assert_originals(conn, result)
    assert result['abstained'] and result['usage']['provider_calls'] == 0


def test_facets_separate_literal_support_from_semantic_coverage(conn, cfg):
    claim(conn, cfg, 'beacon-supported', 'Beacon storage uses PostgreSQL.')
    result = _research(conn, cfg, 'Beacon storage? Missing rollback procedure?',
                       project=PROJECT, strategy='lexical')
    assert result['plan']['facets'] == result['questions']
    assert len(result['coverage']) == 2
    assert result['coverage'][0]['literal_supported'] is True
    assert result['coverage'][0]['semantic_covered'] is False
    assert result['coverage'][1]['literal_supported'] is False
    assert result['coverage'][1]['semantic_covered'] is False
    assert result['exploration']['sql_statements'] <= result['exploration']['limits']['sql_statements']


def test_high_degree_is_visible_and_all_work_stays_bounded(conn, cfg):
    targets = [claim(conn,cfg,f'beacon-{i:02}',f'Beacon resolution original number {i}.') for i in range(11)]
    seed = claim(conn,cfg,'beacon-root','Beacon incident resolution.', edges=[
        store.EdgeSpec('references', t.slug, 'bounded original relation', 'high') for t in targets])
    result = _research(conn,cfg,'Beacon resolution',project=PROJECT,strategy='lexical',
                       retrieve=seeded(seed),budget=ResearchBudget(steps=1,calls=4))
    assert result['exploration']['truncated'] is True
    assert result['usage']['calls'] <= 4
    assert result['exploration']['documents'] <= 24
    assert result['exploration']['sql_statements'] <= 384
    assert len(result['evidence']) <= 9
