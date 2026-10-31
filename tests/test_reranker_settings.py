"""Preset selection must change ordering without changing persisted knowledge."""
from dataclasses import replace
from agentic_rag.config import Config,load_config


def test_default_is_mmarco_focused_and_explicit_legacy_config_survives(tmp_path):
    cfg=Config()
    assert cfg.rerank_model=='agentic-rag-mmarco-int8'
    assert cfg.rerank_policy=='focused-v1'
    config=tmp_path/'config.toml'
    config.write_text('[rerank]\nmodel="legacy-ranker"\nrevision="'+'a'*64+'"\n')
    old=load_config(config)
    assert old.rerank_model=='legacy-ranker' and old.rerank_revision=='a'*64
    assert old.rerank_policy=='legacy-v1'


def test_profile_shortcut_selects_one_consistent_model_identity(tmp_path):
    config=tmp_path/'config.toml';config.write_text('[rerank]\nprofile="minilm-l6"\n')
    cfg=load_config(config)
    assert cfg.rerank_model=='agentic-rag-minilm-l6-en-de-int8'
    assert cfg.rerank_revision=='5d849b007fb3975d130f6f476eea9977980f5f260cbef8b0c4ba00efac67f1ab'
    assert cfg.rerank_policy=='focused-v1'


def test_offline_runtime_command_is_installable_and_has_no_implicit_download():
    import subprocess,sys
    result=subprocess.run([sys.executable,'-m','agentic_rag.reranker_runtime','--help'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'prepare' in result.stdout and 'serve' in result.stdout


def test_profile_and_manual_identity_cannot_be_mixed(tmp_path):
    import pytest
    for text in ['profile="unknown"','profile="mmarco"\nmodel="unverified"','profile="mmarco"\npolicy="legacy-v1"']:
        config=tmp_path/'config.toml';config.write_text('[rerank]\n'+text+'\n')
        with pytest.raises(ValueError):load_config(config)


def test_managed_model_hash_mismatch_never_transfers_source(monkeypatch):
    import httpx
    from agentic_rag import neural_rerank
    from tests.test_measured_rerank import hits
    calls=[];real=httpx.AsyncClient
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'data':[{'id':'agentic-rag-mmarco-int8','revision':'0'*64}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    original=hits();diagnostic={}
    assert neural_rerank.order('private ordinary source question',original,Config(),diagnostics=diagnostic)==original
    assert len(calls)==1 and calls[0].method=='GET' and diagnostic['outcome']=='unavailable'


def test_runtime_rejects_bad_inputs_and_never_returns_source_text():
    from starlette.testclient import TestClient
    from agentic_rag.reranker_runtime import create_app
    calls=[]
    def rank(query,documents):calls.append((query,documents));return [.1,.9]
    with TestClient(create_app({'mmarco':rank})) as client:
        identity=client.get('/v1/models').json()['data'][0]
        assert identity=={'id':'agentic-rag-mmarco-int8','revision':'6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b'}
        valid={'model':identity['id'],'query':'ordinary public question','documents':['private first','private second'],'top_n':2,'return_documents':False}
        result=client.post('/v1/rerank',json=valid)
        assert result.status_code==200 and result.json()['results']==[{'index':0,'relevance_score':.1},{'index':1,'relevance_score':.9}]
        assert 'private' not in result.text
        for mutation in [{'model':'unknown'},{'query':'x'*513},{'documents':[]},{'documents':['x'*1201]},{'top_n':True},{'return_documents':True}]:
            assert client.post('/v1/rerank',json={**valid,**mutation}).status_code==400
        assert client.post('/v1/rerank',json=valid,headers={'origin':'https://hostile.test'}).status_code==403
        assert client.post('/v1/rerank',content=b'x'*65537).status_code==413
        assert len(calls)==1


def test_native_runtime_slot_remains_busy_until_worker_finishes():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from starlette.testclient import TestClient
    from agentic_rag.reranker_runtime import create_app
    entered=threading.Event();release=threading.Event()
    def predict(*args):entered.set();assert release.wait(5);return [.9,.1]
    data={'model':'agentic-rag-mmarco-int8','query':'ordinary question','documents':['one','two'],'top_n':2}
    with TestClient(create_app({'mmarco':predict})) as client,ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(client.post,'/v1/rerank',json=data)
        try:
            assert entered.wait(2)
            assert client.post('/v1/rerank',json=data).status_code==429
        finally:release.set()
        assert pending.result(timeout=5).status_code==200
        assert client.post('/v1/rerank',json=data).status_code==200


def test_pinned_artifacts_reject_corruption_and_links(tmp_path):
    import hashlib
    import pytest
    from agentic_rag.reranker_runtime import verify
    file=tmp_path/'model';file.write_bytes(b'known')
    artifact={'bytes':5,'sha256':hashlib.sha256(b'known').hexdigest()}
    verify(file,artifact)
    file.write_bytes(b'other')
    with pytest.raises(ValueError,match='checksum'):verify(file,artifact)
    link=tmp_path/'link';link.symlink_to(file)
    with pytest.raises(ValueError):verify(link,artifact)


def test_partial_explicit_legacy_identity_preserves_old_omitted_fields(tmp_path):
    config=tmp_path/'config.toml'
    config.write_text('[rerank]\nmodel="agentic-rag-qwen3-reranker-0.6b-q8"\n')
    cfg=load_config(config)
    assert cfg.rerank_revision=='22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48'
    assert cfg.rerank_policy=='legacy-v1'
    config.write_text('[rerank]\nrevision="'+'a'*64+'"\n')
    assert load_config(config).rerank_model=='agentic-rag-qwen3-reranker-0.6b-q8'


def test_reserved_preset_alias_cannot_disable_identity_check_with_wrong_config_sha():
    import pytest
    with pytest.raises(ValueError,match='rerank'):
        replace(Config(),rerank_revision='0'*64)


def test_cancel_before_executor_start_does_not_strand_native_slot():
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import httpx
    from agentic_rag.reranker_runtime import create_app
    async def scenario():
        loop=asyncio.get_running_loop();executor=ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        release=threading.Event();entered=threading.Event()
        def block():entered.set();release.wait(5)
        blocker=loop.run_in_executor(None,block)
        while not entered.is_set():await asyncio.sleep(.001)
        app=create_app({'mmarco':lambda *a:[.9,.1]})
        data={'model':'agentic-rag-mmarco-int8','query':'ordinary question','documents':['one','two'],'top_n':2}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
            pending=asyncio.create_task(client.post('/v1/rerank',json=data))
            await asyncio.sleep(.03)
            pending.cancel()
            try:await pending
            except asyncio.CancelledError:pass
            release.set();await blocker
            await loop.run_in_executor(None,lambda:None)
            assert (await client.post('/v1/rerank',json=data)).status_code==200
    asyncio.run(scenario())


def test_native_cli_rejects_unsupported_ipv6_before_loading_artifacts(tmp_path):
    import pytest
    from agentic_rag.reranker_runtime import main
    with pytest.raises(SystemExit) as error:
        main(['serve','--models-dir',str(tmp_path),'--host','::1'])
    assert error.value.code==2
