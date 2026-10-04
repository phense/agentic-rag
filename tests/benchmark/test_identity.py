from dataclasses import replace
import pytest
from agentic_rag.config import Config


def test_private_remote_endpoint_rejected_before_identity_request(monkeypatch):
    from agentic_rag.benchmark import identity
    monkeypatch.setattr(identity,'model_digest',lambda cfg:pytest.fail('unsafe endpoint called'))
    for url in ('https://remote.example','http://user:secret@localhost:11434','http://localhost:11434?key=x'):
        with pytest.raises(ValueError,match='local'):
            identity.local_model(Config(ollama_url=url))


def test_unknown_or_changed_model_invalidates_comparison(monkeypatch):
    from agentic_rag.benchmark import identity
    monkeypatch.setattr(identity,'model_digest',lambda cfg:None)
    with pytest.raises(ValueError,match='immutable'):
        identity.local_model(Config())
    monkeypatch.setattr(identity,'model_digest',lambda cfg:'a'*64)
    frozen=identity.local_model(Config())
    identity.model_guard(Config(),frozen)
    monkeypatch.setattr(identity,'model_digest',lambda cfg:'b'*64)
    with pytest.raises(ValueError,match='changed'):
        identity.model_guard(Config(),frozen)
    monkeypatch.setattr(identity,'model_digest',lambda cfg:'a'*64)
    with pytest.raises(ValueError,match='changed'):
        identity.model_guard(replace(Config(),embed_model='another-tag'),frozen)
