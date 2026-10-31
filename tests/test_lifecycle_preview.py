"""RAG-066 T066-003: bounded read-only preview and five-way classification against the
frozen hand labels. Preview never writes and never calls a provider."""
import pytest

from agentic_rag import db, llm, store
from agentic_rag import lifecycle
from agentic_rag.benchmark import memory_lifecycle as fx

pytestmark = pytest.mark.usefixtures('conn')
LABELS = fx.load('labels.json')['cases']


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)

    def forbidden(*a, **k):
        raise AssertionError('preview must not call a provider')
    monkeypatch.setattr(llm, 'run_structured', forbidden)


@pytest.fixture
def ids(conn, cfg):
    return fx.ingest(conn, cfg)


def counts(conn):
    return conn.execute("SELECT (SELECT count(*) FROM lifecycle_decisions) d, (SELECT count(*) FROM lifecycle_events) e,"
                        " (SELECT count(*) FROM audit_log) a").fetchone()


def preview(cfg, ids, member, target, operation=None):
    with db.connect(cfg, role='reader') as reader:
        try:
            return lifecycle.preview(reader, ids[member], ids[target], operation=operation)
        except lifecycle.LifecycleError as error:
            return {'error': error.code}


@pytest.mark.parametrize('case', [c for c, v in LABELS.items() if 'preview' in v])
def test_preview_matches_frozen_label(conn, cfg, ids, case):
    label = LABELS[case]
    member, target = label['pair']
    before = counts(conn)
    result = preview(cfg, ids, member, target, label['preview'].get('requested'))
    conn.commit()
    assert counts(conn) == before
    if 'code' in label['preview']:
        assert result == {'error': label['preview']['code']}
        return
    assert result['proof'] == label['preview']['proof']
    assert result['classification'] == label['preview']['class']
    assert result['writes'] == 0 and result['provider_calls'] == 0
    assert result['member']['id'] == ids[member] and result['target']['id'] == ids[target]
    assert result['member']['version'].startswith('lv1:') and result['target']['version'].startswith('lv1:')
    if 'differs' in label['preview']:
        assert result['exact']['differs'] == label['preview']['differs']
    if 'approval' in label['preview']:
        assert result['operations'][result['classification']]['approval'] == label['preview']['approval']
    if 'effective_at' in label['preview']:
        assert result['event_order']['effective_at'] == label['preview']['effective_at']
    # The response separates structural proof from operator judgement.
    assert 'not proven' in result['statement'] or result['proof'] == 'exact'


@pytest.mark.parametrize('case,key', [('E1', 'reverse'), ('T1', 'exact_request'), ('T2', 'exact_request'),
                                      ('T3', 'exact_request'), ('P2', 'reverse')])
def test_requested_operation_that_fails_its_proof_is_reported(cfg, ids, case, key):
    label = LABELS[case]
    member, target = label['pair'] if key != 'reverse' else label['pair'][::-1]
    result = preview(cfg, ids, member, target, label[key]['requested'])
    assert result['operations'][label[key]['requested']] == {**result['operations'][label[key]['requested']],
                                                              'allowed': False, 'code': label[key]['code']}
    assert result['classification'] == 'review_required'


@pytest.mark.parametrize('case', ['P3', 'P4', 'P5'])
def test_unproven_event_order_cannot_classify_replacement(cfg, ids, case):
    label = LABELS[case]
    result = preview(cfg, ids, *label['pair'], 'replacement')
    assert result['operations']['replacement']['code'] == label['replacement']['code']


def test_semantic_preview_does_not_infer_equivalence(cfg, ids):
    # Without a requested operation only an exact proof is classified; the rest is review.
    for case in ('R1', 'R2', 'T1', 'C1', 'P1'):
        result = preview(cfg, ids, *LABELS[case]['pair'])
        assert result['classification'] == 'review_required' and result['proof'] == 'none'


def test_missing_foreign_and_invisible_anchors_are_indistinguishable(conn, cfg, ids):
    import uuid
    from agentic_rag.service.auth import Principal
    from agentic_rag.service.context import request_scope
    missing = str(uuid.uuid4())
    with db.connect(cfg, role='reader') as reader:
        with pytest.raises(lifecycle.LifecycleError) as one:
            lifecycle.preview(reader, missing, ids['E1-keep'])
        with pytest.raises(lifecycle.LifecycleError) as two:
            lifecycle.preview(reader, ids['E1-copy'], missing)
    principal = Principal('reader-b', 'vm1', 'one', frozenset({'general'}), frozenset(),
                          frozenset({'/synthetic/lifecycle-b'}), frozenset())
    with request_scope(principal, cfg, read_only=True), db.connect(cfg, role='reader') as scoped:
        with pytest.raises(lifecycle.LifecycleError) as foreign:
            lifecycle.preview(scoped, ids['E1-copy'], ids['E1-keep'])
        with pytest.raises(lifecycle.LifecycleError) as half:
            lifecycle.preview(scoped, ids['S1-b'], ids['S1-a'])
    assert {one.value.code, two.value.code, foreign.value.code, half.value.code} == {'not_found'}
    assert str(one.value) == str(two.value) == str(foreign.value) == str(half.value)


def test_preview_source_refs_are_bounded(conn, cfg):
    fx.ingest(conn, cfg, set())  # domains only
    evidence = [{'namespace': 'session:bound', 'source_id': f's{n}', 'role': 'user', 'quote': f'Quote {n}',
                 'timestamp': f'2026-01-{n + 1:02d}T00:00:00Z', 'complete': True} for n in range(8)]
    a = store.save_claim(conn, cfg, title='Bounded', body='Bounded claim body.', domain='general', dtype='memory',
                         project='/synthetic/lifecycle-a', claim_kind='stated', evidence=evidence)
    b = store.save_claim(conn, cfg, title='Bounded later', body='Bounded later claim body.', domain='general', dtype='memory',
                         project='/synthetic/lifecycle-a', claim_kind='stated', evidence=evidence[:1])
    store.save_claim(conn, cfg, title='Bounded', body='Bounded claim body.', domain='general', dtype='memory',
                     project='/synthetic/lifecycle-a', claim_kind='stated',
                     evidence=[{**evidence[0], 'source_id': 'extra', 'timestamp': '2026-02-01T00:00:00Z'}])
    conn.commit()
    result = lifecycle.preview(conn, a.doc_id, b.doc_id, operation='semantic_duplicate')
    assert len(result['member']['sources']) == 8 and result['member']['sources_omitted'] == 1
