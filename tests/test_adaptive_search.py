"""Adaptive routes must preserve eligibility and actual returned evidence."""
from dataclasses import replace

import pytest

from agentic_rag import db, mcp_server, search, store
from agentic_rag.domains import seed_defaults


@pytest.fixture(autouse=True)
def isolated_store(conn, monkeypatch):
    seed_defaults(conn)
    conn.execute("INSERT INTO domains(name) VALUES ('other')")
    conn.commit()
    monkeypatch.setattr(store, 'try_embed_texts', lambda *args: None)


def save(conn, cfg, *, title='Selected knowledge', body='TargetError42 needs restart.',
         slug='selected-knowledge', domain='general', project='/adaptive/a', **kwargs):
    return store.save_document(conn, cfg, title=title, body=body, slug=slug,
                               domain=domain, dtype='memory', project=project, **kwargs)


def forbid_embedding(monkeypatch):
    def forbidden(*args):
        pytest.fail('fast-path evidence must not invoke inference')
    monkeypatch.setattr(search, 'try_embed_texts', forbidden)


@pytest.mark.parametrize('selector', ['id', 'slug'])
def test_exact_selector_returns_source_without_embedding(conn, cfg, monkeypatch, selector):
    doc = save(conn, cfg)
    forbid_embedding(monkeypatch)
    hits, warnings = search.search(conn, cfg, doc.doc_id if selector == 'id' else doc.slug,
                                   project='/adaptive/a')
    assert [h.document_id for h in hits] == [doc.doc_id]
    assert 'TargetError42 needs restart.' in hits[0].snippet
    assert warnings == []
    assert hits[0].citation.startswith(doc.doc_id + '#' + hits[0].chunk_id + ':')


def test_error_symbol_returns_late_original_span_without_embedding(conn, cfg, monkeypatch):
    doc = save(conn, cfg, body='padding ' * 180 + 'TargetError42 needs restart.')
    forbid_embedding(monkeypatch)
    hits, warnings = search.search(conn, cfg, 'TargetError42', project='/adaptive/a')
    assert [h.document_id for h in hits] == [doc.doc_id]
    hit = hits[0]
    raw = conn.execute('SELECT content FROM chunks WHERE id=%s', (hit.chunk_id,)).fetchone()['content']
    assert hit.snippet_start > 400 and 'TargetError42' in hit.snippet
    assert raw[hit.snippet_start:hit.snippet_end] == hit.snippet
    assert warnings == []


@pytest.mark.parametrize('selector', ['selected-knowledge', 'TargetError42'])
@pytest.mark.parametrize('restriction', [{'project': '/adaptive/b'}, {'domain': 'other'}, {'scope': 'global'}])
def test_fast_paths_cannot_bypass_scope_or_domain(conn, cfg, monkeypatch, selector, restriction):
    save(conn, cfg)
    calls = []
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: calls.append(True) or None)
    assert search.search(conn, cfg, selector, **restriction)[0] == []
    assert calls == [True]  # no eligible shortcut: preserve ordinary fallback


@pytest.mark.parametrize('query', ['missing-document-slug', 'AbsentError42', 'plain question', 'TargetError42 restart'])
def test_missing_and_natural_queries_keep_existing_embedding_fallback(conn, cfg, monkeypatch, query):
    save(conn, cfg)
    calls = []
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: calls.append(True) or None)
    _, warnings = search.search(conn, cfg, query, project='/adaptive/a')
    assert calls == [True]
    assert warnings == ['embedding unavailable — full-text search only']


def test_explicit_hybrid_and_lexical_strategies(conn, cfg, monkeypatch):
    doc = save(conn, cfg)
    calls = []
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: calls.append(True) or None)
    hybrid, warnings = search.search(conn, cfg, 'TargetError42', strategy='hybrid')
    assert [h.document_id for h in hybrid] == [doc.doc_id] and calls == [True]
    assert warnings == ['embedding unavailable — full-text search only']
    calls.clear()
    lexical, warnings = search.search(conn, cfg, 'TargetError42', strategy='lexical')
    assert [h.citation for h in lexical] == [h.citation for h in hybrid]
    assert calls == [] and warnings == []


@pytest.mark.parametrize('strategy', ['', 'unknown', None, True])
def test_invalid_strategy_rejected_before_any_work(cfg, monkeypatch, strategy):
    forbid_embedding(monkeypatch)
    with pytest.raises(ValueError, match='strategy'):
        search.search(None, cfg, 'TargetError42', strategy=strategy)


def test_legacy_baseline_keeps_embedding_behavior(conn, cfg, monkeypatch):
    doc = save(conn, cfg)
    calls = []
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: calls.append(True) or None)
    hits, warnings = search.search(conn, cfg, 'TargetError42', baseline=True)
    assert doc.doc_id in {h.document_id for h in hits}
    assert calls == [True] and warnings


def test_expired_assertion_excluded_current_and_available_as_of(conn, cfg, monkeypatch):
    fact = store.save_assertion(conn, cfg, entity='service', attribute='status',
        value='ExpiredError42', domain='general', project='/adaptive/a',
        event_at='2025-01-01T00:00:00Z', expires_at='2025-02-01T00:00:00Z',
        evidence={'source_id':'expiry-case','role':'user','quote':'ExpiredError42'})
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: None)
    assert search.search(conn, cfg, fact.doc_id, project='/adaptive/a')[0] == []
    forbid_embedding(monkeypatch)
    assert search.search(conn, cfg, fact.doc_id, project='/adaptive/a',
                         as_of='2025-01-15T00:00:00Z')[0][0].document_id == fact.doc_id
    assert search.search(conn, cfg, 'ExpiredError42', project='/adaptive/a', history=True)[0][0].document_id == fact.doc_id


def test_refuted_claim_source_is_not_returned_by_id_or_symbol(conn, cfg, monkeypatch):
    from agentic_rag import evidence
    text = 'RefutedError42 needs restart.'
    doc = store.save_claim(conn, cfg, title='Refuted', body=text, domain='general',
        dtype='memory', project='/adaptive/a', claim_kind='stated',
        evidence=[{'namespace':'synthetic','source_id':'refuted-case','role':'user','quote':text,'complete':True}])
    store.set_source_state(conn, evidence.sources(conn, doc.doc_id)[0]['source_key'],
                           state='refuted', reason='controlled test correction')
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: None)
    for query in (doc.doc_id, doc.slug, 'RefutedError42'):
        assert search.search(conn, cfg, query, project='/adaptive/a')[0] == []


def test_archived_exact_target_cannot_shortcut(conn, cfg, monkeypatch):
    doc = save(conn, cfg)
    store.save_document(conn, cfg, title='Selected knowledge', body='TargetError42 needs restart.',
        domain='general', dtype='memory', doc_id=doc.doc_id, status='archived')
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: None)
    for query in (doc.doc_id, doc.slug, 'TargetError42'):
        assert search.search(conn, cfg, query, project='/adaptive/a')[0] == []


def test_reader_role_old_mcp_call_shape_and_reranker_fallback(conn, cfg, hook_env, monkeypatch):
    doc = save(conn, cfg, project=None, scope='global')
    forbid_embedding(monkeypatch)
    with db.connect(cfg, role='reader') as reader:
        hits, warnings = search.search(reader, cfg, doc.slug,
            reranker=lambda hits: [replace(h, body='invalid') for h in hits])
        assert [h.document_id for h in hits] == [doc.doc_id]
        assert any('reranker' in w for w in warnings)
        with pytest.raises(Exception):
            reader.execute("UPDATE documents SET title='not permitted'")
        reader.rollback()
    result = mcp_server.memory_search('TargetError42')
    assert set(result) == {'results', 'warnings'}
    assert result['results'][0]['document_id'] == doc.doc_id


def test_cli_strategy_and_invalid_mcp_inputs(conn, cfg, hook_env, monkeypatch, capsys):
    import json
    from agentic_rag.cli import main
    doc = save(conn, cfg, project=None, scope='global')
    forbid_embedding(monkeypatch)
    assert main(['search', 'TargetError42', '--strategy', 'lexical', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['results'][0]['document_id'] == doc.doc_id
    assert result['warnings'] == []
    with pytest.raises(SystemExit) as invalid:
        main(['search', 'TargetError42', '--strategy', 'invalid'])
    assert invalid.value.code == 2
    monkeypatch.setattr(mcp_server, '_connect', lambda: pytest.fail('must validate before DB'))
    with pytest.raises(ValueError, match='strategy'):
        mcp_server.memory_search('TargetError42', strategy='invalid')


def test_populated_store_upgrade_mixed_readers_and_rollback(conn, cfg, monkeypatch):
    """Code-only switch on persisted representative state, no fresh install shortcut."""
    from concurrent.futures import ThreadPoolExecutor
    from agentic_rag import jobs, pins
    from agentic_rag.continuity.model import CheckpointSnapshot
    from agentic_rag.continuity import store as checkpoints
    first = save(conn, cfg, body='UpgradeError42 retains original knowledge.',
                 slug='upgrade-primary', provenance={'actor': 'user-a'})
    save(conn, cfg, title='Other user', body='PrivateError42 is isolated.',
         slug='upgrade-other', domain='other', project='/adaptive/b',
         provenance={'actor': 'user-b'})
    save(conn, cfg, title='Global', body='GlobalError42 is shared.',
         slug='upgrade-global', project=None, scope='global')
    pins.add_pin(conn, document_id=first.doc_id, scope='/adaptive/a')
    checkpoints.upsert_snapshot(conn, CheckpointSnapshot(session_id='upgrade-session',
        turn_id='upgrade-turn', cursor='upgrade-cursor', source='test', trigger='manual',
        cwd='/adaptive/a', project_root='/adaptive/a', transcript_fingerprint='sha256:synthetic',
        git={'branch':'old'}, artifacts=('CLAUDE.md',)))
    jobs.enqueue_curate(conn, reason='pending work retained')
    tables = [r['tablename'] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
    def snapshot():
        # Full row comparisons include vectors, sources, audit, pins, checkpoints, jobs.
        from psycopg import sql
        return {table: conn.execute(sql.SQL('SELECT to_jsonb(t) row FROM {} t ORDER BY to_jsonb(t)::text')
                                    .format(sql.Identifier(table))).fetchall() for table in tables}
    before = snapshot()
    monkeypatch.setattr(search, 'try_embed_texts', lambda *args: None)
    def read(strategy):
        with db.connect(cfg, role='reader') as reader:
            reader.execute('SET TRANSACTION READ ONLY')
            hits, _ = search.search(reader, cfg, 'UpgradeError42', strategy=strategy,
                                    project='/adaptive/a')
            assert [h.document_id for h in hits] == [first.doc_id]
            assert search.search(reader, cfg, 'PrivateError42', strategy=strategy,
                                 project='/adaptive/a')[0] == []
            return [h.citation for h in hits]
    with ThreadPoolExecutor(max_workers=2) as pool:
        legacy = pool.submit(read, 'hybrid')
        upgraded = pool.submit(read, 'auto')
        assert legacy.result() == upgraded.result()
    assert read('hybrid') == read('auto')  # rollback preserves old retrieval
    assert snapshot() == before
