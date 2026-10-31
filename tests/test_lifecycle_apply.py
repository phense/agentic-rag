"""RAG-066 T066-004: audited apply/correct gateway, replay, conflicts, concurrency and
all-or-nothing failure behavior. Rows are compared before/after to prove that the
overlay never rewrites originals, evidence, edges or pins."""
import threading

import psycopg
import pytest

from agentic_rag import db, lifecycle, store
from agentic_rag.benchmark import memory_lifecycle as fx

pytestmark = pytest.mark.usefixtures('conn')
LABELS = fx.load('labels.json')
ORIGINAL_TABLES = ('documents', 'chunks', 'claim_records', 'claim_evidence', 'knowledge_sources', 'edges', 'pins',
                   'fact_assertions', 'assertion_sources', 'source_revisions', 'claim_revisions')


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)


@pytest.fixture
def ids(conn, cfg):
    return fx.ingest(conn, cfg)


def snapshot_rows(conn):
    return {t: conn.execute(f'SELECT md5(COALESCE(string_agg(md5(to_jsonb(x)::text),\',\' ORDER BY md5(to_jsonb(x)::text)),\'\')) h'
                            f' FROM {t} x').fetchone()['h'] for t in ORIGINAL_TABLES}


def lifecycle_counts(conn):
    return dict(conn.execute("SELECT (SELECT count(*) FROM lifecycle_decisions) decisions,"
                             " (SELECT count(*) FROM lifecycle_events) events,"
                             " (SELECT count(*) FROM audit_log WHERE op LIKE 'lifecycle%%') audit").fetchone())


def current(conn, doc):
    return conn.execute('SELECT assertion_eligible(%s) ok', (doc,)).fetchone()['ok']


def apply(cfg, ids, member, target, operation, *, reason='synthetic review', reviewed=None, versions=None,
          request_key=None, role='writer'):
    with db.connect(cfg, role=role) as c:
        seen = versions or lifecycle.preview(c, ids[member], ids[target], operation=operation)
        c.rollback()
        reviewed = operation not in ('exact_duplicate', 'contradiction') if reviewed is None else reviewed
        return store.apply_lifecycle(c, cfg, member=ids[member], target=ids[target], operation=operation,
                                     expected_member_version=seen['member']['version'],
                                     expected_target_version=seen['target']['version'], reason=reason,
                                     reviewed=reviewed, request_key=request_key, actor='cli')


def error(fn, *args, **kwargs):
    with pytest.raises(lifecycle.LifecycleError) as raised:
        fn(*args, **kwargs)
    return raised.value.code


def test_exact_apply_is_atomic_audited_and_source_preserving(conn, cfg, ids):
    ev1 = {k: conn.execute('SELECT rag_document_version(%s) v', (v,)).fetchone()['v'] for k, v in ids.items()}
    rows = snapshot_rows(conn)
    conn.commit()
    result = apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate')
    assert result['decision']['state'] == 'active' and result['decision']['proof'] == 'exact' and not result['replayed']
    assert lifecycle_counts(conn) == {'decisions': 1, 'events': 1, 'audit': 1}
    assert snapshot_rows(conn) == rows
    assert {k: conn.execute('SELECT rag_document_version(%s) v', (v,)).fetchone()['v'] for k, v in ids.items()} == ev1
    assert not current(conn, ids['E1-copy']) and current(conn, ids['E1-keep'])
    audit = conn.execute("SELECT actor,document_id FROM audit_log WHERE op='lifecycle_apply'").fetchone()
    assert str(audit['document_id']) == ids['E1-copy']


def test_semantic_operations_require_explicit_review_and_reason(conn, cfg, ids):
    assert error(apply, cfg, ids, 'R1-short', 'R1-rich', 'extension', reviewed=False) == 'review_required'
    assert error(apply, cfg, ids, 'R1-short', 'R1-rich', 'extension', reason='  ') == 'invalid_arguments'
    assert lifecycle_counts(conn) == {'decisions': 0, 'events': 0, 'audit': 0}
    assert apply(cfg, ids, 'R1-short', 'R1-rich', 'extension')['decision']['proof'] == 'judgement'


@pytest.mark.parametrize('member,target,operation,code', [
    ('T1-beta', 'T1-alpha', 'exact_duplicate', 'proof_failed'),
    ('E1-keep', 'E1-copy', 'exact_duplicate', 'proof_failed'),
    ('P3-a', 'P3-b', 'replacement', 'event_order_unproven'),
    ('P4-a', 'P4-b', 'replacement', 'event_order_unproven'),
    ('P5-now', 'P5-future', 'replacement', 'event_order_unproven'),
    ('P2-newer', 'P2-older-late', 'replacement', 'event_order_unproven'),
    ('S1-b', 'S1-a', 'semantic_duplicate', 'scope_mismatch'),
    ('S3-y', 'S3-x', 'semantic_duplicate', 'unknown_scope'),
    ('A1-v1', 'A1-v2', 'replacement', 'assertion_managed'),
    ('Q1-inferred', 'Q1-stated', 'semantic_duplicate', 'not_current'),
])
def test_unjustified_operations_fail_closed_without_rows(conn, cfg, ids, member, target, operation, code):
    with db.connect(cfg, role='writer') as w:
        versions = {k: {'version': w.execute('SELECT rag_lifecycle_version(%s) v', (ids[d],)).fetchone()['v']}
                    for k, d in (('member', member), ('target', target))}
    assert error(apply, cfg, ids, member, target, operation, versions=versions) == code
    assert lifecycle_counts(conn) == {'decisions': 0, 'events': 0, 'audit': 0}


def test_replay_returns_the_same_decision_and_mismatch_is_refused(conn, cfg, ids):
    with db.connect(cfg, role='reader') as r:
        seen = lifecycle.preview(r, ids['E1-copy'], ids['E1-keep'])
    first = apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', versions=seen, request_key='client-1')
    # Same semantic action, new transport identity: same decision, nothing written.
    again = apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', versions=seen, request_key='client-2')
    plain = apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', versions=seen)
    assert again['decision']['id'] == plain['decision']['id'] == first['decision']['id']
    assert again['replayed'] and plain['replayed']
    assert lifecycle_counts(conn) == {'decisions': 1, 'events': 1, 'audit': 1}
    # A known request key with another payload is a replay mismatch.
    assert error(apply, cfg, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', request_key='client-1') == 'replay_mismatch'
    assert error(apply, cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', versions=seen, reason='other reason',
                 request_key='client-1') == 'replay_mismatch'
    assert lifecycle_counts(conn) == {'decisions': 1, 'events': 1, 'audit': 1}


def test_edit_after_preview_and_action_aba_are_stale(conn, cfg, ids):
    with db.connect(cfg, role='reader') as r:
        seen = lifecycle.preview(r, ids['D1-copy'], ids['D1-keep'])
    store.save_document(conn, cfg, doc_id=ids['D1-copy'], title='Plotter paper size', body='The plotter is loaded with A0 rolls.',
                        domain='general', dtype='memory')  # same text, new updated_at
    assert error(apply, cfg, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', versions=seen) == 'stale_version'
    # Apply then correct: the earlier inspected versions cannot start a second decision.
    with db.connect(cfg, role='reader') as r:
        seen = lifecycle.preview(r, ids['D1-copy'], ids['D1-keep'])
    made = apply(cfg, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', versions=seen, reason='aba')
    with db.connect(cfg) as w:
        store.correct_lifecycle(w, cfg, decision_id=made['decision']['id'], expected_revision=1, reason='undo', actor='cli')
    replay = apply(cfg, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', versions=seen, reason='aba')
    assert replay['replayed'] and replay['decision']['state'] == 'corrected'
    assert error(apply, cfg, ids, 'D1-copy', 'D1-keep', 'exact_duplicate', versions=seen, reason='new attempt') == 'stale_version'
    assert current(conn, ids['D1-copy'])


def test_flat_groups_siblings_and_chain_attempts(conn, cfg, ids):
    apply(cfg, ids, 'M1-copy1', 'M1-canon', 'exact_duplicate')
    apply(cfg, ids, 'M1-copy2', 'M1-canon', 'exact_duplicate')
    for chain in LABELS['cases']['M1']['chains']:
        assert error(apply, cfg, ids, chain['member'], chain['target'], chain['operation']) == chain['code']
    assert error(apply, cfg, ids, 'M1-copy1', 'M1-canon', 'exact_duplicate', reason='second decision') == 'already_active'
    visible = {k for k in ('M1-canon', 'M1-copy1', 'M1-copy2', 'M1-copy3') if current(conn, ids[k])}
    assert visible == set(LABELS['cases']['M1']['views']['current'])
    with db.connect(cfg, role='reader') as r:
        detail = lifecycle.detail(r, ids['M1-canon'])
    assert sorted(m['relationship'] for m in detail['as_canonical']['members']) == ['hiding', 'hiding']


def test_contradiction_is_recorded_and_hides_nothing(conn, cfg, ids):
    made = apply(cfg, ids, 'C1-a', 'C1-b', 'contradiction', reason='conflicting DNS statements')
    assert made['decision']['state'] == 'contested'
    assert current(conn, ids['C1-a']) and current(conn, ids['C1-b'])
    from agentic_rag import curation
    review = curation.review_report(conn, cfg)
    assert [d['id'] for d in review['lifecycle_review']] == [made['decision']['id']]


def test_opposing_concurrent_applies_yield_one_active_decision(conn, cfg, ids):
    for left, right in (('R2-p2', 'R2-p3'), ('T1-alpha', 'T1-beta'), ('T3-a', 'T3-b')):
        barrier = threading.Barrier(2)
        outcomes = []

        def run(member, target):
            try:
                with db.connect(cfg, role='writer') as c:
                    seen = lifecycle.preview(c, ids[member], ids[target], operation='semantic_duplicate')
                    c.rollback()
                    barrier.wait()
                    store.apply_lifecycle(c, cfg, member=ids[member], target=ids[target], operation='semantic_duplicate',
                                          expected_member_version=seen['member']['version'],
                                          expected_target_version=seen['target']['version'], reason='race',
                                          reviewed=True, actor='cli')
                    outcomes.append('ok')
            except lifecycle.LifecycleError as exc:
                outcomes.append(exc.code)
        threads = [threading.Thread(target=run, args=pair) for pair in ((left, right), (right, left))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert outcomes.count('ok') == 1 and len(outcomes) == 2
        assert set(outcomes) - {'ok'} <= {'chain_conflict', 'stale_version'}
    assert conn.execute("SELECT count(*) n FROM lifecycle_decisions WHERE state='active'").fetchone()['n'] == 3


def test_injected_audit_failure_and_lock_timeout_leave_nothing(conn, cfg, ids, monkeypatch):
    def broken(*args, **kwargs):
        raise psycopg.errors.InsufficientPrivilege('audit unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, '_audit', broken)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate')
    assert lifecycle_counts(conn) == {'decisions': 0, 'events': 0, 'audit': 0}
    conn.commit()
    with db.connect(cfg) as holder:
        holder.execute('SELECT 1 FROM documents WHERE id=%s FOR UPDATE', (ids['E1-keep'],))
        assert error(apply, cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate') == 'busy'
        holder.rollback()
    assert lifecycle_counts(conn) == {'decisions': 0, 'events': 0, 'audit': 0}
    assert apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate')['decision']['state'] == 'active'


def test_correction_releases_only_its_own_decision_and_never_revives_truth(conn, cfg, ids):
    a = apply(cfg, ids, 'M1-copy1', 'M1-canon', 'exact_duplicate')
    b = apply(cfg, ids, 'M1-copy2', 'M1-canon', 'exact_duplicate')
    x = apply(cfg, ids, 'X1-short', 'X1-rich', 'extension')
    with db.connect(cfg) as w:
        assert error(store.correct_lifecycle, w, cfg, decision_id=a['decision']['id'], expected_revision=2,
                     reason='wrong revision', actor='cli') == 'stale_version'
        done = store.correct_lifecycle(w, cfg, decision_id=a['decision']['id'], expected_revision=1, reason='mistake', actor='cli')
        same = store.correct_lifecycle(w, cfg, decision_id=a['decision']['id'], expected_revision=1, reason='mistake', actor='cli')
        assert done['decision']['state'] == 'corrected' and same['replayed'] and same['decision']['id'] == done['decision']['id']
        assert error(store.correct_lifecycle, w, cfg, decision_id=a['decision']['id'], expected_revision=2,
                     reason='again', actor='cli') == 'stale_version'
    states = {r['id']: r['state'] for r in conn.execute('SELECT id::text,state FROM lifecycle_decisions')}
    assert states == {a['decision']['id']: 'corrected', b['decision']['id']: 'active', x['decision']['id']: 'active'}
    assert current(conn, ids['M1-copy1']) and not current(conn, ids['M1-copy2'])
    # A member refuted independently stays excluded after its decision is corrected.
    store.review_claim(conn, ids['X1-short'], state='refuted', reason='independent refutation')
    with db.connect(cfg) as w:
        store.correct_lifecycle(w, cfg, decision_id=x['decision']['id'], expected_revision=1, reason='undo', actor='cli')
    assert not current(conn, ids['X1-short'])
    assert conn.execute('SELECT review_state FROM claim_records WHERE document_id=%s', (ids['X1-short'],)).fetchone()['review_state'] == 'refuted'
    assert lifecycle_counts(conn) == {'decisions': 3, 'events': 5, 'audit': 5}


def test_reader_cannot_write_and_missing_decision_is_not_found(conn, cfg, ids):
    with pytest.raises((lifecycle.LifecycleError, psycopg.Error)):
        apply(cfg, ids, 'E1-copy', 'E1-keep', 'exact_duplicate', role='reader')
    import uuid
    with db.connect(cfg) as w:
        assert error(store.correct_lifecycle, w, cfg, decision_id=str(uuid.uuid4()), expected_revision=1,
                     reason='x', actor='cli') == 'not_found'
    assert lifecycle_counts(conn) == {'decisions': 0, 'events': 0, 'audit': 0}
