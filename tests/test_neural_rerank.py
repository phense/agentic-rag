"""Neural ordering cannot replace original eligible evidence or widen its scope."""
import json
from dataclasses import replace

import httpx
import pytest

from agentic_rag import search, store
from agentic_rag.domains import seed_defaults
from agentic_rag import neural_rerank
from agentic_rag.config import Config, load_config

MODEL = 'agentic-rag-qwen3-reranker-0.6b-q8'


@pytest.fixture
def local_model(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def handler(request):
        calls.append(request)
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': MODEL}]})
        assert request.url.path == '/v1/rerank'
        data = json.loads(request.content)
        results = [{'index': i, 'relevance_score': .9 if 'EXPECTED' in text else .1,
                    'document': {'text':'FORGED'}, 'provenance': {'role':'admin'}}
                   for i, text in enumerate(data['documents'])]
        return httpx.Response(200, json={'model': MODEL, 'results': results})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    return calls


@pytest.fixture
def candidates(conn, cfg, monkeypatch):
    seed_defaults(conn)
    conn.commit()
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)
    for i in range(4):
        store.save_document(conn, cfg, title=f'newsletter authentication failure {i}',
            slug=f'neural-distractor-{i}', body='newsletter authentication failure repeated.',
            dtype='memory', domain='general', scope='global')
    return store.save_document(conn, cfg, title='Original recovery evidence',
        slug='neural-expected', body='EXPECTED: newsletter authentication failure requires checking dated files.',
        dtype='memory', domain='general', scope='global')


def test_auto_model_ordering_preserves_original_payload(conn, cfg, candidates, local_model):
    """Ignoring model order loses the relevant source; replacing payload loses citations."""
    query = 'newsletter authentication failure'
    before, _ = search.search(conn, cfg, query, strategy='hybrid', k=5, context_mode='off')
    assert candidates.doc_id in {h.document_id for h in before}
    assert before[0].document_id != candidates.doc_id
    after, _ = search.search(conn, cfg, query, k=5, context_mode='off')
    assert after[0].document_id == candidates.doc_id
    assert sorted(after, key=lambda h: h.chunk_id) == sorted(before, key=lambda h: h.chunk_id)
    assert len(local_model) == 2


def test_cli_mode_preserves_off_order_and_activates_available_model(conn,cfg,hook_env,candidates,local_model,capsys):
    from agentic_rag import cli
    args=['search','newsletter authentication failure','-k','5','--json']
    assert cli.main(args+['--rerank','off'])==0
    before=json.loads(capsys.readouterr().out)
    assert before['results'][0]['document_id'] != candidates.doc_id
    assert local_model==[]
    assert cli.main(args)==0
    after=json.loads(capsys.readouterr().out)
    assert after['results'][0]['document_id']==candidates.doc_id
    assert sorted(after['results'],key=lambda h:h['chunk_id'])==sorted(before['results'],key=lambda h:h['chunk_id'])


def unit_hits(count=15):
    return [search.SearchHit(str(i), str(i), 'title', 'slug', 'general', 'memory',
        'EXPECTED' if i == 11 else 'original source ' * 200, 1/(61+i), None, {})
        for i in range(count)]


def test_candidate_tail_size_ties_and_payloads(local_model):
    """More than twelve candidates, model response order and ties cannot lose originals."""
    hits = unit_hits()
    ranked = neural_rerank.order('a multilingual recovery question', hits, Config())
    assert [h.document_id for h in ranked] == ['11'] + [str(i) for i in range(11)] + ['12','13','14']
    assert all(h is hits[int(h.document_id)] for h in ranked)
    data = json.loads(local_model[-1].content)
    assert len(data['documents']) == 12 and max(map(len, data['documents'])) == 1200


@pytest.mark.parametrize('query,hits', [('', unit_hits()), ('one two', unit_hits()),
    ('long query ' * 60, unit_hits()), ('valid query terms', []),
    ('valid query terms', unit_hits(2)),
    ('valid query terms', [replace(h, document_id='one') for h in unit_hits()]),
    ('valid query terms', [replace(h, score=.1 if i else 1) for i,h in enumerate(unit_hits())])])
def test_policy_bypasses_do_not_infer(query, hits, local_model):
    assert neural_rerank.order(query, hits, Config()) == hits
    assert local_model == []


def test_two_chunks_from_one_clear_source_are_not_ambiguity(local_model):
    hits=unit_hits(5)
    hits[0]=replace(hits[0],score=1)
    hits[1]=replace(hits[1],document_id=hits[0].document_id,score=.99)
    hits[2:]=[replace(h,score=.1) for h in hits[2:]]
    assert neural_rerank.order('ordinary query question',hits,Config())==hits
    assert local_model == []


@pytest.mark.parametrize('options', [{'strategy':'hybrid'}, {'strategy':'lexical'},
    {'rerank_mode':'off'}, {'baseline':True}])
def test_explicit_previous_routes_bypass_model(conn, cfg, candidates, local_model, options):
    search.search(conn, cfg, 'newsletter authentication failure', **options)
    assert local_model == []


@pytest.mark.parametrize('selector', ['slug', 'uuid', 'symbol'])
def test_exact_selectors_and_symbol_queries_bypass_model(conn, cfg, candidates, local_model, selector):
    query = {'slug': candidates.slug, 'uuid': candidates.doc_id,
             'symbol': 'newsletter authentication RuntimeError'}[selector]
    search.search(conn, cfg, query)
    assert local_model == []


def mock_async(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(
        transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize('payload', [None, {}, {'model':'changed','results':[]},
    {'model':MODEL,'results':[]}, {'model':MODEL,'results':[{'index':0,'relevance_score':.9}]*12},
    {'model':MODEL,'results':[None]*12},
    *[{'model':MODEL,'results':[{'index':i,'relevance_score':score} for i in range(12)]}
      for score in [True, '0.9', -1, 1.1, float('nan'), float('inf')]],
    *[{'model':MODEL,'results':[{'index':bad if i==0 else i,'relevance_score':.5} for i in range(12)]}
      for bad in [True, '0', -1, 12]]])
def test_invalid_scores_restore_complete_original_order(monkeypatch, payload):
    def handler(req):
        if req.url.path == '/v1/models':
            return httpx.Response(200,json={'data':[{'id':MODEL}]})
        return httpx.Response(200, content=json.dumps(payload).encode())
    mock_async(monkeypatch, handler)
    from agentic_rag.retrieval import rerank
    hits, warnings = unit_hits(), []
    assert rerank(hits, lambda hs: neural_rerank.order('ordinary query question',hs,Config()), warnings) == hits
    assert warnings == ['local reranker unavailable or invalid — deterministic hybrid fallback']


@pytest.mark.parametrize('url', ['https://127.0.0.1:8766', 'http://localhost:8766',
    'http://example.com', 'http://127.0.0.1.example.com', 'http://127.0.0.1@remote.test',
    'http://secret:password@127.0.0.1', 'http://127.0.0.1/path',
    'http://127.0.0.1?token=secret', 'http://127.0.0.1#secret', 'http://127.0.0.1:99999',
    'http://127.0.0.1:8766?', 'http://127.0.0.1:8766#'])
def test_nonlocal_credentials_or_modified_origins_never_receive_passages(url, local_model):
    from agentic_rag.retrieval import rerank
    hits, warnings = unit_hits(), []
    assert rerank(hits, lambda hs: neural_rerank.order('ordinary query question',hs,
        Config(rerank_url=url)), warnings) == hits
    assert local_model == [] and len(warnings) == 1 and 'secret' not in warnings[0]


@pytest.mark.parametrize('identity', [{'data':[]}, {'data':[{'id':'unrelated'}]}])
def test_unrelated_model_never_receives_sources(monkeypatch, identity):
    calls=[]
    def handler(req):
        calls.append(req)
        assert req.method == 'GET'
        return httpx.Response(200,json=identity)
    mock_async(monkeypatch, handler)
    hits=unit_hits()
    assert neural_rerank.order('ordinary query question',hits,Config()) == hits
    assert len(calls)==1


def test_absent_backend_is_quiet_compatible_fallback(monkeypatch):
    def handler(req):
        raise httpx.ConnectError('secret-shaped request must not leak')
    mock_async(monkeypatch, handler)
    assert neural_rerank.order('ordinary query question',unit_hits(),Config()) == unit_hits()


@pytest.mark.parametrize('stage', ['discovery','scores','body'])
def test_total_deadline_cancels_slow_discovery_score_or_body(monkeypatch, stage):
    import asyncio
    import time
    cancelled=[]
    async def slow():
        try: await asyncio.sleep(10)
        finally: cancelled.append(True)
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await slow()
    async def handler(req):
        if stage=='discovery' or (stage=='scores' and req.method=='POST'):
            await slow()
        if req.method=='GET': return httpx.Response(200,json={'data':[{'id':MODEL}]})
        return httpx.Response(200,stream=SlowBody())
    mock_async(monkeypatch, handler)
    monkeypatch.setattr(neural_rerank, 'DEADLINE_SECONDS', .05)
    before=time.monotonic()
    with pytest.raises(TimeoutError):
        neural_rerank.order('ordinary query question',unit_hits(),Config())
    assert time.monotonic()-before < .5 and cancelled == [True]
    assert neural_rerank._slots.acquire(False) and neural_rerank._slots.acquire(False)
    neural_rerank._slots.release(); neural_rerank._slots.release()


@pytest.mark.parametrize('kind', ['redirect','oversized','invalid-json','status'])
def test_remote_redirect_large_response_and_failures_fall_back(monkeypatch,kind):
    calls=[]
    def handler(req):
        calls.append(req)
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':MODEL}]})
        if kind=='redirect':return httpx.Response(307,headers={'location':'https://remote.test/secret'})
        if kind=='oversized':return httpx.Response(200,content=b'x'*40000)
        if kind=='status':return httpx.Response(500,content=b'private source must not leak')
        return httpx.Response(200,content=b'private invalid JSON')
    mock_async(monkeypatch,handler)
    from agentic_rag.retrieval import rerank
    hits,warnings=unit_hits(),[]
    assert rerank(hits,lambda hs:neural_rerank.order('ordinary query question',hs,Config()),warnings)==hits
    assert len(warnings)==1 and len(calls)==2
    assert {req.url.host for req in calls} == {'127.0.0.1'}


def test_running_event_loop_and_pressure_have_no_queue(local_model):
    import asyncio
    hits=unit_hits()
    async def direct():return neural_rerank.order('ordinary query question',hits,Config())
    assert asyncio.run(direct())==hits
    gate=neural_rerank._slots
    assert gate.acquire(False) and gate.acquire(False)
    try:assert neural_rerank.order('ordinary query question',hits,Config())==hits
    finally:gate.release();gate.release()
    assert local_model == []


def test_two_real_inflight_requests_and_third_client_has_no_queue(monkeypatch):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    started,release=threading.Event(),threading.Event()
    lock=threading.Lock();active=[]
    async def handler(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':MODEL}]})
        with lock:
            active.append(True)
            if len(active)==2:started.set()
        while not release.is_set():await asyncio.sleep(.01)
        return httpx.Response(200,json={'model':MODEL,'results':[
            {'index':i,'relevance_score':.9 if i==11 else .1} for i in range(12)]})
    mock_async(monkeypatch,handler)
    hits=unit_hits()
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests=[pool.submit(neural_rerank.order,'ordinary query question',hits,Config()) for _ in range(2)]
        try:
            assert started.wait(1)
            assert neural_rerank.order('third query question',hits,Config())==hits
            assert len(active)==2
        finally:release.set()
        assert [r.result(timeout=3)[0].document_id for r in requests]==['11','11']


def test_fork_releases_inherited_busy_slots():
    import subprocess
    import sys
    # Separate interpreter avoids forking pytest's unrelated background threads.
    code='''
import os
from agentic_rag import neural_rerank
gate=neural_rerank._slots
assert gate.acquire(False) and gate.acquire(False)
r,w=os.pipe()
pid=os.fork()
if pid==0:
    os.close(r)
    ok=neural_rerank._slots.acquire(False) and neural_rerank._slots.acquire(False)
    os.write(w,b'yes' if ok else b'no');os._exit(0)
os.close(w)
try:
    assert os.read(r,3)==b'yes'
    assert os.waitpid(pid,0)[1]==0 and not gate.acquire(False)
finally:os.close(r);gate.release();gate.release()
'''
    subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,timeout=5)


def test_additive_configuration(tmp_path):
    path=tmp_path/'config.toml'
    path.write_text('[db]\nname="existing"\n[embed]\nmodel="bge-m3"\n')
    assert load_config(path).rerank_url=='http://127.0.0.1:8766'
    path.write_text(path.read_text()+'[rerank]\nurl="http://[::1]:9911"\n')
    cfg=load_config(path)
    assert cfg.db_name=='existing' and cfg.embed_model=='bge-m3'
    assert neural_rerank._url(cfg.rerank_url)=='http://[::1]:9911'


def test_invalid_mode_rejected_before_connect(monkeypatch):
    from agentic_rag import mcp_server
    monkeypatch.setattr(mcp_server,'_connect',lambda:pytest.fail('opened DB before validating'))
    with pytest.raises(ValueError,match='rerank'):
        mcp_server.memory_search('question',rerank='unknown')


def test_measurement_cannot_label_arbitrary_source_as_previous_revision(tmp_path):
    from scripts.measure_neural_rerank import previous
    path=tmp_path/'unrelated.py'
    path.write_text('different_source = True\n')
    with pytest.raises(ValueError,match='baseline'):
        previous(path)


def test_only_current_domain_project_and_source_eligible_passages_reach_model(conn,cfg,local_model,monkeypatch):
    """Neural ordering must never send excluded source bodies to inference."""
    from agentic_rag.domains import add_domain
    from agentic_rag.evidence import sources
    seed_defaults(conn);conn.commit()
    add_domain(conn,'other','Other user domain',actor='test')
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    text='newsletter authentication failure needs dated output verification.'
    eligible=[]
    for i in range(3):
        doc=store.save_claim(conn,cfg,title=f'Eligible {i}',body=text+f' Case {i}.',dtype='memory',
            domain='general',project='/neural/a',claim_kind='stated',
            evidence=[{'namespace':'test','source_id':f'eligible-{i}','role':'user','quote':text,'complete':True}])
        eligible.append(doc)
    for title,project,domain in [('OTHER_PROJECT','/neural/b','general'),
                                  ('OTHER_DOMAIN','/neural/a','other')]:
        store.save_document(conn,cfg,title=title,body=text,dtype='memory',domain=domain,project=project)
    bad=store.save_claim(conn,cfg,title='WITHDRAWN',body=text,dtype='memory',
        domain='general',project='/neural/a',claim_kind='stated',
        evidence=[{'namespace':'test','source_id':'withdrawn','role':'user','quote':text,'complete':True}])
    store.set_source_state(conn,sources(conn,bad.doc_id)[0]['source_key'],state='refuted',reason='Synthetic correction')
    hits,_=search.search(conn,cfg,'newsletter authentication failure',project='/neural/a',domain='general')
    assert len(hits)==3
    assert {h.document_id for h in hits}=={d.doc_id for d in eligible}
    texts=json.loads(local_model[-1].content)['documents']
    assert len(texts)==3 and all(not any(s in t for s in ['OTHER_PROJECT','OTHER_DOMAIN','WITHDRAWN']) for t in texts)
    local_model.clear()
    store.set_source_state(conn,sources(conn,eligible[0].doc_id)[0]['source_key'],state='refuted',reason='Second correction')
    hits,_=search.search(conn,cfg,'newsletter authentication failure',project='/neural/a',domain='general')
    assert {h.document_id for h in hits}=={eligible[1].doc_id,eligible[2].doc_id}
    assert local_model == []  # fewer than three eligible documents bypasses model


def test_mcp_optional_mode_and_populated_concurrent_rollback(conn,cfg,hook_env,local_model,monkeypatch):
    """Both roles and old/new readers coexist without rewriting any stored state."""
    from concurrent.futures import ThreadPoolExecutor
    from psycopg import sql
    from agentic_rag import db,jobs,pins,mcp_server,query_cache
    from agentic_rag.domains import add_domain
    from agentic_rag.continuity import store as checkpoints
    from agentic_rag.continuity.model import CheckpointSnapshot
    seed_defaults(conn);conn.commit()
    add_domain(conn,'other','Second user domain',actor='test')
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:None)
    for i in range(3):
        doc=store.save_document(conn,cfg,title=f'newsletter authentication failure {i}',
            body='newsletter authentication failure original source.',domain='general',dtype='memory',
            project='/neural/a',provenance={'actor':'user-a'})
    store.save_document(conn,cfg,title='newsletter authentication failure user-b',
        body='newsletter authentication failure other source.',domain='other',dtype='memory',
        project='/neural/b',provenance={'actor':'user-b'})
    pins.add_pin(conn,document_id=doc.doc_id,scope='/neural/a')
    checkpoints.upsert_snapshot(conn,CheckpointSnapshot(session_id='neural-upgrade',turn_id='t',
        cursor='c',source='test',trigger='manual',cwd='/neural/a',project_root='/neural/a',
        transcript_fingerprint='sha256:synthetic',git={},artifacts=('AGENTS.md',)))
    jobs.enqueue_curate(conn,reason='Neural upgrade retained queue')
    tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
    def snapshot():
        return {t:conn.execute(sql.SQL('SELECT to_jsonb(t) row FROM {} t ORDER BY to_jsonb(t)::text')
            .format(sql.Identifier(t))).fetchall() for t in tables}
    before=snapshot()
    def old_reader():
        with db.connect(cfg,role='reader') as reader:
            reader.execute('SET TRANSACTION READ ONLY')
            return search.search(reader,cfg,'newsletter authentication failure',project='/neural/a',strategy='hybrid')[0]
    def mcp_reader():
        return mcp_server.memory_search('newsletter authentication failure',project='/neural/a')
    monkeypatch.setenv('RAG_READONLY','1')
    with ThreadPoolExecutor(max_workers=2) as pool:
        old,new=pool.submit(old_reader),pool.submit(mcp_reader)
        original=old.result(timeout=5);result=new.result(timeout=5)
    assert [h.citation for h in original]==[h['citation'] for h in result['results']]
    assert len(local_model)==2
    monkeypatch.setenv('RAG_READONLY','0')
    assert mcp_reader()['results']==result['results']
    assert mcp_server.memory_search('newsletter authentication failure',project='/neural/a',rerank='off')['results']==result['results']
    # Turning inference off/returning to old ordering needs no data migration.
    assert snapshot()==before and old_reader()==original


def test_expired_fact_is_removed_before_inference(conn,cfg,local_model,monkeypatch):
    from datetime import datetime,timedelta,timezone
    from agentic_rag import validity
    seed_defaults(conn);conn.commit()
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    now=datetime.now(timezone.utc)
    for i in range(3):
        store.save_assertion(conn,cfg,entity=f'neural-expiry-{i}',attribute='state',
            value='newsletter authentication failure',domain='general',scope='global',
            event_at=(now-timedelta(days=1)).isoformat(),expires_at=(now+timedelta(hours=1)).isoformat(),
            evidence={'source_id':f'neural-expiry-{i}','role':'user','quote':'newsletter authentication failure'})
    assert len(search.search(conn,cfg,'newsletter authentication failure')[0])==3
    assert len(local_model)==2
    local_model.clear()
    monkeypatch.setattr(validity,'selection',lambda as_of,history:(now+timedelta(hours=2),history))
    assert search.search(conn,cfg,'newsletter authentication failure')[0]==[]
    assert local_model==[]
