"""Exact input reuse is derived; canonical ordering/transactions remain authoritative."""
from dataclasses import replace
import threading
import time

import psycopg
import pytest

from agentic_rag import db, store, embedding_reuse as reuse
from agentic_rag.chunker import chunk_markdown


@pytest.fixture
def identity(monkeypatch, conn):
    conn.execute('TRUNCATE embedding_reuse_cache')
    conn.execute("INSERT INTO domains(name) VALUES ('nature')")
    conn.commit()
    monkeypatch.setattr(reuse, 'model_digest', lambda cfg: 'a' * 64)
    return conn


def loader_recorder():
    calls = []
    def load(texts, cfg):
        calls.extend(texts)
        return [[(sum(t.encode()) % 100) / 100] * cfg.embed_dim for t in texts]
    return calls, load


def test_small_edit_embeds_only_changed_exact_chunk(identity, cfg, monkeypatch):
    calls, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    body = '\n\n'.join(f'## Part {i}\n\n' + str(i) * 950 for i in range(20))
    result = store.save_document(identity, cfg, title='Large', body=body, domain='nature', dtype='concept')
    original = chunk_markdown('# Large\n\n' + body)
    assert len(calls) == len(original)
    calls.clear()
    updated = body.replace('## Part 10', '## Revised 10')
    store.save_document(identity, cfg, title='Large', body=updated, doc_id=result.doc_id, domain='nature', dtype='concept')
    target = chunk_markdown('# Large\n\n' + updated)
    assert calls == [text for text in target if text not in original]
    actual = identity.execute('SELECT content FROM chunks WHERE document_id=%s ORDER BY idx', (result.doc_id,)).fetchall()
    assert [r['content'] for r in actual] == target


@pytest.mark.parametrize('change', ['digest', 'endpoint', 'tag', 'representation'])
def test_model_or_representation_change_invalidates(identity, cfg, monkeypatch, change):
    calls, load = loader_recorder()
    reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli')
    identity.commit()
    calls.clear()
    representation = 'raw-v1'
    if change == 'digest': monkeypatch.setattr(reuse, 'model_digest', lambda _: 'b' * 64)
    if change == 'endpoint': cfg = replace(cfg, ollama_url='http://another.invalid')
    if change == 'tag': cfg = replace(cfg, embed_model='other')
    if change == 'representation': representation = 'context-v1'
    reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli', representation=representation)
    assert calls == ['same']


def test_unknown_identity_uses_original_loader_without_cache(identity, cfg, monkeypatch):
    monkeypatch.setattr(reuse, 'model_digest', lambda _: None)
    calls, load = loader_recorder()
    reuse.vectors(identity, cfg, ['same', 'same'], loader=load, actor='cli')
    assert calls == ['same', 'same']
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0


def test_outer_rollback_discards_document_cache_audit(identity, cfg, monkeypatch):
    _, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    store.save_document(identity, cfg, title='atomic', body='body', domain='nature', dtype='concept', commit=False)
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] > 0
    identity.rollback()
    for table in ('documents', 'embedding_reuse_cache', 'audit_log'):
        assert identity.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n'] == 0


def test_bounded_parallel_inference_preserves_order(identity, cfg):
    lock = threading.Lock()
    active = peak = 0
    def load(texts, cfg):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
        assert len(texts) <= 16
        time.sleep(0.01 if texts[0] == '0' else 0.001)
        with lock: active -= 1
        return [[float(t)] * cfg.embed_dim for t in texts]
    texts = [str(i) for i in range(300)]
    vectors = reuse.vectors(identity, cfg, texts, loader=load, actor='cli')
    assert [v[0] for v in vectors] == list(range(300))
    assert peak == 2


def test_missing019_preserves_prior_uncommitted_write(identity, cfg):
    calls, load = loader_recorder()
    identity.execute('ALTER TABLE embedding_reuse_cache RENAME TO hidden_reuse')
    identity.execute("INSERT INTO documents(slug,domain,dtype,title,body) VALUES ('prior','nature','concept','prior','body')")
    assert reuse.vectors(identity, cfg, ['x'], loader=load, actor='cli') is not None
    assert calls == ['x']
    identity.rollback()
    assert identity.execute("SELECT to_regclass('embedding_reuse_cache') AS t").fetchone()['t']
    assert identity.execute('SELECT count(*) AS n FROM documents').fetchone()['n'] == 0


def test_cache_sql_failure_preserves_prior_write_and_falls_back(identity, cfg):
    calls, load = loader_recorder()
    identity.execute("INSERT INTO documents(slug,domain,dtype,title,body) VALUES ('prior','nature','concept','prior','body')")
    identity.execute('ALTER TABLE embedding_reuse_cache RENAME COLUMN embedding TO unavailable_vector')
    assert reuse.vectors(identity, cfg, ['x'], loader=load, actor='cli') is not None
    assert calls == ['x']
    assert identity.execute("SELECT slug FROM documents").fetchone()['slug'] == 'prior'
    identity.rollback()
    assert identity.execute('SELECT count(*) AS n FROM documents').fetchone()['n'] == 0


def test_contention_skips_cache_persistence_without_waiting(identity, cfg):
    other = db.connect(cfg)
    try:
        other.execute('SELECT pg_advisory_xact_lock(5840919371552421)')
        calls, load = loader_recorder()
        start = time.monotonic()
        reuse.vectors(identity, cfg, ['x'], loader=load, actor='cli')
        assert time.monotonic() - start < 2
        assert calls == ['x']
        assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0
        identity.commit()
    finally:
        other.rollback()
        other.close()


@pytest.mark.parametrize('role', ['reader', 'writer'])
def test_no_direct_cache_mutation_grants(identity, cfg, role):
    connection = db.connect(cfg, role=role)
    try:
        for privilege in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
            assert connection.execute('SELECT has_table_privilege(current_user,%s,%s) AS yes',
                ('embedding_reuse_cache', privilege)).fetchone()['yes'] is False
        yes = connection.execute("SELECT has_function_privilege(current_user,'put_embedding_reuse(text,text,text[],text[],text)','EXECUTE') AS yes").fetchone()['yes']
        assert yes is (role == 'writer')
    finally:
        connection.close()


def test_digest_drift_never_applies_cached_or_new_vectors(identity, cfg, monkeypatch):
    _, load = loader_recorder()
    reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli')
    identity.commit()
    digests = iter(['a' * 64, 'b' * 64])
    monkeypatch.setattr(reuse, 'model_digest', lambda _: next(digests))
    assert reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli') is None


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 70000, True])
def test_invalid_halfvectors_never_cache_or_apply(identity, cfg, bad):
    def load(texts, cfg): return [[bad] * cfg.embed_dim for _ in texts]
    assert reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli') is None
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0


def test_cache_does_not_commit_initially_idle_connection(identity, cfg):
    _, load = loader_recorder()
    identity.commit()
    reuse.vectors(identity, cfg, ['same'], loader=load, actor='cli')
    identity.rollback()
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0


def test_prepared_sanitized_inputs_match_gateway_and_no_preparation_writes(identity, cfg, monkeypatch):
    calls, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    title = 'key sk-abc123DEF456ghi789jkl012'
    with reuse.prepare_documents(identity, cfg, [(title, 'Signal body')], loader=load):
        assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0
        assert len(calls) == 1 and '[REDACTED]' in calls[0]
        store.save_document(identity, cfg, title=title, body='Signal body', domain='nature', dtype='concept', commit=False)
        assert len(calls) == 1
    identity.rollback()
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0


def test_preparation_excess_falls_back_without_discarding_documents(identity, cfg, monkeypatch):
    calls, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    docs = [(str(i), f'Body {i}') for i in range(20)]
    with reuse.prepare_documents(identity, cfg, docs, loader=load):
        assert len(calls) == 16
        for title, body in docs:
            store.save_document(identity, cfg, title=title, body=body, domain='nature', dtype='concept', commit=False)
    assert len(calls) == 20
    assert identity.execute('SELECT count(*) AS n FROM documents').fetchone()['n'] == 20


def test_failed_inference_keeps_originals_and_queues_retry(identity, cfg, monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *_: None)
    result = store.save_document(identity, cfg, title='original', body='evidence', domain='nature', dtype='concept')
    assert result.warnings
    assert identity.execute('SELECT body FROM documents').fetchone()['body'] == 'evidence'
    assert identity.execute("SELECT count(*) AS n FROM mining_queue WHERE kind='embed'").fetchone()['n'] == 1
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 0


def test_cache_capacity_eviction_is_audited_and_outer_rollback_safe(identity, cfg):
    # Owned fault fixture lowers capacity; actual cache function/gateway stays in use.
    definition = identity.execute("SELECT pg_get_functiondef('put_embedding_reuse(text,text,text[],text[],text)'::regprocedure) AS d").fetchone()['d']
    identity.execute(definition.replace('count(*)-8192', 'count(*)-3'))
    _, load = loader_recorder()
    reuse.vectors(identity, cfg, ['a', 'b', 'c', 'd', 'e'], loader=load, actor='cli')
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 3
    assert 'evicted=2' in identity.execute("SELECT summary FROM audit_log WHERE op='embedding_reuse'").fetchone()['summary']
    identity.rollback()
    assert 'count(*)-8192' in identity.execute("SELECT pg_get_functiondef('put_embedding_reuse(text,text,text[],text[],text)'::regprocedure) AS d").fetchone()['d']


def test_independent_batch_writers_do_not_wait_on_shared_cache_keys(identity, cfg, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    barrier = threading.Barrier(2)
    _, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    def apply(actor):
        with db.connect(cfg, role='writer') as writer:
            writer.execute("SET statement_timeout='3s'")
            store.save_document(writer, cfg, title='shared', body='same', slug=actor+'-a', domain='nature', dtype='concept', actor=actor, commit=False)
            barrier.wait(timeout=4)
            store.save_document(writer, cfg, title='shared', body='same', slug=actor+'-b', domain='nature', dtype='concept', actor=actor, commit=False)
            writer.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(apply, 'user-a'), pool.submit(apply, 'user-b')
        a.result(timeout=8)
        b.result(timeout=8)
    assert identity.execute('SELECT count(*) AS n FROM documents').fetchone()['n'] == 4
    assert identity.execute('SELECT count(*) AS n FROM embedding_reuse_cache').fetchone()['n'] == 1


def test_context_scope_change_invalidates_exact_representation(identity, cfg, monkeypatch):
    from agentic_rag import embed
    calls, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    monkeypatch.setattr(embed, 'try_embed_texts', load)
    fields = dict(title='Orion', body='port 8766', domain='nature', dtype='reference')
    result = store.save_document(identity, cfg, **fields, project='/a')
    options = dict(fields, doc_id=result.doc_id, index_context=True)
    store.save_document(identity, cfg, **options)
    old_context = calls[-1]
    calls.clear()
    store.set_project_scope(identity, result.doc_id, project='/b')
    store.save_document(identity, cfg, **options)
    assert len(calls) == 1 and calls[0] != old_context
    assert 'Project: b\n' in calls[0] and 'Project: a\n' not in calls[0]


def test_reembed_source_changed_during_preprocessing_preserves_new_save(identity, cfg, monkeypatch):
    _, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    fields = dict(title='original', body='body', domain='nature', dtype='concept')
    result = store.save_document(identity, cfg, **fields)
    # Force a different identity/cache miss to exercise an actual concurrent edit.
    monkeypatch.setattr(reuse, 'model_digest', lambda _: 'b' * 64)
    def changed(texts, cfg):
        with db.connect(cfg, role='writer') as other:
            store.save_document(other, cfg, **dict(fields, body='newer body'), doc_id=result.doc_id)
        return load(texts, cfg)
    monkeypatch.setattr(store, 'embed_texts', changed)
    with pytest.raises(ValueError, match='source changed'):
        store.reembed_document(identity, cfg, result.doc_id)
    assert identity.execute('SELECT body FROM documents WHERE id=%s', (result.doc_id,)).fetchone()['body'] == 'newer body'
    assert identity.execute("SELECT count(*) AS n FROM audit_log WHERE op='reembed'").fetchone()['n'] == 0


def test_unknown_identity_fallback_obeys_process_concurrency_bound(identity, cfg, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(reuse, 'model_digest', lambda _: None)
    # No connection may cross a thread; each caller owns its own transaction.
    lock = threading.Lock()
    active = peak = 0
    def load(texts, cfg):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.03)
        with lock: active -= 1
        return [[1.] * cfg.embed_dim for _ in texts]
    def run(_):
        with db.connect(cfg) as connection:
            return reuse.vectors(connection, cfg, ['x'] * 20, loader=load, actor='cli')
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(len(v) == 20 for v in pool.map(run, range(4)))
    assert peak == 2


def test_mining_prepares_final_signal_input_but_dedup_stays_sequential(identity, cfg, monkeypatch):
    from agentic_rag import mining
    calls, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    seen = []
    def dedup(connection, cfg, title, body, domain, project):
        seen.append((body, connection.execute('SELECT count(*) AS n FROM documents').fetchone()['n']))
        return None
    monkeypatch.setattr(mining, '_near_duplicate', dedup)
    ext = mining.parse_extraction({'memories': [{'title':'First','body':'original','domain':'nature','edges':[]}],
        'signals':[{'title':'Second','body':'source','signal':'explicit signal','domain':'nature','edges':[]}]}, {'nature'})
    with reuse.measure() as metrics:
        mining._apply_extraction(identity, cfg, ext, session_id='test', project='/a', batch_id='b', output_cursor='c')
    assert seen == [('original', 0), ('source', 1)]
    assert len(calls) == 2 and '## Signal\n\nexplicit signal' in calls[-1]
    assert metrics.generated_inputs == 2 and metrics.prepared_inputs == 2 and metrics.cache_inputs == 0
    identity.rollback()


def test_metrics_distinguish_cache_hits_from_prepared_consumption(identity, cfg, monkeypatch):
    _, load = loader_recorder()
    monkeypatch.setattr(store, 'try_embed_texts', load)
    documents = [('one', 'a'), ('two', 'b')]
    for title, body in documents:
        store.save_document(identity, cfg, title=title, body=body, domain='nature', dtype='concept')
    with reuse.measure() as metrics:
        with reuse.prepare_documents(identity, cfg, documents, loader=load):
            for title, body in documents:
                store.save_document(identity, cfg, title=title, body=body, domain='nature', dtype='concept', commit=False)
    assert metrics.generated_inputs == 0 and metrics.cache_inputs == 2 and metrics.prepared_inputs == 2
    identity.rollback()
