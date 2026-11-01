"""RAG-066 T066-005: explicit views across candidate families, get, graph, research and
derived readers. Selection happens in SQL before each LIMIT; omitted views keep
every existing default and payload shape."""
import json

import psycopg
import pytest

from agentic_rag import db, graph, lifecycle, profiles, search, store, thematic
from agentic_rag.benchmark import memory_lifecycle as fx

pytestmark = pytest.mark.usefixtures('conn')
LABELS = fx.load('labels.json')['cases']
PROJECT = '/synthetic/lifecycle-a'


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a, **k: None)


@pytest.fixture
def ids(conn, cfg):
    return fx.ingest(conn, cfg)


def apply(conn, cfg, member, target, operation, reason='view test'):
    seen = lifecycle.preview(conn, member, target, operation=operation)
    conn.rollback()
    return store.apply_lifecycle(conn, cfg, member=member, target=target, operation=operation,
                                 expected_member_version=seen['member']['version'],
                                 expected_target_version=seen['target']['version'], reason=reason,
                                 reviewed=operation not in ('exact_duplicate', 'contradiction'), actor='cli')


def lexical(conn, cfg, query, k=8, **kw):
    hits, _ = search.search(conn, cfg, query, domain='general', k=k, project=PROJECT, strategy='lexical',
                            rerank_mode='off', context_mode='off', **kw)
    conn.rollback()
    return hits


def selected(conn, ids, keys, view):
    names = {v: k for k, v in ids.items()}
    with lifecycle.view_scope(conn, view):
        rows = conn.execute('SELECT id::text AS id FROM documents WHERE id = ANY(%s::uuid[]) AND status=%s'
                            ' AND assertion_eligible(id)', ([ids[k] for k in keys], 'active')).fetchall()
    conn.rollback()
    return sorted(names[r['id']] for r in rows)


def test_views_match_frozen_labels_after_each_operation(conn, cfg, ids):
    for case in ('E1', 'R1', 'P1', 'P2', 'C1'):
        label = LABELS[case]
        member, target = label['pair']
        apply(conn, cfg, ids[member], ids[target], label['apply']['operation'])
        for view, wanted in label['views'].items():
            assert selected(conn, ids, label['pair'], view) == wanted, (case, view)
    for case in ('A1', 'Q1'):
        for view, wanted in LABELS[case]['views'].items():
            assert selected(conn, ids, LABELS[case]['pair'], view) == wanted, (case, view)
    as_of = LABELS['P1']['as_of']
    hits = lexical(conn, cfg, 'Wiki backups', view='current', as_of=as_of['at'])
    names = {v: k for k, v in ids.items()}
    assert sorted(names[h.document_id] for h in hits) == as_of['current']


def test_k1_selection_happens_before_limit_in_every_candidate_family(conn, cfg, ids):
    # Members rank above their canonical; a post-LIMIT filter would return nothing.
    canonical = store.save_document(conn, cfg, title='Spooler restart', body='Restart the spooler.', domain='general',
                                    dtype='memory', project=PROJECT).doc_id
    members = [store.save_document(conn, cfg, title=f'Spooler restart note {n}',
                                   body='Restart the spooler. Spooler spooler spooler restart restart.', domain='general',
                                   dtype='memory', project=PROJECT).doc_id for n in range(4)]
    conn.commit()
    for member in members:
        apply(conn, cfg, member, canonical, 'semantic_duplicate')
    assert [h.document_id for h in lexical(conn, cfg, 'spooler restart', k=1)] == [canonical]
    assert [h.document_id for h in lexical(conn, cfg, 'spooler restart', k=1, view='current')] == [canonical]
    merged = lexical(conn, cfg, 'spooler restart', k=1, view='include_merged')
    assert merged[0].document_id in members and merged[0].evidence['lifecycle']['state'] == 'merged'
    scopes = [PROJECT, 'global']
    for function in ('hybrid_search_candidates', 'hybrid_search_temporal', 'hybrid_search_contextual',
                     'hybrid_search_candidates_planned', 'hybrid_search_contextual_planned', 'contextual_search_candidates'):
        rows = conn.execute(f'SELECT document_id::text AS id FROM {function}(%s,NULL,%s,1,%s,now(),false)',
                            ('spooler restart', 'general', scopes)).fetchall()
        assert [r['id'] for r in rows] in ([canonical], []), function  # contextual has no indexed context here
        assert function.startswith('contextual') or [r['id'] for r in rows] == [canonical], function
    conn.rollback()
    # Identity shortcut (slug selector) and graph expansion use the same predicate.
    slug = conn.execute('SELECT slug FROM documents WHERE id=%s', (members[0],)).fetchone()['slug']
    assert search._identity_candidates(conn, slug, 'general', scopes, *search_time()) in (None, [])
    conn.rollback()


def search_time():
    from agentic_rag.validity import selection
    return selection(None, False)


def test_omitted_view_keeps_payload_and_invalid_combinations_fail_before_sql(conn, cfg, ids):
    before = [json.dumps(h.__dict__, default=str, sort_keys=True) for h in lexical(conn, cfg, 'printer toner', k=10)]
    assert before and all("'lifecycle'" not in b and '"lifecycle"' not in b for b in before)
    for kwargs in ({'view': 'current', 'history': True}, {'view': 'include_merged', 'history': True},
                   {'view': 'historical', 'as_of': '2026-01-01T00:00:00Z'}, {'view': 'newest'}):
        with pytest.raises(lifecycle.LifecycleError, match='invalid_view'):
            lexical(conn, cfg, 'printer toner', **kwargs)
        with pytest.raises(lifecycle.LifecycleError, match='invalid_view'):
            graph.neighbors(conn, ids['R1-rich'], **{k: v for k, v in kwargs.items()})
    # latest is an alias of current; labels appear only when a view was given.
    hits = lexical(conn, cfg, 'printer toner', k=10, view='latest')
    assert {h.evidence['lifecycle']['view'] for h in hits} == {'current'}
    assert [json.dumps(h.__dict__, default=str, sort_keys=True) for h in lexical(conn, cfg, 'printer toner', k=10)] == before


def test_view_setting_is_restored_across_nesting_savepoints_errors_and_autocommit(cfg, ids):
    with db.connect(cfg, role='reader') as c:
        with lifecycle.view_scope(c, 'include_merged'):
            with c.transaction():
                with lifecycle.view_scope(c, 'historical'):
                    assert lifecycle._setting(c) == 'historical'
            assert lifecycle._setting(c) == 'include_merged'
            with pytest.raises(RuntimeError):
                with lifecycle.view_scope(c, 'current'):
                    raise RuntimeError('boom')
            assert lifecycle._setting(c) == 'include_merged'
        assert lifecycle._setting(c) == ''
        c.rollback()
    with db.connect(cfg, role='reader') as c:
        c.autocommit = True
        with lifecycle.view_scope(c, 'include_merged'):
            assert lifecycle._setting(c) == 'include_merged'
        assert lifecycle._setting(c) == ''
    with db.connect(cfg, role='reader') as c:
        with pytest.raises(psycopg.errors.DivisionByZero):
            with lifecycle.view_scope(c, 'include_merged'):
                c.execute('SELECT 1/0')
        c.rollback()
        assert lifecycle._setting(c) == ''


def test_get_resolves_canonical_and_never_discloses_unavailable_targets(conn, cfg, ids, hook_env):
    from agentic_rag import mcp_server
    apply(conn, cfg, ids['E1-copy'], ids['E1-keep'], 'exact_duplicate')
    apply(conn, cfg, ids['G1-old'], ids['G1-new'], 'replacement')
    plain = mcp_server.memory_get(ids['E1-copy'])
    assert plain['document']['id'] == ids['E1-copy'] and 'lifecycle' not in plain
    current = mcp_server.memory_get(ids['E1-copy'], view='current')
    assert current['document']['id'] == ids['E1-keep']
    assert current['lifecycle'] | {} == {**current['lifecycle'], 'requested_id': ids['E1-copy'],
                                         'canonical_id': ids['E1-keep'], 'resolution': 'canonical'}
    merged = mcp_server.memory_get(ids['E1-copy'], view='include_merged')
    assert merged['document']['id'] == ids['E1-copy'] and merged['lifecycle']['state'] == 'merged'
    store.review_claim(conn, ids['G1-new'], state='refuted', reason='wrong')
    conn.execute('DELETE FROM documents WHERE id=%s', (ids['G1-new'],))  # admin purge
    conn.commit()
    gone = mcp_server.memory_get(ids['G1-old'], view='current')
    assert gone['document'] is None and gone['lifecycle']['resolution'] == 'canonical_unavailable'
    assert ids['G1-new'] not in json.dumps(gone)
    with db.connect(cfg, role='reader') as r:
        detail = lifecycle.detail(r, ids['G1-old'])
    assert detail['as_member'][0]['resolution'] == 'canonical_unavailable' and ids['G1-new'] not in json.dumps(detail)
    assert detail['as_member'][0]['relationship'] == 'replaced' and not detail['current']


def test_graph_default_history_is_unchanged_and_explicit_view_selects(conn, cfg, ids):
    store.save_document(conn, cfg, doc_id=ids['R1-rich'], title='Printer P1 toner and drum',
                        body='Printer P1 uses toner TN-243 and drum DR-243; replace the drum every 12000 pages.',
                        domain='general', dtype='memory', edges=[store.EdgeSpec('extends', 'printer-p1-toner')])
    conn.commit()
    apply(conn, cfg, ids['R1-short'], ids['R1-rich'], 'extension')
    default = graph.neighbors(conn, ids['R1-rich'])
    current = graph.neighbors(conn, ids['R1-rich'], view='current')
    merged = graph.neighbors(conn, ids['R1-rich'], view='include_merged')
    conn.rollback()
    assert len(default) == 1 and current == [] and len(merged) == 1


@pytest.mark.parametrize(('key', 'view'), [
    ('P1-old', 'include_merged'),
    ('Q1-inferred', 'historical'),
    ('P5-future', 'historical'),
])
def test_explicit_get_obeys_the_selected_view(conn, cfg, ids, hook_env, key, view):
    from agentic_rag import mcp_server
    apply(conn, cfg, ids['P1-old'], ids['P1-new'], 'replacement')
    # Raw original inspection stays available; selecting a view must apply its
    # truth/time gates, just like search, instead of merely adding a label.
    assert mcp_server.memory_get(ids[key])['document']['id'] == ids[key]
    result = mcp_server.memory_get(ids[key], view=view)
    assert result['document'] is None
    assert result['edges_in'] == [] and result['edges_out'] == []


def test_derived_current_scope_inside_autocommit_view(cfg, ids, conn):
    apply(conn, cfg, ids['R1-short'], ids['R1-rich'], 'extension')
    with db.connect(cfg, role='reader') as reader:
        reader.autocommit = True
        with lifecycle.view_scope(reader, 'include_merged'):
            assert reader.execute('SELECT assertion_eligible(%s) ok', (ids['R1-short'],)).fetchone()['ok']
            with lifecycle.current_scope(reader):
                assert not reader.execute('SELECT assertion_eligible(%s) ok', (ids['R1-short'],)).fetchone()['ok']
            assert reader.execute('SELECT assertion_eligible(%s) ok', (ids['R1-short'],)).fetchone()['ok']


def test_derived_profile_thematic_and_pattern_follow_decisions(conn, cfg, ids, monkeypatch):
    store.refresh_profile(conn, cfg, PROJECT)
    assert profiles.read(conn, cfg, PROJECT)['status'] == 'fresh'
    store.refresh_summaries(conn, cfg, 'printer toner', project=PROJECT, domain='general')
    assert thematic.read(conn, cfg, 'printer toner', project=PROJECT, domain='general')['status'] == 'fresh'
    conn.commit()
    made = apply(conn, cfg, ids['R1-short'], ids['R1-rich'], 'extension')
    assert profiles.read(conn, cfg, PROJECT)['status'] == 'stale'
    assert thematic.read(conn, cfg, 'printer toner', project=PROJECT, domain='general')['status'] == 'stale'
    # A request view can never widen derived readers.
    with lifecycle.view_scope(conn, 'include_merged'):
        with lifecycle.current_scope(conn):
            assert lifecycle._setting(conn) == 'current'
            assert not conn.execute('SELECT assertion_eligible(%s) ok', (ids['R1-short'],)).fetchone()['ok']
    conn.rollback()
    store.correct_lifecycle(conn, cfg, decision_id=made['decision']['id'], expected_revision=1, reason='undo', actor='cli')
    assert conn.execute('SELECT assertion_eligible(%s) ok', (ids['R1-short'],)).fetchone()['ok']


def test_pattern_dependency_hidden_is_withheld_under_every_view(conn, cfg, monkeypatch):
    from dataclasses import replace
    from agentic_rag.domains import seed_defaults, add_domain
    from test_synthesis_reads import apply_k1
    seed_defaults(conn)
    add_domain(conn, 'alpha')
    conn.commit()
    env = replace(cfg, synthesis_enabled=True, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    keys, pattern = apply_k1(conn, env, monkeypatch)
    originals = [r['original_id'] for r in conn.execute('SELECT DISTINCT original_id::text FROM synthesis_dependencies'
                                                        ' ORDER BY 1').fetchall()]
    ev1 = {o: conn.execute('SELECT rag_document_version(%s) v', (o,)).fetchone()['v'] for o in originals}
    assert conn.execute('SELECT rag_pattern_current(%s) ok', (pattern,)).fetchone()['ok']
    conn.commit()
    made = apply(conn, env, originals[0], originals[1], 'semantic_duplicate')
    for view in (None, 'current', 'include_merged', 'historical'):
        with lifecycle.view_scope(conn, view):
            row = conn.execute('SELECT rag_pattern_current(%s) ok, assertion_eligible(%s) visible', (pattern, pattern)).fetchone()
        assert not row['ok'] and not row['visible'], view
        conn.rollback()
    store.correct_lifecycle(conn, env, decision_id=made['decision']['id'], expected_revision=1, reason='undo', actor='cli')
    assert conn.execute('SELECT rag_pattern_current(%s) ok', (pattern,)).fetchone()['ok']
    assert {o: conn.execute('SELECT rag_document_version(%s) v', (o,)).fetchone()['v'] for o in originals} == ev1


def test_source_aba_and_target_change_release_duplicate_members_only(conn, cfg, ids):
    label = LABELS['X1']
    apply(conn, cfg, ids['X1-short'], ids['X1-rich'], 'extension')
    key = conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s', (ids['X1-short'],)).fetchone()['source_key']
    store.set_source_state(conn, key, state='removed', reason='withdrawn')
    assert selected(conn, ids, label['pair'], 'current') == label['source_withdrawn']['current']
    store.set_source_state(conn, key, state='active', reason='reinstated')
    assert selected(conn, ids, label['pair'], 'current') == label['source_reinstated']['current']
    with db.connect(cfg, role='reader') as r:
        assert lifecycle.detail(r, ids['X1-short'])['as_member'][0]['relationship'] == 'stale'
    # Duplicate target archived: member answers through its own gates.
    apply(conn, cfg, ids['R1-short'], ids['R1-rich'], 'extension')
    store.save_document(conn, cfg, doc_id=ids['R1-rich'], title='Printer P1 toner and drum',
                        body='Printer P1 uses toner TN-243 and drum DR-243; replace the drum every 12000 pages.',
                        domain='general', dtype='memory', status='archived')
    assert selected(conn, ids, LABELS['R1']['pair'], 'current') == LABELS['R1']['target_archived']['current']


def test_research_accepts_view_and_rejects_invalid_combinations(conn, cfg, ids):
    from dataclasses import replace
    from agentic_rag.research import research
    apply(conn, cfg, ids['E1-copy'], ids['E1-keep'], 'exact_duplicate')
    conn.commit()
    offline = replace(cfg, ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    result = research(offline, 'flush the DNS cache', domain='general', project=PROJECT, view='current', strategy='lexical')
    cited = {e['document_id'] for e in result['evidence']}
    assert ids['E1-copy'] not in cited and result['lifecycle'] == {'view': 'current'}
    with pytest.raises(lifecycle.LifecycleError, match='invalid_view'):
        research(offline, 'flush the DNS cache', view='historical', as_of='2026-01-01T00:00:00Z')


def test_hidden_check_is_flat_and_snapshot_matches_document_version(conn, cfg, ids):
    # PostgreSQL 17 re-plans an SQL function nested in another non-inlined one on
    # every call; a per-row ls1/ev1 call made every hidden candidate cost about 2 ms.
    for member, target, operation in (('E1-copy', 'E1-keep', 'exact_duplicate'), ('R1-short', 'R1-rich', 'extension'),
                                      ('X1-short', 'X1-rich', 'extension')):
        apply(conn, cfg, ids[member], ids[target], operation)
    if not conn.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()['rolsuper']:
        pytest.skip('track_functions needs a superuser test owner')
    conn.execute("SET LOCAL track_functions = 'all'")
    hidden = conn.execute('SELECT count(*) n FROM documents WHERE rag_lifecycle_hidden(id)').fetchone()['n']
    calls = {name: conn.execute('SELECT COALESCE(pg_stat_get_xact_function_calls(%s::regprocedure), 0) n',
                                (name,)).fetchone()['n']
             for name in ('rag_lifecycle_snapshot(uuid)', 'rag_document_version(uuid)',
                          'rag_lifecycle_merge_holds(uuid,uuid,text,text,timestamptz)')}
    conn.rollback()
    # Only the three members reach the snapshot comparison; nothing nested per row.
    assert hidden == 3 and calls == {'rag_lifecycle_snapshot(uuid)': 0, 'rag_document_version(uuid)': 0,
                                     'rag_lifecycle_merge_holds(uuid,uuid,text,text,timestamptz)': 3}
    # One ls1 definition; its embedded ev1 is the migration030 version, row for row.
    rows = conn.execute('SELECT s.ev1 = rag_document_version(s.id) AND s.snapshot = rag_lifecycle_snapshot(s.id) ok'
                        ' FROM rag_lifecycle_snapshots s').fetchall()
    assert len(rows) == len(set(ids.values())) and all(r['ok'] for r in rows)
