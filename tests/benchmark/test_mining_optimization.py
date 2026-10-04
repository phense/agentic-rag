from pathlib import Path
import pytest
from agentic_rag.config import Config


def test_native_prompt_optimization_requires_explicit_model_before_storage(tmp_path):
    from agentic_rag.benchmark.mining_optimization import run
    with pytest.raises(ValueError,match='explicit'):
        run(Config(),output=tmp_path/'report')
    assert not (tmp_path/'report').exists()


def test_candidate_is_frozen_using_development_only():
    from agentic_rag.benchmark.mining_optimization import select
    rows=[dict(prompt='source',user_correct=False,unsafe=0,error=None),
          dict(prompt='correction-v1',user_correct=True,unsafe=0,error=None)]
    assert select(rows)=='correction-v1'
    assert select([dict(prompt='source',user_correct=True,unsafe=0,error=None),
                   dict(prompt='correction-v1',user_correct=True,unsafe=0,error=None)])=='source'
    assert select([dict(prompt='source',user_correct=True,unsafe=0,error=None),
                   dict(prompt='correction-v1',user_correct=True,unsafe=1,error=None)])=='source'


def test_owned_grounding_and_replay_keep_all_provider_failures_in_denominators(cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining,store
    from agentic_rag.benchmark import identity
    monkeypatch.setattr(identity,'model_digest',lambda cfg:'a'*64)
    from agentic_rag.benchmark.mining_optimization import run
    monkeypatch.setattr(store,'try_embed_texts',lambda *args:None)
    monkeypatch.setattr(mining,'try_embed_texts',lambda *args:None)
    def provider(prompt,*args,**kwargs):
        events=json.loads(prompt.split('SOURCE EVENTS (consumed fragments only):\n')[1])
        text=events[0]['text'].removeprefix('[user] ')
        entity=text.split()[0];value=text.split('is now ')[1].split('.')[0]
        return dict(assertions=[dict(entity=entity,attribute='port',value=value,domain='general',
            relation='replacement',event_at='2026-03-01T00:00:00Z',expires_at=None,
            source_id=events[0]['source_id'],quote=text)])
    monkeypatch.setattr(mining,'run_structured',provider)
    r=run(cfg,output=tmp_path/'success',model=True)
    assert r['provider_calls']==8 and len(r['heldout'])==4
    assert all(v['user_correct'] and v['unsafe']==0 and v['replay_identical'] for v in r['development']+r['heldout'])
    assert r['selected_prompt']=='source'
    from agentic_rag.benchmark.optimization import _mining_metadata
    candidate=json.loads((tmp_path/'success/candidate.json').read_text())
    assert _mining_metadata(candidate)['selected_prompt']=='source'
    def unavailable(*args,**kwargs):raise RuntimeError('provider failure')
    monkeypatch.setattr(mining,'run_structured',unavailable)
    r=run(cfg,output=tmp_path/'failure',model=True)
    assert r['provider_calls']==8 and len(r['heldout'])==4
    assert all(v['error'] and not v['user_correct'] for v in r['development']+r['heldout'])


def test_remote_native_stage_stops_before_storage_or_provider(tmp_path,monkeypatch):
    from agentic_rag.benchmark import mining_optimization
    monkeypatch.setattr(mining_optimization,'isolated_database',lambda cfg:pytest.fail('unsafe endpoint reached storage'))
    with pytest.raises(ValueError,match='local'):
        mining_optimization.run(Config(ollama_url='https://remote.example'),output=tmp_path/'remote',model=True)
    assert not (tmp_path/'remote').exists()


def test_changed_loaded_prompt_invalidates_native_comparison(tmp_path,monkeypatch):
    from agentic_rag import mining
    from agentic_rag.benchmark import identity,mining_optimization
    monkeypatch.setattr(identity,'model_digest',lambda cfg:'a'*64)
    def change(*args):
        monkeypatch.setitem(mining.BENCHMARK_PROMPTS,'correction-v1',mining.BENCHMARK_PROMPTS['correction-v1']+' changed')
        return dict(prompt='source',unsafe=0,user_correct=True,error=None)
    monkeypatch.setattr(mining_optimization,'_measure',change)
    with pytest.raises(ValueError,match='prompt/source'):
        mining_optimization.run(Config(),output=tmp_path/'changed',model=True)
    assert not (tmp_path/'changed/results.json').exists()
