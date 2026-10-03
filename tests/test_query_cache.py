"""Cache inference, never authority: every result rechecks persisted eligibility."""
from collections import Counter
import json

import httpx
import pytest

from agentic_rag import embed, mcp_server, store
from agentic_rag.domains import seed_defaults
from agentic_rag import query_cache
from agentic_rag.config import Config


@pytest.fixture
def cached_mcp(conn, cfg, hook_env, monkeypatch):
    mcp_server._QUERY_CACHE.clear()
    seed_defaults(conn)
    conn.commit()
    monkeypatch.setenv('RAG_READONLY', '1')
    monkeypatch.setattr(store, 'try_embed_texts', lambda *args: None)
    calls = Counter()
    model = {'digest': 'a'*64}
    def handler(request):
        calls[request.url.path] += 1
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models':[{'name':'bge-m3:latest', **model}]})
        assert request.url.path == '/api/embed'
        body = json.loads(request.content)
        return httpx.Response(200, json={'embeddings':[[1.0]*1024 for _ in body['input']]})
    monkeypatch.setattr(embed, '_client', lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls, model


def document(conn, cfg, **kwargs):
    return store.save_document(conn, cfg, title=kwargs.pop('title', 'Cached question'),
        body='cached semantic question is evidence from the original source.',
        dtype='memory', domain=kwargs.pop('domain', 'general'), **kwargs)


def test_repeat_mcp_query_reuses_only_inference(conn, cfg, cached_mcp):
    calls, _ = cached_mcp
    doc = document(conn, cfg, scope='global')
    first = mcp_server.memory_search('cached semantic question')
    second = mcp_server.memory_search('cached semantic question')
    assert first == second
    assert first['results'][0]['document_id'] == doc.doc_id
    assert calls['/api/embed'] == 1
    assert calls['/api/tags'] == 3  # before/after inference, then on every reuse


@pytest.mark.parametrize('trial', range(20))
def test_correction_after_cache_hit_is_immediately_effective(conn, cfg, cached_mcp, trial):
    from agentic_rag.evidence import sources
    from agentic_rag import db,search
    from agentic_rag.config import load_config
    calls, _ = cached_mcp
    text = 'cached semantic question is evidence from the original source.'
    doc = store.save_claim(conn, cfg, title='Cached claim', body=text, dtype='memory',
        domain='general', scope='global', claim_kind='stated',
        evidence=[{'namespace':'synthetic','source_id':'cache-correction','role':'user','quote':text,'complete':True}])
    assert mcp_server.memory_search('cached semantic question')['results'][0]['document_id'] == doc.doc_id
    assert calls['/api/embed']==1
    with db.connect(cfg,role='reader') as reader:
        assert search.search(reader,load_config(),'cached semantic question')[0][0].document_id==doc.doc_id
    assert calls['/api/embed']==2
    store.set_source_state(conn, sources(conn, doc.doc_id)[0]['source_key'],
        state='refuted', reason='Synthetic correction')
    assert mcp_server.memory_search('cached semantic question')['results'] == []
    assert calls['/api/embed'] == 2  # correction lookup reused vector, not results
    with db.connect(cfg,role='reader') as reader:
        assert search.search(reader,load_config(),'cached semantic question')[0]==[]
    assert calls['/api/embed']==3  # one cached vs two uncached inference calls per pair


def test_project_domain_and_role_boundaries(conn, cfg, cached_mcp, monkeypatch):
    calls, _ = cached_mcp
    conn.execute("INSERT INTO domains(name) VALUES ('other')")
    conn.commit()
    a = document(conn, cfg, project='/cache/a', slug='cache-project-a')
    b = document(conn, cfg, project='/cache/b', slug='cache-project-b', domain='other')
    for _ in range(2):
        for project, domain, expected in [('/cache/a','general',a.doc_id),('/cache/b','other',b.doc_id)]:
            result = mcp_server.memory_search('cached semantic question', project=project, domain=domain)
            assert [h['document_id'] for h in result['results']] == [expected]
    assert calls['/api/embed'] == 2
    monkeypatch.setenv('RAG_READONLY', '0')
    result = mcp_server.memory_search('cached semantic question', project='/cache/a', domain='general')
    assert [h['document_id'] for h in result['results']] == [a.doc_id]
    assert calls['/api/embed'] == 3


def test_model_replacement_invalidates_mcp_cache(conn, cfg, cached_mcp):
    calls, model = cached_mcp
    document(conn, cfg, scope='global')
    mcp_server.memory_search('cached semantic question')
    model['digest'] = 'b'*64
    mcp_server.memory_search('cached semantic question')
    mcp_server.memory_search('cached semantic question')
    assert calls['/api/embed'] == 2


def test_expiry_without_write_after_cached_mcp_lookup(conn, cfg, cached_mcp, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from agentic_rag import validity
    calls, _ = cached_mcp
    now = datetime.now(timezone.utc)
    fact = store.save_assertion(conn, cfg, entity='cache-service', attribute='status',
        value='cached semantic question', domain='general', scope='global',
        event_at=(now-timedelta(days=1)).isoformat(), expires_at=(now+timedelta(hours=1)).isoformat(),
        evidence={'source_id':'cache-expiry','role':'user','quote':'cached semantic question'})
    assert mcp_server.memory_search('cached semantic question')['results'][0]['document_id'] == fact.doc_id
    original = validity.selection
    monkeypatch.setattr(validity, 'selection', lambda as_of, history: (now+timedelta(hours=2), history))
    assert mcp_server.memory_search('cached semantic question')['results'] == []
    assert calls['/api/embed'] == 1
    monkeypatch.setattr(validity, 'selection', original)


@pytest.fixture
def cache_unit(monkeypatch):
    model = {'digest': 'a'*64}
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: model['digest'])
    return query_cache.QueryCache(capacity=2, ttl=10), Config(embed_dim=3), model


def test_capacity_ttl_context_and_defensive_copy(cache_unit, monkeypatch):
    cache, cfg, _ = cache_unit
    clock = [100.0]
    monkeypatch.setattr(query_cache.time, 'monotonic', lambda: clock[0])
    calls = []
    def load(texts, cfg):
        calls.append(texts[0]); return [[1.0,2.0,3.0]]
    get = lambda q, context='reader': cache.vectors(q,cfg,context,load)
    value = get('one'); value[0][0] = 999
    assert get('one') == [[1.0,2.0,3.0]] and calls == ['one']
    get('two'); get('one'); get('three'); get('two')
    assert calls == ['one','two','three','two']  # LRU eviction
    get('two','writer'); assert calls[-1] == 'two' and len(calls) == 5
    clock[0] += 10
    get('two','writer'); assert len(calls) == 6
    assert len(cache._entries) == 1  # expired entries swept


def test_failed_metadata_or_inference_not_cached(cache_unit):
    cache, cfg, model = cache_unit
    calls = []
    load = lambda *args: calls.append(True) or None
    assert cache.vectors('one',cfg,'reader',load) is None
    assert cache.vectors('one',cfg,'reader',load) is None
    assert len(calls) == 2
    model['digest'] = None
    load = lambda *args: calls.append(True) or [[1.,2.,3.]]
    assert cache.vectors('one',cfg,'reader',load) == [[1.,2.,3.]]
    assert cache.vectors('one',cfg,'reader',load) == [[1.,2.,3.]]
    assert len(calls) == 4 and not cache._entries


def test_model_swap_during_inference_cannot_poison_cache(cache_unit):
    cache, cfg, model = cache_unit
    calls = []
    def load(*args):
        calls.append(True)
        model['digest'] = 'b'*64
        return [[1.,2.,3.]]
    cache.vectors('one',cfg,'reader',load)
    assert not cache._entries
    model['digest'] = 'a'*64
    cache.vectors('one',cfg,'reader',load)
    assert len(calls) == 2


def test_simultaneous_identical_misses_share_one_vector(cache_unit):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    cache, cfg, _ = cache_unit
    entered, release = threading.Event(), threading.Event()
    calls = []
    def load(*args):
        calls.append(True); entered.set()
        assert release.wait(3)
        return [[1.,2.,3.]]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(cache.vectors,'one',cfg,'reader',load) for _ in range(3)]
        assert entered.wait(3)
        release.set()
        values = [future.result(timeout=3) for future in futures]
    assert calls == [True] and values == [[[1.,2.,3.]]]*3
    values[0][0][0] = 0
    assert values[1][0][0] == 1


@pytest.mark.parametrize('payload', [None, {}, {'models':42}, {'models':[{}]},
                                   {'models':[{'name':'bge-m3:latest','digest':'invalid'}]}])
def test_malformed_metadata_is_safe_uncached_fallback(monkeypatch, payload):
    monkeypatch.setattr(embed,'_client',lambda: httpx.Client(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))))
    assert query_cache.model_digest(Config()) is None


def test_transport_reused_closed_and_fork_state_reset():
    embed.close_transport()
    with embed._client() as first:
        pass
    with embed._client() as second:
        assert first is second and not first.is_closed
    embed.close_transport()
    assert first.is_closed
    with embed._client() as third:
        assert third is not first
    # Child callback discards inherited locks/sockets; parent retains its object.
    embed._after_fork()
    with embed._client() as fourth:
        assert fourth is not third
    third.close()
    embed.close_transport()


def test_transient_caches_collect_and_child_resets(cache_unit):
    import gc
    import weakref
    cache, cfg, _ = cache_unit
    cache.vectors('one',cfg,'reader',lambda *args:[[1.,2.,3.]])
    inherited_lock = cache._lock
    query_cache._after_fork()
    assert not cache._entries and cache._lock is not inherited_lock
    transient = query_cache.QueryCache()
    ref = weakref.ref(transient)
    del transient
    gc.collect()
    assert ref() is None


@pytest.mark.parametrize('failure', [None, 'exception'])
def test_coalesced_failure_releases_waiters_and_recovers(cache_unit, monkeypatch, failure):
    from concurrent.futures import ThreadPoolExecutor, Future
    import threading
    cache, cfg, _ = cache_unit
    entered, waiting, release = threading.Event(), threading.Event(), threading.Event()
    class ObservedFuture(Future):
        def result(self, *args, **kwargs):
            waiting.set()
            return super().result(*args, **kwargs)
    monkeypatch.setattr(query_cache,'Future',ObservedFuture)
    def load(*args):
        entered.set(); assert release.wait(3)
        if failure:raise RuntimeError('synthetic inference failure')
        return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner=pool.submit(cache.vectors,'one',cfg,'reader',load)
        assert entered.wait(3)
        waiter=pool.submit(cache.vectors,'one',cfg,'reader',load)
        assert waiting.wait(3)
        release.set()
        for future in (owner,waiter):
            if failure:
                with pytest.raises(RuntimeError,match='synthetic'):future.result(timeout=3)
            else:assert future.result(timeout=3) is None
    assert not cache._inflight and not cache._entries
    assert cache.vectors('one',cfg,'reader',lambda *args:[[1.,2.,3.]]) == [[1.,2.,3.]]


def test_inflight_pressure_falls_back_without_evicting_active_request(cache_unit):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    cache,cfg,_=cache_unit
    cache.max_inflight=1
    entered,release=threading.Event(),threading.Event()
    def load(texts,cfg):
        if texts==['one']:
            entered.set(); assert release.wait(3)
        return [[1.,2.,3.]]
    with ThreadPoolExecutor(max_workers=1) as pool:
        active=pool.submit(cache.vectors,'one',cfg,'reader',load)
        assert entered.wait(3)
        assert cache.vectors('two',cfg,'reader',load)==[[1.,2.,3.]]
        assert len(cache._inflight)==1 and not cache._entries
        release.set(); assert active.result(timeout=3)==[[1.,2.,3.]]
    assert not cache._inflight and len(cache._entries)==1


def test_populated_mcp_cached_and_uncached_readers_rollback_preserves_state(conn,cfg,cached_mcp):
    """Existing gateway-seeded knowledge, pin, checkpoint and queue survive code reuse."""
    from concurrent.futures import ThreadPoolExecutor
    from psycopg import sql
    from agentic_rag import db,jobs,pins,search
    from agentic_rag.config import load_config
    from agentic_rag.continuity import store as checkpoints
    from agentic_rag.continuity.model import CheckpointSnapshot
    from agentic_rag.domains import add_domain
    add_domain(conn,'programming','Second user domain',actor='test')
    a=document(conn,cfg,project='/cache/a',provenance={'actor':'user-a'})
    document(conn,cfg,project='/cache/b',domain='programming',title='Other user',provenance={'actor':'user-b'})
    pins.add_pin(conn,document_id=a.doc_id,scope='/cache/a')
    checkpoints.upsert_snapshot(conn,CheckpointSnapshot(session_id='cache-upgrade',turn_id='t',
        cursor='c',source='test',trigger='manual',cwd='/cache/a',project_root='/cache/a',
        transcript_fingerprint='sha256:synthetic',git={},artifacts=('AGENTS.md',)))
    jobs.enqueue_curate(conn,reason='cache-upgrade retained queue')
    tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
    def snapshot():
        return {t:conn.execute(sql.SQL('SELECT to_jsonb(t) row FROM {} t ORDER BY to_jsonb(t)::text')
            .format(sql.Identifier(t))).fetchall() for t in tables}
    before=snapshot()
    def uncached():
        with db.connect(cfg,role='reader') as reader:
            reader.execute('SET TRANSACTION READ ONLY')
            return [h.citation for h in search.search(reader,load_config(),'cached semantic question',project='/cache/a')[0]]
    def cached():
        return [h['citation'] for h in mcp_server.memory_search('cached semantic question',project='/cache/a')['results']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        old,new=pool.submit(uncached),pool.submit(cached)
        assert old.result(timeout=3)==new.result(timeout=3)
    assert cached()==uncached()  # uncached rollback needs no state migration
    assert snapshot()==before
