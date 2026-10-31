"""RAG-063 S2: one versioned evidence representation and audited strict decisions."""
import json
import threading

import psycopg
import pytest

from agentic_rag import db, evidence, store
from agentic_rag import evidence_contract as contract
from agentic_rag.domains import seed_defaults


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def source(identity='event1', role='user', quote='Server uses TLS.', complete=True, timestamp='2026-01-01T00:00:00Z',
           namespace='session:/home/alice/.claude/projects/secret-path.jsonl'):
    return {'source_id': identity, 'namespace': namespace, 'role': role, 'quote': quote,
            'complete': complete, 'timestamp': timestamp}


def claim(conn, cfg, *sources, kind='stated', body='Server uses TLS.'):
    return store.save_claim(conn, cfg, title='TLS', body=body, domain='general', dtype='memory',
                            project='/synthetic/a', claim_kind=kind, evidence=list(sources or [source()]))


def keys(conn, doc):
    return [s['source_key'] for s in evidence.sources(conn, doc)]


def test_envelope_exposes_exact_evidence_without_host_locators(conn, cfg):
    quote = 'Grüße: Ω≈ç√ — exact "quoted" text\nsecond line'
    one = claim(conn, cfg, source(quote=quote, timestamp=None), body=quote)
    view = contract.inspect(conn, one.slug)
    assert view['contract_version'] == 1 and view['version'].startswith('ev1:')
    assert view['document']['id'] == one.doc_id and view['document']['slug'] == one.slug
    item = view['sources']['items'][0]
    assert item['quote'] == quote and item['quote_truncated'] is False
    assert item['source_event_at'] is None and item['event_time'] == 'unknown'
    assert item['role'] == 'user' and item['completeness'] == 'complete' and item['reviewed'] is False
    assert item['origin'] == 'user_source_event' and item['trust']['state'] == 'active'
    assert item['reference'] == item['source_key'] + '#' + item['span_hash']
    assert item['source_version'].startswith('src1:') and item['revision'] == 1
    encoded = json.dumps(view, default=str)
    assert 'secret-path' not in encoded and '/home/alice' not in encoded
    assert 'namespace' not in encoded and 'source_id' not in encoded
    # The claim registry state stays separate from trust, lifecycle and verification.
    assert view['claim']['review_state'] == 'unreviewed' and view['claim']['kind'] == 'stated'
    assert view['claim']['support_basis'] == 'complete_user_statement'
    assert view['verification'] == {'independent': False, 'origin': 'none'}
    assert view['eligibility']['current'] is True and view['eligibility']['reasons'] == []
    assert view['lifecycle']['document_status'] == 'active' and view['lifecycle']['fact'] is None


def test_legacy_manual_assistant_and_partial_are_labeled_not_verified(conn, cfg):
    legacy = store.save_document(conn, cfg, title='old', body='old', domain='general', dtype='memory', mark_verified=True)
    old = contract.inspect(conn, legacy.doc_id)
    assert old['claim'] is None and old['provenance']['registry'] == 'legacy_unmanaged'
    assert old['provenance']['status'] == 'incomplete' and old['sources']['items'] == []
    assert old['verification'] == {'independent': False, 'origin': 'none'}
    assert 'legacy_provenance_unknown' in old['eligibility']['notices']
    manual = store.save_assertion(conn, cfg, entity='server', attribute='port', value='443', domain='general',
                                  event_at='2026-01-01T00:00:00Z', project='/synthetic/a',
                                  evidence={'source_id': 'op-1', 'role': 'user', 'quote': 'port 443'})
    attested = contract.inspect(conn, manual.doc_id)
    assert attested['sources']['items'][0]['origin'] == 'manual_attestation'
    assert attested['verification']['independent'] is False
    assert attested['lifecycle']['fact']['state'] == 'current'
    inference = claim(conn, cfg, source('a1', 'assistant', 'TLS maybe', complete=False), kind='inference', body='TLS inferred')
    view = contract.inspect(conn, inference.doc_id)
    item = view['sources']['items'][0]
    assert item['origin'] == 'assistant_statement' and item['completeness'] == 'partial'
    assert view['eligibility']['current'] is False and view['eligibility']['reasons'] == ['review_required']
    evidence.review(conn, inference.doc_id, state='confirmed', reason='derivation checked')
    view = contract.inspect(conn, inference.doc_id)
    assert view['verification'] == {'independent': False, 'origin': 'operator_review'}
    assert view['claim']['support_basis'] == 'operator_review' and view['eligibility']['current'] is True


def test_exclusion_reasons_follow_canonical_predicates(conn, cfg):
    one = claim(conn, cfg)
    store.set_source_state(conn, keys(conn, one.doc_id)[0], state='removed', reason='withdrawn')
    view = contract.inspect(conn, one.doc_id)
    assert view['eligibility']['current'] is False
    assert view['eligibility']['reasons'] == ['no_active_support']
    assert 'source_withdrawn' in view['eligibility']['notices']
    store.review_claim(conn, one.doc_id, state='refuted', reason='wrong')
    assert contract.inspect(conn, one.doc_id)['eligibility']['reasons'][0] == 'claim_refuted'
    from tests.test_validity import put
    old = put(conn, cfg, '7000')
    put(conn, cfg, '8000', '2026-02-01T00:00:00Z', relation='replacement')
    superseded = contract.inspect(conn, old.doc_id)
    assert superseded['lifecycle']['fact']['state'] == 'superseded'
    assert superseded['eligibility']['reasons'] == ['fact_superseded']
    expired = put(conn, cfg, '9000', '2026-03-01T00:00:00Z', expires_at='2026-03-02T00:00:00Z', project='/synthetic/b')
    assert contract.inspect(conn, expired.doc_id)['eligibility']['reasons'] == ['fact_expired']


def test_version_is_whole_set_stable_and_never_reused(conn, cfg):
    one = claim(conn, cfg, *[source(f'e{i:02d}', quote=f'Server uses TLS {i}.') for i in range(8)])
    claim(conn, cfg, *[source(f'f{i:02d}', quote=f'Server uses TLS f{i}.') for i in range(8)])
    claim(conn, cfg, *[source(f'g{i:02d}', quote=f'Server uses TLS g{i}.') for i in range(9)][:8])
    first = contract.inspect(conn, one.doc_id, limit=5)
    assert first['sources']['total'] == 24 and len(first['sources']['items']) == 5
    following = contract.inspect(conn, one.doc_id, limit=5, cursor=first['sources']['next_cursor'])
    assert following['version'] == first['version'] == contract.inspect(conn, one.doc_id)['version']
    assert {i['reference'] for i in first['sources']['items']}.isdisjoint({i['reference'] for i in following['sources']['items']})
    seen = [first['version']]
    key = keys(conn, one.doc_id)[-1]  # only on a later page: the token still covers it
    store.set_source_state(conn, key, state='removed', reason='withdrawn')
    seen.append(contract.inspect(conn, one.doc_id)['version'])
    store.set_source_state(conn, key, state='active', reason='reinstated')
    seen.append(contract.inspect(conn, one.doc_id)['version'])
    claim(conn, cfg, source('late', quote='Server uses TLS late.'))
    seen.append(contract.inspect(conn, one.doc_id)['version'])
    assert len(set(seen)) == 4


def test_pages_are_finite_and_input_is_bounded(conn, cfg):
    big = 'x' * 4000
    one = claim(conn, cfg, *[source(f'b{i}', quote=big + str(i)[:0]) for i in range(1)], body='big')
    for batch in range(4):
        claim(conn, cfg, *[source(f'b{batch}-{i}', quote=big) for i in range(8)], body='big')
    page = contract.inspect(conn, one.doc_id, limit=20)
    encoded = sum(len(i['quote'].encode()) for i in page['sources']['items'])
    assert encoded <= contract.QUOTE_PAGE_BYTES and page['sources']['next_cursor']
    assert page['sources']['limit'] == 20 and page['sources']['truncated'] is True
    for bad in [0, 21, True, '5']:
        with pytest.raises(ValueError):
            contract.inspect(conn, one.doc_id, limit=bad)
    for cursor in ['../etc', 'x' * 200, 'a.b']:
        with pytest.raises(ValueError):
            contract.inspect(conn, one.doc_id, cursor=cursor)


def test_unknown_unlinked_and_missing_anchors_are_indistinguishable(conn, cfg):
    one = claim(conn, cfg)
    other = claim(conn, cfg, source('other', quote='Other'), body='Other claim')
    foreign_key = keys(conn, other.doc_id)[0]
    errors = []
    for call in [lambda: contract.inspect(conn, 'missing-slug'),
                 lambda: contract.inspect(conn, one.doc_id, source_key=foreign_key),
                 lambda: contract.inspect(conn, one.doc_id, source_key='0' * 64),
                 lambda: contract.history(conn, one.doc_id, source_key=foreign_key),
                 lambda: contract.history(conn, '00000000-0000-0000-0000-000000000000')]:
        with pytest.raises(contract.EvidenceUnavailable) as caught:
            call()
        errors.append(str(caught.value))
    assert set(errors) == {'evidence_unavailable'}


def test_history_pages_claim_and_anchored_source_events(conn, cfg):
    one = claim(conn, cfg)
    key = keys(conn, one.doc_id)[0]
    for n in range(3):
        store.review_claim(conn, one.doc_id, state='unreviewed', reason=f'pass {n}', actor='alice')
    store.set_source_state(conn, key, state='refuted', reason='corrected', actor='bob')
    page = contract.history(conn, one.doc_id, limit=2)
    assert page['contract_version'] == 1 and page['scope'] == 'claim'
    assert page['pre_upgrade_history'] == 'not_captured'
    assert [i['operation'] for i in page['items']] == ['review', 'review']
    assert page['items'][0]['revision'] > page['items'][1]['revision'] and page['next_cursor']
    rest = contract.history(conn, one.doc_id, limit=20, cursor=page['next_cursor'])
    assert [i['operation'] for i in rest['items']] == ['review', 'attach'] and rest['next_cursor'] is None
    assert all(i['concurrency'] == 'legacy' and i['inspected_version'] is None for i in page['items'] + rest['items'])
    sourced = contract.history(conn, one.doc_id, source_key=key)
    assert sourced['scope'] == 'source' and sourced['items'][0]['actor'] == 'bob'
    assert sourced['anchor'] == {'document_id': one.doc_id, 'source_key': key}
    assert all('document_id' not in item for item in sourced['items'])


# ------------------------------------------------------------ strict decisions

def counts(conn):
    return conn.execute('SELECT (SELECT count(*) FROM audit_log) audit,(SELECT count(*) FROM claim_history) claims,'
                        '(SELECT count(*) FROM source_history) sources,'
                        '(SELECT string_agg(review_state,\',\') FROM claim_records) states').fetchone()


def test_strict_review_records_inspected_version_atomically(conn, cfg):
    one = claim(conn, cfg)
    seen = contract.inspect(conn, one.doc_id)['version']
    result = evidence.review(conn, one.doc_id, state='confirmed', reason='checked spans', actor='alice', expected_version=seen)
    assert result['version'] != seen and result['version'] == contract.inspect(conn, one.doc_id)['version']
    row = conn.execute("SELECT * FROM claim_history WHERE document_id=%s AND operation='review'", (one.doc_id,)).fetchone()
    assert (row['concurrency'], row['inspected_version'], row['actor'], row['state']) == ('strict', seen, 'alice', 'confirmed')
    assert row['revision'] == result['revision']


@pytest.mark.parametrize('change', ['attach', 'aba', 'legacy_review'])
def test_stale_strict_review_conflicts_without_any_change(conn, cfg, change):
    one = claim(conn, cfg)
    seen = contract.inspect(conn, one.doc_id)['version']
    if change == 'attach':
        claim(conn, cfg, source('second', quote='Server uses TLS too.'))
    elif change == 'aba':
        key = keys(conn, one.doc_id)[0]
        store.set_source_state(conn, key, state='removed', reason='withdrawn')
        store.set_source_state(conn, key, state='active', reason='reinstated')
    else:
        store.review_claim(conn, one.doc_id, state='unreviewed', reason='legacy writer without token')
    before = counts(conn)
    with pytest.raises(contract.EvidenceConflict) as caught:
        evidence.review(conn, one.doc_id, state='confirmed', reason='stale', expected_version=seen)
    assert str(caught.value) == 'evidence_conflict'
    assert counts(conn) == before
    fresh = contract.inspect(conn, one.doc_id)['version']
    evidence.review(conn, one.doc_id, state='confirmed', reason='fresh inspection', expected_version=fresh)


def test_strict_source_state_requires_anchor_and_current_source_version(conn, cfg):
    one = claim(conn, cfg)
    other = claim(conn, cfg, source('other', quote='Other'), body='Other claim')
    item = contract.inspect(conn, one.doc_id)['sources']['items'][0]
    with pytest.raises(ValueError):
        evidence.source_state(conn, item['source_key'], state='removed', reason='x', expected_version=item['source_version'])
    with pytest.raises(contract.EvidenceUnavailable):
        evidence.source_state(conn, item['source_key'], state='removed', reason='x',
                              expected_version=item['source_version'], anchor=other.doc_id)
    store.set_source_state(conn, item['source_key'], state='refuted', reason='legacy change')
    before = counts(conn)
    with pytest.raises(contract.EvidenceConflict):
        evidence.source_state(conn, item['source_key'], state='removed', reason='stale', anchor=one.doc_id,
                              expected_version=item['source_version'])
    assert counts(conn) == before
    current = contract.inspect(conn, one.doc_id)['sources']['items'][0]
    result = evidence.source_state(conn, item['source_key'], state='active', reason='reinstated', actor='carol',
                                   anchor=one.doc_id, expected_version=current['source_version'])
    assert result['source_version'] != current['source_version'] and result['revision'] == 3
    row = conn.execute('SELECT * FROM source_history WHERE source_key=%s ORDER BY revision DESC LIMIT 1', (item['source_key'],)).fetchone()
    assert (row['concurrency'], row['inspected_version'], row['actor']) == ('strict', current['source_version'], 'carol')


def test_invalid_strict_arguments_are_rejected_before_writes(conn, cfg):
    one = claim(conn, cfg)
    before = counts(conn)
    for version in ['', 'ev1:short', 'src1:' + 'a' * 64, 'ev1:' + 'G' * 64]:
        with pytest.raises(ValueError):
            evidence.review(conn, one.doc_id, state='confirmed', reason='x', expected_version=version)
    with pytest.raises(ValueError):
        evidence.review(conn, one.doc_id, state='confirmed', reason='r' * 1001,
                        expected_version=contract.inspect(conn, one.doc_id)['version'])
    assert counts(conn) == before


def test_audit_failure_rolls_back_strict_decision(conn, cfg):
    one = claim(conn, cfg)
    seen = contract.inspect(conn, one.doc_id)['version']
    conn.execute("CREATE FUNCTION pg_temp.fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'audit down'; END$$")
    conn.execute('CREATE TRIGGER fail_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_audit()')
    conn.commit()
    try:
        with pytest.raises(psycopg.Error):
            evidence.review(conn, one.doc_id, state='confirmed', reason='x', expected_version=seen)
    finally:
        conn.execute('DROP TRIGGER fail_audit ON audit_log')
        conn.commit()
    assert contract.inspect(conn, one.doc_id)['version'] == seen
    assert conn.execute("SELECT count(*) n FROM claim_history WHERE operation='review'").fetchone()['n'] == 0


def test_strict_review_waits_for_concurrent_source_change_then_conflicts(conn, cfg):
    one = claim(conn, cfg)
    key = keys(conn, one.doc_id)[0]
    seen = contract.inspect(conn, one.doc_id)['version']
    conn.commit()
    holder = db.connect(cfg, role='owner')
    evidence.source_state(holder, key, state='removed', reason='concurrent withdrawal', commit=False)
    outcome = {}

    def reviewer():
        with db.connect(cfg, role='owner') as other:
            try:
                evidence.review(other, one.doc_id, state='confirmed', reason='racing', expected_version=seen)
                outcome['result'] = 'committed'
            except contract.EvidenceConflict:
                outcome['result'] = 'conflict'
    thread = threading.Thread(target=reviewer)
    thread.start()
    thread.join(0.5)
    assert thread.is_alive()  # blocked on the per-source lock, not deciding on stale state
    holder.commit()
    holder.close()
    thread.join(10)
    assert outcome == {'result': 'conflict'}


def test_source_update_never_waits_for_claim_lock(conn, cfg):
    one = claim(conn, cfg)
    key = keys(conn, one.doc_id)[0]
    conn.commit()
    with db.connect(cfg, role='owner') as reviewer:
        reviewer.execute('SELECT 1 FROM claim_records WHERE document_id=%s FOR UPDATE', (one.doc_id,))
        with db.connect(cfg, role='owner') as writer:
            writer.execute("SET lock_timeout='2s'")
            evidence.source_state(writer, key, state='refuted', reason='independent of claim lock')
        reviewer.rollback()


def test_page_and_history_budgets_count_encoded_bytes(conn, cfg):
    control = '\x01' * 3990  # each character encodes as six JSON bytes
    one = claim(conn, cfg, *[source(f'c{i}', quote=control + str(i)) for i in range(8)], body='control')
    claim(conn, cfg, *[source(f'd{i}', quote=control + 'd' + str(i)) for i in range(8)], body='control')
    page = contract.inspect(conn, one.doc_id)
    encoded = len(json.dumps(page, ensure_ascii=False).encode())
    assert encoded <= 120 * 1024 and page['sources']['next_cursor']
    for n in range(12):
        store.review_claim(conn, one.doc_id, state='unreviewed', reason='\x01' * 1000 + str(n))
    history = contract.history(conn, one.doc_id)
    assert len(json.dumps(history, ensure_ascii=False).encode()) <= 120 * 1024 and history['next_cursor']


def test_strict_review_waits_for_old_source_writer_without_advisory_locks(conn, cfg):
    """A still-running 0.6.15 source UPDATE must serialize with a strict review."""
    one = claim(conn, cfg)
    key = keys(conn, one.doc_id)[0]
    seen = contract.inspect(conn, one.doc_id)['version']
    conn.commit()
    outcome = {}
    with db.connect(cfg, role='writer') as holder:
        # Exactly the old source-state SQL; no new Python/advisory-lock helper.
        holder.execute("UPDATE knowledge_sources SET state='removed',reason='old writer' WHERE source_key=%s", (key,))
        def reviewer():
            try:
                with db.connect(cfg, role='writer') as other:
                    evidence.review(other, one.doc_id, state='confirmed', reason='racing old writer', expected_version=seen)
                outcome['result'] = 'committed'
            except contract.EvidenceConflict:
                outcome['result'] = 'conflict'
            except BaseException as error:
                outcome['error'] = repr(error)
        thread = threading.Thread(target=reviewer)
        thread.start()
        thread.join(0.5)
        waiting = thread.is_alive()
        holder.commit()
    thread.join(10)
    assert waiting, outcome
    assert not thread.is_alive() and outcome == {'result': 'conflict'}
    assert conn.execute("SELECT count(*) n FROM claim_history WHERE operation='review'").fetchone()['n'] == 0


def test_strict_review_waits_for_document_lifecycle_change(conn, cfg):
    """The token includes lifecycle, so a concurrent archive must invalidate it."""
    one = claim(conn, cfg)
    seen = contract.inspect(conn, one.doc_id)['version']
    conn.commit()
    outcome = {}
    with db.connect(cfg, role='writer') as holder:
        holder.execute("UPDATE documents SET status='archived' WHERE id=%s", (one.doc_id,))
        def reviewer():
            try:
                with db.connect(cfg, role='writer') as other:
                    evidence.review(other, one.doc_id, state='confirmed', reason='racing archive', expected_version=seen)
                outcome['result'] = 'committed'
            except contract.EvidenceConflict:
                outcome['result'] = 'conflict'
            except BaseException as error:
                outcome['error'] = repr(error)
        thread = threading.Thread(target=reviewer)
        thread.start()
        thread.join(0.5)
        waiting = thread.is_alive()
        holder.commit()
    thread.join(10)
    assert waiting, outcome
    assert not thread.is_alive() and outcome == {'result': 'conflict'}


def test_inspection_bounds_legacy_reasons_as_well_as_quotes(conn, cfg):
    """Old unbounded reason fields must not make the new finite pages unusable."""
    one = claim(conn, cfg, *[source(f'reason-{i}') for i in range(8)])
    for key in keys(conn, one.doc_id):
        store.set_source_state(conn, key, state='active', reason='\x01' * 30000)
    store.review_claim(conn, one.doc_id, state='unreviewed', reason='\x01' * 30000)
    view = contract.inspect(conn, one.doc_id)
    assert len(json.dumps(view, ensure_ascii=False).encode()) <= 120 * 1024
    assert len(view['claim']['review_reason']) <= 1000 and view['claim']['review_reason_truncated']
    assert all(len(i['trust']['reason']) <= 1000 and i['trust']['reason_truncated'] for i in view['sources']['items'])
