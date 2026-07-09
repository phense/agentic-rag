import json

import httpx
import pytest

from agentic_rag.config import Config
from agentic_rag.embed import EmbedError, embed_texts, try_embed_texts, vec_literal


def _cfg():
    return Config(embed_dim=3)


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embed_texts_ok(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    assert embed_texts(["hi"], _cfg()) == [[0.1, 0.2, 0.3]]


def test_embed_texts_dim_mismatch_raises(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    with pytest.raises(EmbedError, match="dimension"):
        embed_texts(["hi"], _cfg())


def test_embed_texts_http_error_raises(monkeypatch):
    def handler(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    with pytest.raises(EmbedError):
        embed_texts(["hi"], _cfg())


def test_try_embed_returns_none_on_connect_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    assert try_embed_texts(["hi"], _cfg()) is None


def test_malformed_payload_is_embed_error_not_typeerror(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"embeddings": 42})

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    with pytest.raises(EmbedError):
        embed_texts(["hi"], _cfg())
    assert try_embed_texts(["hi"], _cfg()) is None  # never raises


def test_vec_literal():
    assert vec_literal([0.1, -1.0, 2]) == "[0.1,-1,2]"


def test_embed_count_mismatch_is_embed_error(monkeypatch):
    # Ollama returned fewer vectors than inputs — must surface as EmbedError
    # (the existing dim-mismatch test covers WRONG-SIZED vectors; this one
    # covers TOO FEW vectors — a distinct failure the len() check catches)
    def handler(request):
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    with pytest.raises(EmbedError):
        embed_texts(["a", "b"], _cfg())


def test_embed_posts_expected_body_shape(monkeypatch):
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        vecs = [[0.1, 0.2, 0.3] for _ in seen["body"]["input"]]
        return httpx.Response(200, json={"embeddings": vecs})

    monkeypatch.setattr("agentic_rag.embed._client", lambda: _mock(handler))
    embed_texts(["hello", "welt"], _cfg())
    assert seen["path"] == "/api/embed"
    assert seen["body"] == {"model": _cfg().embed_model,
                            "input": ["hello", "welt"]}
