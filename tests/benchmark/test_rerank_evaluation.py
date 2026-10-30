"""Behavioral evaluation guards: leakage, label inflation, forged seals and retuning."""
from copy import deepcopy
import importlib

import pytest


def module():
    return importlib.import_module('agentic_rag.benchmark.rerank_evaluation')


def test_binary_source_metrics_count_duplicates_and_missing_sources_as_misses():
    score=module().ranking(['a','b','b'],['b','c'],error=None)
    assert score['recall']==.5 and score['precision']==pytest.approx(1/3)
    assert score['ndcg']==pytest.approx(.3868528072)
    assert score['missing']==['c'] and score['retrieval_empty'] is False
    empty=module().ranking([],[],error='TimeoutError')
    assert empty['retrieval_empty'] is True and empty['correct_empty'] is False
    assert module().ranking([],[],error=None)['correct_empty'] is True
    assert module().ranking(['b'],['b','c'])['ndcg']==pytest.approx(.6131471928)


def test_corpus_rejects_family_or_copied_source_leakage_before_services():
    m=module();corpus=m.load_corpus()[0]
    assert {'en','de'}=={q['language'] for q in corpus['queries']}
    assert {'identifier','temporal','multi-source','unanswerable'} <= {q['category'] for q in corpus['queries']}
    bad=deepcopy(corpus);bad['documents'][-1]['family']=bad['documents'][0]['family']
    with pytest.raises(ValueError,match='family|split'):m.validate_corpus(bad)
    bad=deepcopy(corpus);bad['documents'][-1]['body']=bad['documents'][0]['body']
    with pytest.raises(ValueError,match='copied|split'):m.validate_corpus(bad)


def test_candidate_seal_exclusive_and_detects_source_drift(tmp_path):
    m=module();path=tmp_path/'candidate.json'
    source={'a.py':'a'*64};payload={'choice':'focused-v1','source':source,'corpus_sha256':'b'*64}
    sealed=m.seal(payload,path)
    assert m.read_seal(path,source,'b'*64)==sealed
    with pytest.raises(FileExistsError):m.seal(payload,path)
    with pytest.raises(ValueError,match='drift'):m.read_seal(path,{'a.py':'c'*64},'b'*64)
    path.write_text(path.read_text().replace('focused-v1','legacy-v1'))
    with pytest.raises(ValueError,match='seal'):m.read_seal(path,source,'b'*64)


def test_selector_cannot_use_test_outcomes_or_regress_quality():
    m=module()
    base=[{'id':'a','ndcg':.5,'recall':.5,'error':None,'latency_ms':100,'outcomes':['ranked']}]
    better=[{'id':'a','ndcg':.5,'recall':.5,'error':None,'latency_ms':70,'outcomes':['ranked']}]
    worse=[{'id':'a','ndcg':.4,'recall':.5,'error':None,'latency_ms':20}]
    assert m.choose(base,better,split='dev')=='focused-v1'
    assert m.choose(base,worse,split='dev')=='legacy-v1'
    with pytest.raises(ValueError,match='development'):m.choose(base,better,split='test')


def test_selector_rejects_an_additional_failed_inference_repeat():
    base=[dict(id='a',ndcg=.5,recall=.5,error=None,latency_ms=100,outcomes=['timeout','ranked','ranked'])]
    candidate=[dict(id='a',ndcg=.5,recall=.5,error=None,latency_ms=50,outcomes=['timeout','timeout','ranked'])]
    assert module().choose(base,candidate,split='dev')=='legacy-v1'


def test_all_bypass_or_timeout_equality_cannot_select_a_faster_failed_model():
    for outcome in ('bypass','timeout','unavailable'):
        base=[dict(id='a',ndcg=.5,recall=.5,error=None,latency_ms=100,outcomes=[outcome])]
        candidate=[dict(id='a',ndcg=.5,recall=.5,error=None,latency_ms=50,outcomes=[outcome])]
        assert module().choose(base,candidate,split='dev')=='legacy-v1'


def test_repetitions_do_not_multiply_quality_denominators():
    m=module();row=dict(id='one',family='f',ndcg=.5,recall=.5,precision=1/3,missing=['x'],
        error=None,unanswerable=False,retrieval_empty=False,correct_empty=False,
        latency_ms=10,raw_ms=[10,11,12],warm_ms=[11,12],first_ms=10,
        citation_parity=True,context_chars=100,outcomes=['ranked'])
    summary=m.summarize([row])
    assert summary['queries']==1 and summary['answerable']==1 and summary['timing_observations']==3
    assert summary['misses']==['one'] and summary['independent_families']==1
    assert summary['family_interval'] is None
    row['trials']=[{'error':None},{'error':'original_citation_mismatch'}]
    summary=m.summarize([row])
    assert summary['query_failures']==1 and summary['trial_failures']==1
    assert summary['citation_parity'] is False


def test_runtime_idle_gate_drains_a_cancelled_request_before_next_measurement(monkeypatch):
    import httpx
    calls=[];real=httpx.Client
    def handler(request):
        calls.append(request)
        assert request.url.path=='/slots'
        return httpx.Response(200,json=[{'is_processing':len(calls)==1}])
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:real(transport=httpx.MockTransport(handler),**kwargs))
    result=module()._drain('http://127.0.0.1:8768')
    assert result['idle_verified'] is True and result['observations']==2 and len(calls)==2


def test_cleanup_tracks_partial_startup_and_already_crashed_children():
    from pathlib import Path
    import subprocess
    import sys
    from scripts.rehearse_reranker import stop_owned
    partial=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    crashed=subprocess.Popen([sys.executable,'-c','raise SystemExit(7)']);crashed.wait(timeout=5)
    try:
        errors=stop_owned([('postgres',partial),('model',crashed)],Path('/proc/self/cgroup').read_bytes())
        assert errors==[] and partial.poll() is not None and crashed.returncode==7
    finally:
        if partial.poll() is None:partial.kill();partial.wait(timeout=5)


def test_nonpreregistered_model_or_timeout_rejected_before_database(tmp_path,monkeypatch):
    from agentic_rag.config import Config
    m=module();monkeypatch.setattr(m.db,'connect',lambda *a,**kw:pytest.fail('database before fixed-grid validation'))
    for cfg in [Config(ollama_url='http://127.0.0.1:1',rerank_timeout_seconds=.1),
                Config(ollama_url='http://127.0.0.1:1',rerank_model='different')]:
        with pytest.raises(ValueError,match='preregistered'):m.run(cfg,output=tmp_path/'output')


def test_actual_citation_verification_error_survives_trial_and_summary(monkeypatch):
    from types import SimpleNamespace
    from agentic_rag.config import Config
    m=module()
    conn=SimpleNamespace(execute=lambda *a,**kw:SimpleNamespace(fetchone=lambda:{'content':'original'}),rollback=lambda:None)
    hit=SimpleNamespace(chunk_id='c',snippet='forged',snippet_start=0,snippet_end=6)
    monkeypatch.setattr(m.search,'search',lambda *a,**kw:([hit],[]))
    monkeypatch.setattr(m,'_drain',lambda url:{'idle_verified':True,'drain_ms':0})
    trial=m._one(conn,Config(),{'query':'ordinary ambiguous question','domain':'alpha','as_of':None},{},'focused-v1',None)
    assert trial['error']=='original_citation_mismatch' and trial['hits']==[]
    row=dict(id='one',family='f',ndcg=0,recall=0,precision=0,missing=['x'],
        error=trial['error'],unanswerable=False,retrieval_empty=True,correct_empty=False,
        raw_ms=[trial['latency_ms']],warm_ms=[],first_ms=trial['latency_ms'],
        citation_parity=True,context_chars=0,outcomes=['bypass'],trials=[trial])
    assert m.summarize([row])['citation_parity'] is False


def test_forced_parent_shutdown_is_a_failed_rehearsal_even_if_parent_exits():
    import subprocess
    from pathlib import Path
    from scripts.rehearse_reranker import stop_owned
    class StuckChild:
        pid=__import__('os').getpid()
        returncode=None
        def poll(self):return self.returncode
        def send_signal(self,value):pass
        def wait(self,timeout):
            if self.returncode is None:raise subprocess.TimeoutExpired('owned',timeout)
            return self.returncode
        def kill(self):self.returncode=-9
    child=StuckChild()
    assert stop_owned([('postgres',child)],Path('/proc/self/cgroup').read_bytes())==[
        {'child':'postgres','error':'forced_shutdown'}]
    assert child.poll()==-9


def test_reference_envelope_checks_actual_affinity_without_delegated_cpuset(tmp_path,monkeypatch):
    from pathlib import Path
    m=module();root=tmp_path/'group';root.mkdir()
    for key,value in {'cpu.max':'400000 100000','memory.max':'8589934592','memory.swap.max':'0',
            'memory.current':'1','memory.peak':'2','cpu.stat':'usage_usec 1',
            'memory.events':'oom 0\noom_kill 0','cgroup.procs':'1'}.items():(root/key).write_text(value)
    membership=tmp_path/'membership';membership.write_text('0::/\n')
    monkeypatch.setattr(m,'Path',lambda p:membership if str(p)=='/proc/self/cgroup' else root if str(p)=='/sys/fs/cgroup' else Path(p))
    monkeypatch.setattr(m.os,'sched_getaffinity',lambda _:set(range(4)))
    result=m.reference_snapshot()
    assert result['affinity_cpus']==[0,1,2,3] and result['cpuset.cpus.effective']=='not delegated'
    monkeypatch.setattr(m.os,'sched_getaffinity',lambda _:set(range(8)))
    with pytest.raises(ValueError,match='envelope'):m.reference_snapshot()


def test_development_controls_ingest_and_exercise_real_candidate_routes(conn,cfg,monkeypatch):
    from dataclasses import replace
    m=module();corpus=m.load_corpus()[0]
    monkeypatch.setattr(m.store,'try_embed_texts',lambda *a,**kw:None)
    monkeypatch.setattr(m.search,'try_embed_texts',lambda *a,**kw:None)
    documents=[d for d in corpus['documents'] if d['family']=='dev-orbit']
    mapping,failures=m._ingest(conn,replace(cfg,ollama_url='http://127.0.0.1:1'),documents)
    assert failures=={} and len(mapping)==len(documents)
    for q in [q for q in corpus['queries'] if q['family']=='dev-orbit']:
        hits,_=m.search.search(conn,cfg,q['query'],domain=q['domain'],project=q['project'],as_of=q['as_of'],
            k=12,context_mode='off',rerank_mode='off')
        identities=[mapping[h.document_id] for h in hits]
        if q['category'] in ('ordering','multi-source'):
            assert len(identities)>=3 and m.neural_rerank.eligible(q['query'],hits)
        if q['category'] in ('temporal','identifier'):
            assert set(q['expected_ids'])<=set(identities)
        assert not set(q.get('stale_ids',[]))&set(identities)
        conn.rollback()


def test_native_idle_endpoint_read_timeout_is_drained_within_overall_deadline(monkeypatch):
    import httpx
    calls=[];real=httpx.Client
    def handler(request):
        calls.append(request)
        if len(calls)==1:raise httpx.ReadTimeout('busy native runtime',request=request)
        return httpx.Response(200,json=[{'is_processing':False}])
    monkeypatch.setattr(httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    result=module()._drain('http://127.0.0.1:8768')
    assert result['idle_verified'] is True and result['observations']==2


def test_rejected_initial_test_families_are_not_reused_as_fresh_heldout():
    corpus=module().load_corpus()[0]
    assert {q['family'] for q in corpus['queries'] if q['split']=='test'}=={'test-spruce','test-amber','test-falcon'}
    assert all(d.get('assertion',{}).get('relation')=='replacement'
        for d in corpus['documents'] if d['id'] in ('dev-orbit-current','test-spruce-current','test-amber-current','test-falcon-current'))


def test_unique_ids_do_not_hide_duplicate_quality_request_contracts():
    m=module();corpus=m.load_corpus()[0]
    duplicate=deepcopy(corpus['queries'][0]);duplicate['id']='duplicate-quality-row'
    corpus['queries'].append(duplicate)
    with pytest.raises(ValueError,match='duplicate.*request'):m.validate_corpus(corpus)
