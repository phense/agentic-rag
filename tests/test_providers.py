"""Synthetic provider boundary tests; never contact a real inference endpoint."""
import dataclasses
import json
import math

import httpx
import pytest

from agentic_rag.config import Config, load_config


def test_profiles_are_loaded_separately_and_immutable(tmp_path):
    # Mutation caught: treating a managed profile as a new legacy default.
    path = tmp_path / 'config.toml'
    path.write_text('[embedding_profiles.small]\nprovider="ollama"\nmodel="tiny"\n'
                    'revision="' + 'a' * 64 + '"\nurl="http://127.0.0.1:11434"\ndimensions=2\n')
    cfg = load_config(path)
    assert cfg.embed_model == 'bge-m3'
    assert 'small' in cfg.embedding_profiles
    with pytest.raises(TypeError):
        cfg.embedding_profiles['other'] = {}


def profile(**changes):
    from agentic_rag.providers import resolve_profile
    values = dict(provider='ollama', model='tiny', revision='a'*64,
                  url='http://127.0.0.1:11434', dimensions=2)
    values.update(changes)
    return resolve_profile(Config(embedding_profiles={'small': values}), 'small')


def mock_http(monkeypatch, handler):
    from agentic_rag import providers
    original = httpx.Client
    def client(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(providers, '_http_client', client)


def test_identity_excludes_credentials_and_limits_but_includes_space():
    p = profile()
    assert p.identity == profile(credential_env='TEST_ROTATED_TOKEN', max_batch=1).identity
    for change in [dict(revision='b'*64), dict(dimensions=3), dict(normalization='l2'),
                   dict(model='other'), dict(url='http://localhost:11434')]:
        assert p.identity != profile(**change).identity
    copy = p.descriptor
    copy['model'] = 'other'
    assert p.descriptor['model'] == 'tiny'
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.model = 'other'


@pytest.mark.parametrize('changes', [dict(provider='unsupported'),dict(dimensions=0),
    dict(dimensions=4001),dict(max_batch=33),dict(max_input_chars=4001),dict(timeout=math.inf),
    dict(url='http://user:secret@localhost:11434'),dict(url='https://example.com?token=secret'),
    dict(url='http://example.com'),dict(revision='alias'),dict(metric='l2'),
    dict(credential_env='BAD-NAME'),dict(api_key='plaintext')])
def test_invalid_configuration_never_contacts_provider(changes):
    from agentic_rag.providers import ProviderError
    with pytest.raises(ProviderError) as error:
        profile(**changes)
    assert not error.value.retryable
    assert 'secret' not in str(error.value) and 'plaintext' not in str(error.value)


def test_describe_is_offline_and_has_explicit_bounds(monkeypatch):
    from agentic_rag import providers
    monkeypatch.setattr(providers, '_http_client', lambda **kw: pytest.fail('offline inspection sent data'))
    info = providers.describe_profile(profile())
    assert info['max_requests_per_batch'] == 3
    assert info['max_batch'] == 32 and info['max_input_chars'] == 4000
    assert info['external_egress'] is False
    assert info['identity_guarantee'] == 'ollama-sha256-tag'


def test_ollama_pins_digest_before_and_after_and_normalizes(monkeypatch):
    from agentic_rag.providers import embed_profile, verify_identity
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == '/api/tags':
            return httpx.Response(200,json={'models':[{'name':'tiny:latest','digest':'a'*64}]})
        assert json.loads(request.content) == {'model':'tiny','input':['synthetic'], 'truncate':False}
        return httpx.Response(200,json={'embeddings':[[3,4]]})
    mock_http(monkeypatch, handler)
    p = profile(normalization='l2')
    assert verify_identity(p) == p.identity
    assert embed_profile(['synthetic'], p) == [[.6,.8]]
    assert seen == ['/api/tags','/api/tags','/api/embed','/api/tags']


def test_identity_drift_never_returns_vectors(monkeypatch):
    from agentic_rag.providers import embed_profile, ProviderError
    tags = 0
    def handler(request):
        nonlocal tags
        if request.url.path == '/api/tags':
            tags += 1
            return httpx.Response(200,json={'models':[{'name':'tiny:latest','digest':('a' if tags==1 else 'b')*64}]})
        return httpx.Response(200,json={'embeddings':[[1,2]]})
    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:embed_profile(['synthetic'],profile())
    assert error.value.code == 'identity_mismatch'


@pytest.mark.parametrize('vector', [[0,0],[1,math.inf],[True,1],[70000,1],[1e-30,0],['1',2]])
def test_invalid_vectors_never_apply(monkeypatch, vector):
    from agentic_rag.providers import embed_profile,ProviderError
    def handler(request):
        if request.url.path == '/api/tags':
            return httpx.Response(200,json={'models':[{'name':'tiny:latest','digest':'a'*64}]})
        return httpx.Response(200,content=json.dumps({'embeddings':[vector]}))
    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:embed_profile(['synthetic'],profile())
    assert error.value.code == 'invalid_response'


@pytest.mark.parametrize('texts', [[],[''],['x'*4001],['x']*33])
def test_input_bounds_reject_before_network(monkeypatch,texts):
    from agentic_rag import providers
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('invalid input reached network'))
    with pytest.raises(providers.ProviderError):providers.embed_profile(texts,profile())


@pytest.mark.parametrize('status,code,retryable',[(401,'authentication',False),(429,'rate_limit',True),
    (404,'model_missing',False),(503,'transient',True),(302,'configuration',False)])
def test_errors_are_classified_without_body_or_arbitrary_secret(monkeypatch,status,code,retryable):
    from agentic_rag.providers import verify_identity,ProviderError
    mock_http(monkeypatch,lambda req:httpx.Response(status,text='opaque-private-token private corpus'))
    with pytest.raises(ProviderError) as error:verify_identity(profile())
    assert error.value.code == code and error.value.retryable is retryable
    assert 'opaque-private-token' not in str(error.value) and 'corpus' not in str(error.value)


def test_http_pinned_logical_identity_and_auth(monkeypatch):
    from agentic_rag.providers import embed_profile,describe_profile
    monkeypatch.setenv('TEST_PROVIDER_TOKEN','opaque-secret-value')
    seen=[]
    def handler(req):
        assert req.headers['authorization']=='Bearer opaque-secret-value'
        seen.append(req.url.path)
        if req.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':'tiny-20261030'}]})
        return httpx.Response(200,json={'model':'tiny-20261030','data':[{'index':0,'embedding':[1,2]}]})
    mock_http(monkeypatch,handler)
    p=profile(provider='openai-compatible',model='tiny-20261030',revision='tiny-20261030',
              url='https://models.example/v1',credential_env='TEST_PROVIDER_TOKEN')
    assert embed_profile(['synthetic'],p)==[[1.,2.]]
    assert seen==['/v1/models','/v1/embeddings','/v1/models']
    assert describe_profile(p)['identity_guarantee']=='server-asserted-logical-model-id; not weight attestation'
    assert 'opaque-secret-value' not in json.dumps(describe_profile(p))


def test_http_refuses_arbitrary_revision_label():
    from agentic_rag.providers import ProviderError
    with pytest.raises(ProviderError):profile(provider='openai-compatible',revision='my-immutable-label')


def test_protected_token_file_and_no_symlinks(tmp_path,monkeypatch):
    from agentic_rag.providers import verify_identity,ProviderError
    token=tmp_path/'token';token.write_text('opaque-private-token');token.chmod(0o644)
    p=profile(credential_file=str(token))
    monkeypatch.setattr('agentic_rag.providers._http_client',lambda **kw:pytest.fail('unsafe credentials reached network'))
    with pytest.raises(ProviderError) as error:verify_identity(p)
    assert error.value.code=='authentication'
    token.chmod(0o600)
    link=tmp_path/'link';link.symlink_to(token)
    with pytest.raises(ProviderError):verify_identity(profile(credential_file=str(link)))


def test_http_structured_extraction_independent_of_embedding(monkeypatch):
    from agentic_rag.llm import run_structured
    def handler(req):
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'extract-20261030'}]})
        body=json.loads(req.content)
        assert body['response_format']['type']=='json_schema'
        assert body['max_tokens']==256
        return httpx.Response(200,json={'model':'extract-20261030','choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]})
    mock_http(monkeypatch,handler)
    cfg=Config(llm_provider='openai-compatible',llm_model='extract-20261030',
               llm_revision='extract-20261030',llm_url='http://127.0.0.1:8765/v1',llm_max_output_tokens=256)
    assert run_structured('Synthetic check',{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},cfg)=={'ok':True}


def test_llm_inspection_and_probe_are_separate(monkeypatch):
    from agentic_rag import providers
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('inspection made an inference request'))
    info=providers.describe_llm(Config())
    assert info['provider']=='claude' and info['credential_source']=='existing-cli-login-and-environment'
    assert info['inspection_is_offline'] is True


def test_oversized_integer_is_a_classified_vector_failure():
    from agentic_rag.providers import validate_vectors,ProviderError
    with pytest.raises(ProviderError) as error:validate_vectors([[10**400,1]],1,2)
    assert error.value.code=='invalid_response'


def test_config_remains_json_dataclass_serializable_for_research_workers():
    # Research hands Config across a process boundary with dataclasses.asdict.
    cfg=Config(embedding_profiles={'small':profile()})
    serialized=json.loads(json.dumps(dataclasses.asdict(cfg),default=str))
    roundtrip=Config(**serialized)
    assert roundtrip.embedding_profiles['small'].identity==cfg.embedding_profiles['small'].identity


def test_missing_environment_secret_fails_before_network(monkeypatch):
    from agentic_rag import providers
    monkeypatch.delenv('TEST_UNCONFIGURED_TOKEN',raising=False)
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('missing secret reached network'))
    with pytest.raises(providers.ProviderError) as error:
        providers.verify_identity(profile(credential_env='TEST_UNCONFIGURED_TOKEN'))
    assert error.value.code=='authentication'


def test_provider_response_bytes_are_bounded_and_transport_errors_sanitized(monkeypatch):
    from agentic_rag import providers
    mock_http(monkeypatch,lambda req:httpx.Response(200,content=b'x'*(providers.MAX_RESPONSE_BYTES+1)))
    with pytest.raises(providers.ProviderError) as error:providers.verify_identity(profile())
    assert error.value.code=='invalid_response'


def test_http_response_model_must_match_pin(monkeypatch):
    from agentic_rag import providers
    sent=[]
    def handler(req):
        sent.append(req.url.path)
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'tiny-20261030'}]})
        return httpx.Response(200,json={'model':'other-model','data':[{'index':0,'embedding':[1,2]}]})
    mock_http(monkeypatch,handler)
    p=profile(provider='openai-compatible',model='tiny-20261030',revision='tiny-20261030')
    with pytest.raises(providers.ProviderError) as error:providers.embed_profile(['synthetic'],p)
    assert error.value.code=='identity_mismatch' and len(sent)==2


def test_protected_file_is_usable_without_exposing_value(tmp_path,monkeypatch):
    from agentic_rag import providers
    token=tmp_path/'token';token.write_text('arbitrary-private-value\n');token.chmod(0o600)
    def handler(req):
        assert req.headers['authorization']=='Bearer arbitrary-private-value'
        return httpx.Response(401,text='arbitrary-private-value')
    mock_http(monkeypatch,handler)
    with pytest.raises(providers.ProviderError) as error:
        providers.verify_identity(profile(credential_file=str(token)))
    assert 'arbitrary-private-value' not in str(error.value)


def test_inference_concurrency_pressure_fails_without_sending_corpus(monkeypatch):
    from agentic_rag import providers
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('capacity overflow reached network'))
    assert providers._inference_slots.acquire(blocking=False)
    assert providers._inference_slots.acquire(blocking=False)
    try:
        with pytest.raises(providers.ProviderError) as error:providers.embed_profile(['synthetic'],profile())
        assert error.value.code=='capacity' and error.value.retryable
    finally:
        providers._inference_slots.release();providers._inference_slots.release()


def test_llm_external_schema_references_are_rejected_before_network(monkeypatch):
    from agentic_rag import providers
    from agentic_rag.llm import run_structured,LLMJobError
    monkeypatch.setattr(providers,'_http_client',lambda **kw:pytest.fail('unsupported schema reached network'))
    cfg=Config(llm_provider='openai-compatible',llm_model='extract-v1',llm_revision='extract-v1',llm_url='http://127.0.0.1:8765')
    with pytest.raises(LLMJobError) as error:
        run_structured('Synthetic',{'$ref':'https://unrelated.example/private-schema'},cfg)
    assert error.value.code=='unsupported_capability'


def test_malformed_deep_json_is_classified_not_a_runtime_crash(monkeypatch):
    from agentic_rag import providers
    mock_http(monkeypatch,lambda req:httpx.Response(200,content='['*10000+'0'+']'*10000))
    with pytest.raises(providers.ProviderError) as error:providers.verify_identity(profile())
    assert error.value.code=='invalid_response'


def test_extraction_nonfinite_json_cannot_pass_number_schema(monkeypatch):
    from agentic_rag.llm import run_structured,LLMJobError
    def handler(req):
        if req.url.path.endswith('/models'):return httpx.Response(200,json={'data':[{'id':'extract-v1'}]})
        return httpx.Response(200,json={'model':'extract-v1','choices':[{'finish_reason':'stop','message':{'content':'{"number":NaN}'}}]})
    mock_http(monkeypatch,handler)
    cfg=Config(llm_provider='openai-compatible',llm_model='extract-v1',llm_revision='extract-v1',llm_url='http://127.0.0.1:8765')
    with pytest.raises(LLMJobError) as error:
        run_structured('Synthetic',{'type':'object','properties':{'number':{'type':'number'}}},cfg)
    assert error.value.code=='invalid_response'
