"""RAG-064 T064-002: opt-in temporal preference/filter on real PostgreSQL retrieval."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import psycopg
import pytest

from agentic_rag import search, store
from agentic_rag.benchmark import temporal_query as fixture
from agentic_rag.domains import seed_defaults
from agentic_rag.evidence import attach
from agentic_rag.store import EdgeSpec

CASES = fixture.load('ranking-cases.json')
DEV = {c['id']: c for c in CASES['dev']}
R1 = '2026-10-30T10:00:00+01:00'
MARKER = 'rag-temporal-metadata'


@pytest.fixture
def corpus(conn, cfg, monkeypatch):
    seed_defaults(conn)
    conn.commit()
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)
    keys = fixture.ingest(conn, cfg)
    return replace(cfg, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1'), keys


def run(conn, cfg, keys, case, mode, **overrides):
    diagnostics = {}
    hits, warnings = search.search(conn, cfg, overrides.pop('query', case['query']),
                                   **{**fixture.options(case, mode=mode), **overrides}, diagnostics=diagnostics)
    conn.rollback()
    return fixture.ranked_keys(hits, keys), hits, warnings, diagnostics.get('temporal')


class Recorder:
    """Records every statement on the real connection; never alters it."""
    def __init__(self, conn):
        self.conn, self.sql = conn, []

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, *args, **kwargs):
        self.sql.append(str(query))
        return self.conn.execute(query, *args, **kwargs)


def legacy(conn, cfg, case, query=None):
    options = fixture.options(case, mode=None)
    hits, warnings = search.search(conn, cfg, query or case['query'], **options)
    conn.rollback()
    return hits, warnings


@pytest.mark.parametrize('name', ['RD01', 'RD02', 'RD04', 'RD06', 'RD08', 'RD09', 'RD10'])
def test_development_preference_puts_matching_events_first(corpus, conn, name):
    cfg, keys = corpus
    case = DEV[name]
    order, _, _, report = run(conn, cfg, keys, case, 'prefer')
    expected = case['expected']
    assert set(order[:len(expected)]) == set(expected), order
    assert not set(case['forbidden']) & set(order)
    assert report['applied'] == 'preference' and report['status'] == 'interval'


def test_temporal_stage_cannot_add_candidates_lexical_retrieval_misses(corpus, conn):
    """Frozen RD07 contains 'changed', which no document body has: lexical
    candidate retrieval is empty with and without the feature."""
    cfg, keys = corpus
    case = DEV['RD07']
    order, _, _, report = run(conn, cfg, keys, case, 'prefer')
    assert order == [] and legacy(conn, cfg, case)[0] == []
    assert report['effect']['candidates'] == 0 and report['limits']['recall'] == 'candidate_limited'


@pytest.mark.parametrize('name', ['RD03', 'RD05'])
def test_hard_filter_returns_only_known_matching_events(corpus, conn, name):
    cfg, keys = corpus
    case = DEV[name]
    order, hits, _, report = run(conn, cfg, keys, case, 'filter')
    assert order == case['expected']
    assert all(h.evidence['temporal']['match'] == 'inside' for h in hits)
    assert report['applied'] == 'filter' and report['effect']['excluded'] >= 1


def test_ambiguous_soft_keeps_order_and_hard_fails_closed(corpus, conn):
    cfg, keys = corpus
    soft = DEV['RD11']
    order, hits, warnings, report = run(conn, cfg, keys, soft, 'prefer')
    base, _ = legacy(conn, cfg, soft)
    assert [h.chunk_id for h in hits] == [h.chunk_id for h in base]
    assert report['status'] == 'ambiguous' and report['applied'] == 'none'
    assert any('temporal expression not applied' in w for w in warnings)
    with pytest.raises(ValueError, match='temporal_filter_requires_interval'):
        run(conn, cfg, keys, DEV['RD12'], 'filter')
    for query in ('nightly backup job failed', 'nightly backup job failed currently', 'nightly backup 03/04/2026'):
        with pytest.raises(ValueError, match='temporal_filter_requires_interval'):
            run(conn, cfg, keys, DEV['RD12'], 'filter', query=query)


def test_off_disabled_and_no_intent_match_legacy_without_metadata_sql(corpus, conn, monkeypatch):
    cfg, keys = corpus
    enabled = replace(cfg, temporal_enabled=True)
    def unavailable(*a, **k):
        raise AssertionError('temporal metadata must not be read')
    monkeypatch.setattr(search, '_event_metadata', unavailable)
    for name in ('RC01', 'RC02', 'RC03'):
        case = DEV[name]
        base = legacy(conn, cfg, case)
        recorder = Recorder(conn)
        hits, warnings = search.search(recorder, enabled, case['query'], **fixture.options(case, mode='auto'),
                                       diagnostics=(diagnostics := {}))
        conn.rollback()
        assert (hits, warnings) == base and diagnostics == {}
        assert not any(MARKER in s for s in recorder.sql)
    intent = DEV['RD01']
    base = legacy(conn, cfg, intent)
    for config, mode in ((cfg, 'auto'), (cfg, None), (enabled, 'off')):
        options = fixture.options(intent, mode=mode)
        if mode is None:
            options.update(temporal=None, reference=intent['reference'], timezone=intent['timezone'])
        recorder = Recorder(conn)
        result = search.search(recorder, config, intent['query'], **options, diagnostics=(diagnostics := {}))
        conn.rollback()
        assert result == base and not any(MARKER in s for s in recorder.sql)
        assert diagnostics == {} or diagnostics['temporal']['applied'] == 'none'


def test_enabled_auto_prefers_but_never_filters(corpus, conn):
    cfg, keys = corpus
    case = DEV['RD01']
    order, _, _, report = run(conn, replace(cfg, temporal_enabled=True), keys, case, 'auto')
    assert order[0] == 'dev-backup-yesterday' and report['mode'] == 'prefer' and report['requested'] == 'auto'


def test_scores_and_snippets_are_original_for_the_retrieval_text(corpus, conn):
    cfg, keys = corpus
    case = DEV['RD02']
    _, hits, _, report = run(conn, cfg, keys, case, 'prefer')
    assert report['retrieval_query'] == 'without_time_expressions'
    base, _ = legacy(conn, cfg, case, query='nightly backup job failed')
    by_chunk = {h.chunk_id: h for h in base}
    assert {h.chunk_id for h in hits} == set(by_chunk)
    for hit in hits:
        original = by_chunk[hit.chunk_id]
        assert (hit.score, hit.snippet, hit.citation, hit.snippet_start, hit.snippet_end) == (
            original.score, original.snippet, original.citation, original.snippet_start, original.snippet_end)
        assert {k: v for k, v in hit.evidence.items() if k != 'temporal'} == original.evidence


def test_per_hit_basis_and_envelope_hide_private_locators(corpus, conn, cfg):
    cfg, keys = corpus
    order, hits, _, report = run(conn, cfg, keys, DEV['RD01'], 'prefer')
    by_key = {fixture.ranked_keys([h], keys)[0]: h.evidence['temporal'] for h in hits}
    assert by_key['dev-backup-yesterday'] == {'basis': 'source_event', 'match': 'inside',
        'event_at': '2026-10-29T13:00:00+00:00', 'qualifying_events': 1, 'support': ['user_source_event']}
    assert by_key['dev-backup-legacy'] == {'basis': 'unknown', 'match': 'unknown', 'event_at': None,
                                           'qualifying_events': 0, 'support': []}
    # Only the qualifying user source counts; the assistant span dated yesterday does not.
    assert by_key['dev-backup-assistant']['match'] == 'outside'
    assert by_key['dev-backup-assistant']['event_at'] == '2026-09-10T08:00:00+00:00'
    _, relay, _, _ = run(conn, cfg, keys, DEV['RD07'], 'prefer', query='mail relay port yesterday')
    assert relay[0].evidence['temporal']['basis'] == 'assertion_event'
    effect = report['effect']
    assert effect['matching'] == 1 and effect['unknown'] >= 1 and effect['reordered'] is True
    assert report['limits'] == {'candidate_limit': 150, 'graph_node_limit': 20, 'recall': 'candidate_limited'}
    assert 'not independent verification' in report['event_time']
    text = json.dumps(report) + json.dumps([h.evidence for h in hits])
    for private in ('synthetic', '-src-', 'retry succeeded', 'namespace', 'source_id'):
        assert private not in text


def test_ingestion_time_is_never_event_time(corpus, conn):
    cfg, keys = corpus
    case = dict(DEV['RD03'], reference=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), as_of=None)
    order, hits, _, _ = run(conn, cfg, keys, case, 'filter', query='Druckerwartung gestern')
    assert order == []
    order, hits, _, report = run(conn, cfg, keys, case, 'prefer', query='Druckerwartung gestern')
    assert 'ho-print-legacy' in order and report['effect']['matching'] == 0
    assert all(h.evidence['temporal']['match'] != 'inside' for h in hits)


def test_partial_assistant_and_manual_sources(corpus, conn):
    cfg, keys = corpus
    body = 'Partial quote synthetic switch reboot.'
    partial = store.save_claim(conn, cfg, title='partial', body=body, domain='general', dtype='memory',
        project='/synthetic/team', claim_kind='stated', evidence=[
            dict(namespace='synthetic', source_id='p-old', role='user', quote=body, timestamp='2026-09-01T10:00:00Z', complete=True),
            dict(namespace='synthetic', source_id='p-new', role='user', quote=body, timestamp='2026-10-29T10:00:00Z', complete=False)])
    manual = store.save_claim(conn, cfg, title='manual', body='Manual synthetic switch reboot attestation.',
        domain='general', dtype='memory', project='/synthetic/team', claim_kind='stated', evidence=[
            dict(namespace='manual', source_id='m', role='user', quote='Manual synthetic switch reboot attestation.',
                 timestamp='2026-10-29T12:00:00Z', complete=True)])
    conn.commit()
    keys = {**keys, 'partial': partial.doc_id, 'manual': manual.doc_id}
    case = dict(DEV['RD03'])
    order, hits, _, _ = run(conn, cfg, keys, case, 'filter', query='synthetic switch reboot gestern')
    assert order == ['manual']
    assert hits[0].evidence['temporal']['support'] == ['manual_attestation']


def test_lifecycle_scope_and_future_assertions_are_not_resurrected(corpus, conn):
    cfg, keys = corpus
    never = {'dev-backup-refuted', 'dev-backup-withdrawn', 'dev-backup-private', 'dev-relay-future',
             'dev-relay-old', 'dev-relay-expired'}
    for name in ('RD01', 'RD03', 'RD08', 'RD09'):
        case = DEV[name]
        for mode in ('prefer', 'filter'):
            order, _, _, _ = run(conn, cfg, keys, case, mode)
            forbidden = set(case['forbidden']) if mode == 'filter' else set(case['forbidden']) & never
            assert not forbidden & set(order), (name, mode)
    future = dict(DEV['RD08'])
    assert run(conn, cfg, keys, future, 'filter')[0] == []
    # Explicit history keeps its existing meaning, including future/superseded rows.
    history = dict(future, history=True, as_of=None)
    assert run(conn, cfg, keys, history, 'filter')[0] == ['dev-relay-future']
    # The interpretation reference cannot move the valid-time selection.
    shifted = dict(future, reference='2026-10-20T10:00:00+02:00')
    order, _, _, report = run(conn, cfg, keys, shifted, 'filter')
    assert order == [] and report['reference'] == '2026-10-20T08:00:00+00:00'


@pytest.mark.parametrize("limit", [3, 5])
def test_graph_expansion_cannot_leak_or_undo_preference(corpus, conn, limit):
    cfg, keys = corpus
    neighbour = store.save_claim(conn, cfg, title='neighbour', body='Unrelated cabling inventory sheet.',
        domain='general', dtype='memory', project='/synthetic/team', claim_kind='stated', evidence=[
            dict(namespace='synthetic', source_id='n', role='user', quote='Unrelated cabling inventory sheet.',
                 timestamp='2026-01-05T10:00:00Z', complete=True)])
    linked = {}
    for name, when in (('seed', '2026-10-29T10:00:00Z'), ('other', '2026-10-29T18:00:00Z'), ('third', '2026-10-29T20:00:00Z')):
        body = f'Graph seed outage of the core switch, {name} report.'
        linked[name] = store.save_claim(conn, cfg, title=name, body=body, domain='general', dtype='memory',
            project='/synthetic/team', claim_kind='stated', edges=[EdgeSpec('references', neighbour.slug, 'synthetic link', 'high')],
            evidence=[dict(namespace='synthetic', source_id=name, role='user', quote=body, timestamp=when, complete=True)]).doc_id
    conn.commit()
    keys = {**keys, 'neighbour': neighbour.doc_id, **linked}
    # Edges are valid from their creation; select the current graph, not the fixture as_of.
    case = dict(DEV['RD03'], query='graph seed outage core switch gestern', as_of=None)
    hits, _ = search.search(conn, cfg, 'graph seed outage core switch', **{**fixture.options(case, mode=None), 'graph_depth': 1})
    conn.rollback()
    plain = fixture.ranked_keys(hits, keys)
    # Existing graph promotion places the out-of-period neighbour before the third match.
    assert plain[2] == 'neighbour' and len(plain) == 4
    order, _, _, report = run(conn, cfg, keys, case, 'filter', graph_depth=1, k=limit)
    assert set(order) == {'seed', 'other', 'third'} and report['effect']['graph_checked'] == 1
    order, hits, _, _ = run(conn, cfg, keys, case, 'prefer', graph_depth=1, k=limit)
    assert set(order[:3]) == {'seed', 'other', 'third'}
    assert len(order) <= limit
    if limit > 3:
        assert order[3] == 'neighbour' and hits[-1].graph_depth == 1


def test_symbols_and_exact_selectors_are_preserved(corpus, conn):
    cfg, keys = corpus
    for i, (when, text) in enumerate([('2026-10-29T10:00:00Z', 'ERR_SYNTH_FAIL in the parser'),
                                      ('2026-09-01T10:00:00Z', 'ERR_SYNTH_FAIL in the parser again, ERR_SYNTH_FAIL'),
                                      ('2026-10-29T11:00:00Z', 'Parser failure without the code')]):
        saved = store.save_claim(conn, cfg, title='sym' + str(i), body=text, domain='general', dtype='memory',
            project='/synthetic/team', claim_kind='stated', evidence=[
                dict(namespace='synthetic', source_id='sym' + str(i), role='user', quote=text, timestamp=when, complete=True)])
        keys['sym' + str(i)] = saved.doc_id
    conn.commit()
    case = DEV['RD01']
    order, _, _, _ = run(conn, cfg, keys, case, 'prefer', query='ERR_SYNTH_FAIL gestern')
    assert order == ['sym0', 'sym1']
    slug = conn.execute('SELECT slug FROM documents WHERE id=%s', (keys['dev-vpn-1014'],)).fetchone()['slug']
    conn.rollback()
    order, _, _, report = run(conn, cfg, keys, case, 'prefer', query=slug)
    assert order == ['dev-vpn-1014'] and report['status'] == 'none'


def test_soft_metadata_failure_is_safe_and_hard_failure_keeps_transaction(corpus, conn, monkeypatch):
    cfg, keys = corpus
    monkeypatch.setattr(search, '_TEMPORAL_SQL', 'SELECT 1/0 AS failure, %(ids)s::uuid[] AS ids /* ' + MARKER + ' */')
    case = DEV['RD01']
    base, _ = legacy(conn, cfg, case, query='nightly backup job failed')
    diagnostics = {}
    hits, warnings = search.search(conn, cfg, case['query'], **fixture.options(case, mode='prefer'), diagnostics=diagnostics)
    assert conn.execute('SELECT 1 AS alive').fetchone()['alive'] == 1
    conn.rollback()
    assert [h.chunk_id for h in hits] == [h.chunk_id for h in base]
    assert 'temporal metadata unavailable — original order kept' in warnings
    assert diagnostics['temporal']['applied'] == 'none' and diagnostics['temporal']['reasons'] == ['metadata_unavailable']
    assert all('temporal' not in h.evidence for h in hits)
    with pytest.raises(RuntimeError, match='temporal_metadata_unavailable'):
        search.search(conn, cfg, case['query'], **fixture.options(case, mode='filter'))
    assert conn.execute('SELECT 1 AS alive').fetchone()['alive'] == 1
    conn.rollback()


def test_metadata_is_finite_for_many_sources_and_bounded_ids(corpus, conn):
    cfg, keys = corpus
    doc = keys['dev-backup-yesterday']
    for batch in range(3):
        attach(conn, doc, [dict(namespace='synthetic', source_id=f'extra-{batch}-{i}', role='user',
                                quote='Nightly backup job failed on the storage node; retry succeeded.',
                                timestamp=f'2026-10-{10 + i:02d}T10:00:00Z', complete=True) for i in range(8)], 'cli')
    conn.commit()
    _, hits, _, _ = run(conn, cfg, keys, DEV['RD01'], 'prefer')
    explained = next(h.evidence['temporal'] for h in hits if h.document_id == doc)
    assert explained['qualifying_events'] == 25 and explained['match'] == 'inside'
    interpretation = search.temporal.interpret('gestern', reference=R1)
    with pytest.raises(ValueError, match='bounded'):
        search._event_metadata(conn, ['00000000-0000-0000-0000-000000000000'] * 171, interpretation,
                               datetime.now(timezone.utc), False)
    conn.rollback()


def test_baseline_and_invalid_options_are_rejected_before_sql(corpus, conn):
    cfg, _ = corpus
    with pytest.raises(ValueError, match='baseline'):
        search.search(conn, cfg, 'x gestern', baseline=True, temporal='prefer')
    for options in ({'temporal': 'strict'}, {'temporal': 'prefer', 'timezone': 'Nowhere/City'},
                    {'temporal': 'prefer', 'reference': '2026-10-30T10:00:00'}):
        with pytest.raises(ValueError):
            search.search(conn, cfg, 'backup gestern', **options)
    conn.rollback()


def test_unavailable_metadata_does_not_break_a_read_only_role(corpus, conn, cfg):
    """A real reader connection (no owner rights) reads the same metadata."""
    from agentic_rag import db
    cfg, keys = corpus
    reader = db.connect(cfg, role='reader')
    try:
        order, _, _, report = run(reader, cfg, keys, DEV['RD01'], 'prefer')
    finally:
        reader.close()
    assert order[0] == 'dev-backup-yesterday' and report['applied'] == 'preference'


def test_source_withdrawal_between_retrieval_and_metadata_removes_preferred_hit(corpus, conn):
    """A fresh eligibility rejection is exclusion, not an unknown date that
    preference mode may keep behind its matching candidates."""
    from agentic_rag import db
    from agentic_rag.evidence import sources
    cfg, keys = corpus
    body = 'Temporal revocation probe original report.'
    saved = store.save_claim(conn, cfg, title='Temporal revocation probe', body=body,
        domain='general', dtype='memory', project='/synthetic/team', claim_kind='stated',
        evidence=[dict(namespace='synthetic', source_id='revocation-probe', role='user',
                       quote=body, timestamp='2026-10-29T10:00:00Z', complete=True)])
    source_key = sources(conn, saved.doc_id)[0]['source_key']
    conn.commit()

    class WithdrawBeforeMetadata(Recorder):
        withdrawn = False

        def execute(self, query, *args, **kwargs):
            if MARKER in str(query) and not self.withdrawn:
                self.withdrawn = True
                with db.connect(cfg) as writer:
                    store.set_source_state(writer, source_key, state='removed', reason='Concurrent withdrawal')
            return super().execute(query, *args, **kwargs)

    observed = WithdrawBeforeMetadata(conn)
    hits, _ = search.search(observed, cfg, 'temporal revocation probe gestern',
        **fixture.options(DEV['RD01'], mode='prefer'))
    assert observed.withdrawn
    assert hits == []
