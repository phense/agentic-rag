"""Task-role contracts; wrong prefixes must never enter a retained vector space."""
from dataclasses import replace
import json

import httpx
import pytest

from agentic_rag import providers
from test_providers import mock_http, profile


def prefixed(**changes):
    return profile(document_prefix='Document: ', query_prefix='Query: ', **changes)


def test_default_descriptor_is_byte_identical_and_task_roles_change_identity():
    # Catch adding even empty prefix keys to existing persisted identities.
    p = profile()
    assert p.descriptor == dict(provider='ollama',model='tiny',revision='a'*64,
        url='http://127.0.0.1:11434',dimensions=2,normalization='none',metric='cosine',representation='raw-v1')
    task = prefixed()
    assert task.identity != p.identity
    assert task.identity != replace(task, query_prefix='question: ').identity
    assert task.identity != replace(task, document_prefix='passage: ').identity


@pytest.mark.parametrize('provider',['ollama','openai-compatible'])
def test_wire_inputs_are_role_correct_and_raw_limit_is_preserved(monkeypatch,provider):
    # Catch document prefix reused for queries, double prefixing and truncation.
    seen=[]
    p=prefixed(provider=provider, **({'model':'pinned','revision':'pinned'} if provider=='openai-compatible' else {}))
    def handler(request):
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'tiny:latest','digest':'a'*64}]})
        if request.url.path=='/v1/models':return httpx.Response(200,json={'data':[{'id':'pinned'}]})
        data=json.loads(request.content);seen.append(data['input'])
        if provider=='ollama':return httpx.Response(200,json={'embeddings':[[3.,4.]]*len(data['input'])})
        return httpx.Response(200,json={'model':'pinned','data':[{'index':i,'embedding':[3.,4.]} for i in range(len(data['input']))]})
    mock_http(monkeypatch,handler)
    assert providers.embed_profile(['source'],p)==[[3.,4.]]
    assert providers.embed_profile(['source'],p,purpose='query')==[[3.,4.]]
    assert providers.embed_profile(['x'*4000],p)==[[3.,4.]]
    assert seen==[['Document: source'],['Query: source'],['Document: '+'x'*4000]]
    with pytest.raises(providers.ProviderError):providers.embed_profile(['x'*4001],p)
    with pytest.raises(providers.ProviderError):providers.embed_profile(['source'],p,purpose='guess')
    assert len(seen)==3


@pytest.mark.parametrize('changes',[
    {'document_prefix':'Document: '}, {'query_prefix':'Query: '},
    {'document_prefix':None,'query_prefix':'Query: '},
    {'document_prefix':'x'*65,'query_prefix':'Query: '},
    {'document_prefix':'Document:\n','query_prefix':'Query: '},
    {'document_prefix':'Document: ','query_prefix':'\x7f'},
])
def test_invalid_prefixes_fail_before_provider_io(monkeypatch,changes):
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('invalid profile sent data'))
    with pytest.raises(providers.ProviderError):profile(**changes)


def test_probe_covers_both_task_roles_and_describes_wire_bounds(monkeypatch):
    seen=[]
    def handler(request):
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'tiny:latest','digest':'a'*64}]})
        seen.extend(json.loads(request.content)['input'])
        return httpx.Response(200,json={'embeddings':[[1.,0.]]})
    mock_http(monkeypatch,handler)
    info=providers.verify_profile(prefixed())
    assert seen==['Document: Synthetic connectivity probe; no stored knowledge.',
                  'Query: Synthetic connectivity probe; no stored knowledge.']
    assert info['probe_inputs']==2
    assert info['max_wire_input_chars']==4010
    assert info['max_requests_per_probe']==6
    assert info['max_requests_per_selection']==7
    assert providers.describe_profile(profile())['max_requests_per_probe']==3
