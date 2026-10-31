"""Catch wrong model dispatch, unbounded focused requests and unsafe diagnostics."""
import json
from dataclasses import replace

import httpx
import pytest

from agentic_rag import neural_rerank, retrieval, search
from agentic_rag.config import Config, load_config


def hits():
    return [search.SearchHit(str(i), str(i), 'Original title', 'source-'+str(i),
        'general', 'memory', 'Original source text '+('x'*1600), 1/(61+i), None, {})
        for i in range(15)]


def transport(monkeypatch, model, *, broken=False):
    calls=[]
    real=httpx.AsyncClient
    def handler(req):
        calls.append(req)
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':model,'revision':Config().rerank_revision}]})
        body=json.loads(req.content)
        if broken:return httpx.Response(200,content=b'private malformed source')
        return httpx.Response(200,json={'model':model,'results':[
            {'index':i,'relevance_score':.9 if i==4 else .1,'document':{'text':'FORGED'}}
            for i in range(len(body['documents']))]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    return calls


def test_focused_config_dispatches_named_model_with_bounded_original_payload(monkeypatch):
    calls=transport(monkeypatch,'local-alternative')
    cfg=Config(rerank_policy='focused-v1',rerank_model='local-alternative',rerank_revision='a'*64)
    original=hits(); diagnostic={}
    after=neural_rerank.order('ordinary multilingual evidence question',original,cfg,diagnostics=diagnostic)
    assert [h.document_id for h in after[:6]]==['4','0','1','2','3','5']
    assert after[6:]==original[6:] and all(h is original[int(h.document_id)] for h in after)
    body=json.loads(calls[-1].content)
    assert body['model']=='local-alternative' and len(body['documents'])==6
    assert max(map(len,body['documents']))==600
    assert diagnostic=={'route':'focused-v1','model':'local-alternative','revision':'a'*64,
        'outcome':'ranked','candidates':6,'passage_chars':3600}
    assert 'Original' not in json.dumps(diagnostic)


@pytest.mark.parametrize('options',[
    {'rerank_policy':'bigger'}, {'rerank_model':'secret/url'}, {'rerank_model':''},
    {'rerank_model':'x'*81}, {'rerank_revision':'unverified'},
    {'rerank_revision':'a'*63}, {'rerank_diagnostics':1},
    {'rerank_timeout_seconds':0}, {'rerank_timeout_seconds':float('nan')},
    {'rerank_timeout_seconds':2}, {'rerank_timeout_seconds':True},
])
def test_invalid_options_rejected_before_network(options,monkeypatch):
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:pytest.fail('network before config validation'))
    with pytest.raises(ValueError,match='rerank'):
        Config(**options)


def test_default_without_explicit_model_uses_focused_policy(tmp_path,monkeypatch):
    calls=transport(monkeypatch,neural_rerank.MODEL)
    p=tmp_path/'old.toml';p.write_text('[rerank]\nurl="http://127.0.0.1:8766"\n')
    cfg=load_config(p)
    assert cfg.rerank_policy=='focused-v1' and cfg.rerank_diagnostics is False
    original=hits();info={}
    neural_rerank.order('ordinary multilingual evidence question',original,cfg,diagnostics=info)
    assert len(json.loads(calls[-1].content)['documents'])==6 and info['candidates']==6
    assert info['passage_chars']==3600 and info['route']=='focused-v1'


def test_safe_invalid_and_absent_diagnostics_preserve_full_order(monkeypatch):
    original=hits();info={};warnings=[]
    transport(monkeypatch,neural_rerank.MODEL,broken=True)
    after=retrieval.rerank(original,lambda hs:neural_rerank.order(
        'private query secret',hs,Config(),diagnostics=info),warnings)
    assert after==original and info['outcome']=='invalid'
    assert info['candidates']==6 and info['passage_chars']==3600
    assert 'private' not in json.dumps(info) and 'secret' not in json.dumps(info)
    assert warnings==['local reranker unavailable or invalid — deterministic hybrid fallback']
    info={}
    # The advertised model does not match; no request containing passages is allowed.
    calls=[];real=httpx.AsyncClient
    def handler(req):
        calls.append(req);assert req.method=='GET'
        return httpx.Response(200,json={'data':[{'id':'unrelated'}]})
    # Replace from the real type rather than stacking the earlier test transport.
    monkeypatch.undo()
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert neural_rerank.order('ordinary query words',original,Config(),diagnostics=info)==original
    assert info['outcome']=='unavailable' and len(calls)==1


@pytest.mark.parametrize('query,values',[('',[]),('one two',hits()),
    ('newsletter authentication RuntimeError',hits())])
def test_explained_bypass_has_no_input_transfer(query,values,monkeypatch):
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:pytest.fail('bypass inferred'))
    info={}
    assert neural_rerank.order(query,values,Config(),diagnostics=info)==values
    assert info['outcome']=='bypass' and info['candidates']==0 and info['passage_chars']==0
