"""RAG-065 T065-004: a pattern is exposed only while every recorded original and
policy is current. Covers ordinary/history search, direct get, evidence
drill-down, pattern tools, dashboard browse and later confirmation, plus
structural anti-recursion. Providers are scripted; nothing leaves the process.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import time

import psycopg
import pytest

from agentic_rag import llm, search, store, worker
from agentic_rag import evidence_contract as contract
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.domains import add_domain, seed_defaults


@pytest.fixture
def env(conn, cfg, monkeypatch):
    from agentic_rag import synthesis
    monkeypatch.setattr(synthesis, 'SETTLE_SECONDS', 0)
    monkeypatch.setattr('agentic_rag.store.try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a, **k: None)
    seed_defaults(conn)
    add_domain(conn, 'alpha')
    conn.commit()
    return replace(cfg, synthesis_enabled=True, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')


class AllSupport:
    """Cites every offered candidate as supporting one suggestion."""
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt, schema, cfg, **kwargs):
        self.calls += 1
        ids = [c['id'] for c in fx.candidates_from_prompt(prompt)][:8]
        return {'suggestions': [{'label': 'Recurring cause across reports', 'statement': 'A recurring cause appears.',
                                 'confidence': 'low', 'parts': [{'text': 'Reported repeatedly.',
                                 'citations': [{'id': i, 'stance': 'supports'} for i in ids]}]}],
                'non_conclusions': []}


def apply_k1(conn, env, monkeypatch, *, confirm=True):
    from agentic_rag import synthesis
    monkeypatch.setattr(llm, 'run_structured', fx.ScriptedProvider('K1'))
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='t', project=fx.project('K1'))
    keys = fx.ingest(conn, env, {'K1'})
    synthesis.schedule(conn, env)
    worker.drain(conn, env)
    pattern = str(conn.execute('SELECT document_id FROM synthesis_patterns').fetchone()['document_id'])
    conn.commit()
    if confirm:
        store.review_claim(conn, pattern, state='confirmed', reason='operator checked the cited originals')
    return keys, pattern


def found(conn, env, pattern, *, history=False):
    hits, _ = search.search(conn, env, 'DNS suffix VPN reconnect pattern', domain='general', k=50,
                            project=fx.project('K1'), history=history, strategy='lexical', rerank_mode='off',
                            context_mode='off')
    conn.rollback()
    return pattern in {h.document_id for h in hits}


def exposed(conn, env, pattern):
    from agentic_rag import synthesis
    row = conn.execute('SELECT claim_eligible(%s) c,assertion_eligible(%s,now(),true) h,rag_pattern_current(%s) p',
                       (pattern, pattern, pattern)).fetchone()
    conn.rollback()
    listed = [p['id'] for p in synthesis.patterns(conn, env, domain='general', project=fx.project('K1'))['items']]
    get = store.get_document(conn, pattern) is not None
    try:
        contract.inspect(conn, pattern)
        evidence = True
    except contract.EvidenceUnavailable:
        evidence = False
    try:
        contract.history(conn, pattern)
        history = True
    except contract.EvidenceUnavailable:
        history = False
    try:
        synthesis.inspect(conn, pattern)
        inspected = True
    except contract.EvidenceUnavailable:
        inspected = False
    conn.rollback()
    return {'claim_eligible': row['c'], 'history_eligible': row['h'], 'current': row['p'],
            'search': found(conn, env, pattern), 'history_search': found(conn, env, pattern, history=True),
            'listed': pattern in listed, 'get': get, 'evidence': evidence, 'evidence_history': history,
            'inspect': inspected}


VISIBLE = dict.fromkeys(['claim_eligible', 'history_eligible', 'current', 'search', 'history_search', 'listed', 'get',
                         'evidence', 'evidence_history', 'inspect'], True)
WITHHELD = dict.fromkeys(VISIBLE, False)


def source_of(conn, document_id):
    key = contract.inspect(conn, document_id)['sources']['items'][0]['source_key']
    conn.commit()
    return key


def mutate_source_refuted(conn, env, keys):
    store.set_source_state(conn, source_of(conn, keys['k1-b']), state='refuted', reason='wrong machine')


def mutate_withdraw_reinstate(conn, env, keys):
    key = source_of(conn, keys['k1-c'])
    store.set_source_state(conn, key, state='removed', reason='withdrawn')
    store.set_source_state(conn, key, state='active', reason='reinstated')


def mutate_original_refuted(conn, env, keys):
    store.review_claim(conn, keys['k1-a'], state='refuted', reason='not what happened')


def mutate_original_moved(conn, env, keys):
    store.set_domain(conn, keys['k1-d'], 'alpha')


def mutate_new_span(conn, env, keys):
    doc = store.get_document(conn, keys['k1-d'])
    store.save_claim(conn, env, title=doc['title'], body=doc['body'], domain='general', dtype='memory',
                     project=fx.project('K1'), claim_kind='stated',
                     evidence=[{'namespace': 'session:late', 'source_id': 'late-1', 'role': 'user',
                                'quote': 'Late corroborating quote.', 'complete': True}])


@pytest.mark.parametrize('mutation', [mutate_source_refuted, mutate_withdraw_reinstate, mutate_original_refuted,
                                      mutate_original_moved, mutate_new_span])
def test_any_original_change_withholds_a_confirmed_pattern_everywhere(conn, env, monkeypatch, mutation):
    keys, pattern = apply_k1(conn, env, monkeypatch)
    assert exposed(conn, env, pattern) == VISIBLE
    before = {k: store.get_document(conn, v)['body'] for k, v in keys.items()}
    conn.rollback()
    mutation(conn, env, keys)
    assert exposed(conn, env, pattern) == WITHHELD
    # A later confirmation does not bypass the dependency guard.
    store.review_claim(conn, pattern, state='confirmed', reason='confirm again after the change')
    assert exposed(conn, env, pattern) == WITHHELD
    # Originals and their history stay; the pattern row itself is retained.
    assert {k: store.get_document(conn, v)['body'] for k, v in keys.items()} == before
    assert conn.execute('SELECT count(*) n FROM synthesis_patterns').fetchone()['n'] == 1
    conn.rollback()


def test_unreviewed_pattern_is_inspectable_but_never_ordinary_or_history_retrieval(conn, env, monkeypatch):
    from agentic_rag import synthesis
    keys, pattern = apply_k1(conn, env, monkeypatch, confirm=False)
    state = exposed(conn, env, pattern)
    assert state == {**VISIBLE, 'claim_eligible': False, 'history_eligible': False, 'search': False,
                     'history_search': False}
    view = synthesis.inspect(conn, pattern)
    assert view['kind'] == 'inference' and view['review_state'] == 'unreviewed' and view['current'] is True
    assert view['verification'] == {'independent': False} and view['support'] == {'events': 4, 'memories': 4}
    refs = {c['reference'] for p in view['parts'] for c in p['citations']}
    originals = {c['original']['id'] for p in view['parts'] for c in p['citations']}
    assert originals == set(keys.values()) and len(refs) == 4
    for part in view['parts']:
        for c in part['citations']:
            assert c['original']['version'] == contract.document_version(conn, c['original']['id'])
            drill = contract.inspect(conn, c['original']['id'], source_key=c['reference'].split('#')[0])
            assert any(i['reference'] == c['reference'] for i in drill['sources']['items'])
    text = repr(view)
    assert 'session:' not in text and 'evt-' not in text
    notices = contract.inspect(conn, pattern)['eligibility']['notices']
    assert 'derived_pattern' in notices
    conn.rollback()


def test_policy_disable_withholds_and_reenable_restores_unchanged_patterns(conn, env, monkeypatch):
    keys, pattern = apply_k1(conn, env, monkeypatch)
    store.set_synthesis_policy(conn, env, domain='general', enabled=False, reason='stop', project=fx.project('K1'))
    assert exposed(conn, env, pattern) == WITHHELD
    assert all(store.get_document(conn, v) for v in keys.values())
    conn.rollback()
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='resume', project=fx.project('K1'))
    assert exposed(conn, env, pattern) == VISIBLE


def test_refuted_pattern_is_not_listed_or_retrieved(conn, env, monkeypatch):
    from agentic_rag import synthesis
    keys, pattern = apply_k1(conn, env, monkeypatch)
    store.review_claim(conn, pattern, state='refuted', reason='operator rejected the suggestion')
    assert pattern not in [p['id'] for p in synthesis.patterns(conn, env, domain='general', project=fx.project('K1'))['items']]
    assert not found(conn, env, pattern) and not found(conn, env, pattern, history=True)


def test_time_only_expiry_and_supersession_withhold_without_any_write(conn, env, monkeypatch):
    from agentic_rag import synthesis
    provider = AllSupport()
    monkeypatch.setattr(llm, 'run_structured', provider)
    project = '/synthetic/expiry'
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='t', project=project)
    now = datetime.now(timezone.utc)
    ids = {}
    for i, (entity, expires) in enumerate([('gateway-a', now + timedelta(seconds=4)), ('gateway-b', None),
                                           ('gateway-c', None)]):
        saved = store.save_assertion(conn, env, entity=entity, attribute='failure', value=f'fan stall {i}',
                                     event_at=(now - timedelta(hours=i + 1)).isoformat(), domain='general',
                                     project=project, expires_at=expires.isoformat() if expires else None,
                                     evidence={'namespace': f'session:x{i}', 'source_id': f'x{i}', 'role': 'user',
                                               'quote': f'The {entity} fan stall {i} recurred this week.'})
        ids[entity] = saved.doc_id
    synthesis.schedule(conn, env)
    worker.drain(conn, env)
    pattern = str(conn.execute('SELECT document_id FROM synthesis_patterns').fetchone()['document_id'])
    conn.commit()
    store.review_claim(conn, pattern, state='confirmed', reason='checked')
    assert conn.execute('SELECT claim_eligible(%s) ok', (pattern,)).fetchone()['ok']
    conn.rollback()
    before = conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    conn.rollback()
    time.sleep(max(0.0, (now + timedelta(seconds=4.5) - datetime.now(timezone.utc)).total_seconds()))
    assert not conn.execute('SELECT claim_eligible(%s) ok', (pattern,)).fetchone()['ok']
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n'] == before
    conn.rollback()
    with pytest.raises(contract.EvidenceUnavailable):
        synthesis.inspect(conn, pattern)
    conn.rollback()
    assert provider.calls == 1


def test_supersession_of_an_original_withholds(conn, env, monkeypatch):
    from agentic_rag import synthesis
    monkeypatch.setattr(llm, 'run_structured', AllSupport())
    project = '/synthetic/supersession'
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='t', project=project)
    now = datetime.now(timezone.utc)
    for i, entity in enumerate(['relay-a', 'relay-b', 'relay-c']):
        store.save_assertion(conn, env, entity=entity, attribute='queue', value=f'stuck {i}',
                             event_at=(now - timedelta(days=2, hours=i)).isoformat(), domain='general', project=project,
                             evidence={'namespace': f'session:s{i}', 'source_id': f's{i}', 'role': 'user',
                                       'quote': f'The {entity} queue was stuck {i} again.'})
    synthesis.schedule(conn, env)
    worker.drain(conn, env)
    pattern = str(conn.execute('SELECT document_id FROM synthesis_patterns').fetchone()['document_id'])
    conn.commit()
    store.review_claim(conn, pattern, state='confirmed', reason='checked')
    assert conn.execute('SELECT claim_eligible(%s) ok', (pattern,)).fetchone()['ok']
    conn.rollback()
    store.save_assertion(conn, env, entity='relay-b', attribute='queue', value='drained', relation='replacement',
                         event_at=(now - timedelta(hours=1)).isoformat(), domain='general', project=project,
                         evidence={'namespace': 'session:s9', 'source_id': 's9', 'role': 'user',
                                   'quote': 'The relay-b queue is drained now.'})
    assert not conn.execute('SELECT claim_eligible(%s) ok', (pattern,)).fetchone()['ok']
    conn.rollback()


def test_patterns_never_feed_synthesis_and_dependencies_are_structurally_original_only(conn, env, monkeypatch):
    from agentic_rag import synthesis
    keys, pattern = apply_k1(conn, env, monkeypatch)
    view = synthesis.preview(conn, env, domain='general', project=fx.project('K1'))
    assert view['excluded']['derived'] == 1 and view['candidates']['memories'] == 4
    assert pattern not in {r['document_id'] for r in view['references']}
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation, match='pattern_dependency_must_be_original'):
        conn.execute("INSERT INTO synthesis_dependencies SELECT %s,%s,original_version,source_key,span_hash,source_version"
                     " FROM synthesis_dependencies LIMIT 1", (pattern, pattern))
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation, match='pattern_must_be_new_synthesis_document'):
        conn.execute("INSERT INTO synthesis_patterns(document_id,application_key,policy_id,run_id,label,statement,"
                     "confidence,parts,dependency_count,events,memories,applied_by) SELECT %s,repeat('a',64),policy_id,"
                     "run_id,label,statement,confidence,parts,dependency_count,events,memories,'t' FROM synthesis_patterns",
                     (keys['k1-a'],))
    conn.rollback()


def test_dashboard_browse_omits_withheld_patterns(conn, env, monkeypatch):
    from agentic_rag.service import dashboard_views
    from agentic_rag.service.auth import Principal
    keys, pattern = apply_k1(conn, env, monkeypatch)
    everyone = frozenset({'*'})
    reader = Principal('operator', None, 'op', everyone, frozenset(), everyone, frozenset())
    query = {'domain': 'general', 'project': fx.project('K1'), 'limit': '50'}
    listed = {str(r['id']) for r in dashboard_views.browse(env, reader, query)['documents']}
    assert pattern in listed and set(keys.values()) <= listed
    store.set_synthesis_policy(conn, env, domain='general', enabled=False, reason='stop', project=fx.project('K1'))
    page = dashboard_views.browse(env, reader, query)
    listed = {str(r['id']) for r in page['documents']}
    assert pattern not in listed and set(keys.values()) <= listed and page['total'] == len(keys)
