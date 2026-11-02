"""Real reader/gateway regressions for Issue69, no inference provider."""
import json
import pytest

from agentic_rag import store, domains
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
        return search(conn, cfg, seed.doc_id, **{**options, 'strategy':'auto'})
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
    assert max(p['hop'] for e in result['evidence'] for p in e.get('paths', []) if p['kind']=='graph') == 3
    assert result['abstained']  # Literal excerpts never prove semantic completeness.


def test_confirmed_alias_reuses_existing_identity_and_original_facts(conn, cfg):
    # Catches missing entity expansion or inferred/non-source-backed equivalence.
    domains.add_domain(conn, 'general')
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


def test_unrelated_bridge_is_route_evidence_not_literal_facet_support(conn,cfg):
    target=claim(conn,cfg,'beacon-target','Beacon recovery replaces the socket.')
    bridge=claim(conn,cfg,'routing-note','An unrelated routing note with no question terms.',
        edges=[store.EdgeSpec('references',target.slug,'original recovery pointer','high')])
    seed=claim(conn,cfg,'beacon-start','Beacon initial incident.',
        edges=[store.EdgeSpec('references',bridge.slug,'original routing pointer','high')])
    result=_research(conn,cfg,'Beacon recovery',project=PROJECT,strategy='lexical',retrieve=seeded(seed),
                     budget=ResearchBudget(steps=1))
    assert target.doc_id in {e['document_id'] for e in result['evidence']}
    bridge_citations={e['citation'] for e in result['evidence'] if e['document_id']==bridge.doc_id}
    assert bridge_citations
    assert not bridge_citations.intersection(c for s in result['supported'] for c in s['citations'])


def test_hop_cap_cannot_walk_a_fourth_edge(conn,cfg):
    fourth=claim(conn,cfg,'beacon-fourth','Beacon fourth hop must stay outside this path.')
    third=claim(conn,cfg,'beacon-third','Beacon third hop original.',edges=[store.EdgeSpec('references',fourth.slug,'fourth relation','high')])
    second=claim(conn,cfg,'beacon-second','Beacon second hop original.',edges=[store.EdgeSpec('references',third.slug,'third relation','high')])
    first=claim(conn,cfg,'beacon-first','Beacon first hop original.',edges=[store.EdgeSpec('references',second.slug,'second relation','high')])
    seed=claim(conn,cfg,'beacon-zero','Beacon seed original.',edges=[store.EdgeSpec('references',first.slug,'first relation','high')])
    result=_research(conn,cfg,'Beacon',project=PROJECT,strategy='lexical',retrieve=seeded(seed))
    assert third.doc_id in {e['document_id'] for e in result['evidence']}
    assert fourth.doc_id not in json.dumps(result)


@pytest.mark.parametrize('boundary',['project','domain','source'])
def test_hidden_bridge_does_not_leak_downstream_ids_or_counts(conn,cfg,boundary):
    from agentic_rag import evidence
    target=claim(conn,cfg,'beacon-secret-target','Beacon downstream inaccessible original.')
    bridge=claim(conn,cfg,'beacon-secret-bridge','Beacon hidden bridge original.',
        project='/projects/beta' if boundary=='project' else PROJECT,
        domain='sysadmin' if boundary=='domain' else 'programming',
        source_ids=('bridge-one','bridge-two'),
        edges=[store.EdgeSpec('references',target.slug,'hidden downstream proof','high')])
    seed=claim(conn,cfg,'beacon-public-seed','Beacon initial visible original.',
        edges=[store.EdgeSpec('references',bridge.slug,'hidden bridge proof','high')])
    if boundary=='source':
        for row in conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',(bridge.doc_id,)).fetchall():
            evidence.source_state(conn,row['source_key'],state='removed',reason='synthetic withdrawal')
    result=_research(conn,cfg,'Beacon',project=PROJECT,domain='programming',strategy='lexical',retrieve=seeded(seed))
    assert bridge.doc_id not in json.dumps(result)
    assert target.doc_id not in json.dumps(result)
    assert not any(d['kind']=='graph' and d.get('evidence_ids') for d in result['decisions'])


def test_sql_work_cap_is_enforced_inside_one_logical_search(conn,cfg):
    def expensive(conn,cfg,query,**options):
        for _ in range(500):
            conn.execute('SELECT 1')
        return [],[]
    result=_research(conn,cfg,'unknown',retrieve=expensive,strategy='lexical')
    assert result['termination']=='sql_budget'
    assert result['exploration']['sql_statements']==384
    assert result['usage']['search_calls']==1
    assert result['abstained']
    assert conn.execute('SELECT 2 n').fetchone()['n']==2


def test_shorter_sql_timeouts_survive_optional_failure_and_retry(conn,cfg):
    conn.execute("SET LOCAL statement_timeout='35ms'; SET LOCAL lock_timeout='20ms'")
    def stalled(conn,cfg,query,**options):
        conn.execute('SELECT pg_sleep(0.2)')
        return [],[]
    result=_research(conn,cfg,'what unknown?',retrieve=stalled,strategy='lexical')
    assert result['termination']=='repeated_failure'
    assert 'QueryCanceled' in json.dumps(result['warnings'])
    assert conn.execute('SHOW statement_timeout').fetchone()['statement_timeout']=='35ms'
    assert conn.execute('SHOW lock_timeout').fetchone()['lock_timeout']=='20ms'
    conn.execute("SET LOCAL statement_timeout='0'; SET LOCAL lock_timeout='0'")
    assert _research(conn,cfg,'unknown',strategy='lexical')['termination']!='worker_failure'


def test_graph_failure_returns_original_evidence_and_no_private_diagnostics(conn,cfg,monkeypatch):
    seed=claim(conn,cfg,'beacon-original','Beacon original independently supported.')
    def unavailable(*args,**kwargs):
        raise RuntimeError('private-sql-and-content')
    monkeypatch.setattr('agentic_rag.graph.research_neighbors',unavailable)
    result=_research(conn,cfg,'Beacon',project=PROJECT,strategy='lexical',retrieve=seeded(seed))
    assert seed.doc_id in {e['document_id'] for e in result['evidence']}
    assert result['abstained'] and result['warnings']
    assert 'private-sql-and-content' not in json.dumps(result)
    assert_originals(conn,result)


def test_real_rls_subprocess_keeps_authority_and_writes_no_rows(conn,cfg):
    from agentic_rag import db
    from agentic_rag.research import research
    from agentic_rag.service.auth import Principal
    from agentic_rag.service.context import request_scope
    allowed=claim(conn,cfg,'beacon-owned','Beacon owned original evidence.')
    hidden=claim(conn,cfg,'beacon-foreign','Beacon foreign original evidence.',project='/projects/beta')
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    who=Principal('reader','synthetic','research',frozenset({'programming'}),frozenset(),
                  frozenset({PROJECT}),frozenset())
    with request_scope(who,cfg,read_only=True):
        result=research(cfg,'Beacon',strategy='lexical')
    assert result['termination']!='worker_failure',result
    assert allowed.doc_id in {e['document_id'] for e in result['evidence']}
    assert hidden.doc_id not in json.dumps(result)
    assert result['coverage'] and result['decisions']
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before
    assert_originals(conn,result)


def test_ambiguous_entity_values_do_not_expand_or_invent_an_answer(conn,cfg):
    domains.add_domain(conn,'general')
    for name,number in [('orion','8766'),('orion-old','9000')]:
        saved=store.save_assertion(conn,cfg,entity=name,attribute='port',value=number,
            domain='general',project=PROJECT,event_at='2026-01-01T00:00:00Z',
            evidence={'namespace':'ambiguous-research','source_id':name,'role':'user',
                      'quote':f'{name} port {number}','complete':True})
        assert saved.disposition=='accepted'
    store.save_entity_alias(conn,cfg,alias='orion-old',target='orion',domain='general',
        project=PROJECT,effective_at='2026-02-01T00:00:00Z',confirm=True,
        evidence={'namespace':'ambiguous-research','source_id':'alias','role':'user',
                  'quote':'orion-old is another name for orion.','complete':True})
    from agentic_rag.entities import read
    assert read(conn,'orion-old',domain='general',project=PROJECT)['status']=='ambiguous'
    result=_research(conn,cfg,'orion-old port',project=PROJECT,domain='general',strategy='lexical')
    assert result['abstained'] and not result['supported']
    assert not any(p['kind']=='entity' for e in result['evidence'] for p in e['paths'])
    assert any(d['kind']=='entity' and d['status']=='unavailable_or_ambiguous' for d in result['decisions'])
