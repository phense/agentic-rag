"""Ollama embedding client. The ONLY embedding path — never load models in-process."""
from __future__ import annotations

import httpx
import atexit
from contextlib import contextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
import os
import threading

from .config import Config


class EmbedError(RuntimeError):
    pass


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


_transport = None
_transport_lock = threading.Lock()


def close_transport():
    """Close process resources at exit; tests may call this between isolated runs."""
    global _transport
    with _transport_lock:
        client, _transport = _transport, None
    if client is not None:
        client.close()


def _after_fork():
    # Never acquire locks or use sockets inherited from a multi-threaded parent.
    global _transport, _transport_lock
    _transport = None
    _transport_lock = threading.Lock()


atexit.register(close_transport)
if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


@contextmanager
def _client():  # separate seam so tests can inject a MockTransport
    global _transport
    with _transport_lock:
        if _transport is None:
            _transport = httpx.Client(timeout=120,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=8,
                                   keepalive_expiry=30),
                cookies=CookieJar(policy=_NoCookies()))
        client = _transport
    yield client


def background_timeout(cfg: Config) -> float:
    """Finite per-call deadline of the optional background lane (default 60 s)."""
    value = cfg.ollama_background_timeout_seconds
    return 60.0 if value is None else float(value)


def _payload(cfg: Config, texts: list[str], threads: int | None) -> dict:
    # Unset thread settings keep the exact pre-A2 request body.
    body = {"model": cfg.embed_model, "input": texts}
    if threads is not None:
        body["options"] = {"num_thread": threads}
    return body


def embed_texts(texts: list[str], cfg: Config) -> list[list[float]]:
    from .service.fence import LEASE
    from .service.priority import model_slot, check_background
    from .service.context import CURRENT
    server = cfg.service_mode == 'server' or (CURRENT.get() is not None and cfg.service_auth_file is not None)
    if not server:
        return _embed_texts(texts, cfg)
    background = LEASE.get() is not None
    # Only fenced central legacy background pages use the optional lane.
    lane = background and cfg.ollama_background_url is not None
    result = []
    pages = [[text] for text in texts] if background else [texts]
    for page in pages:
        if background:check_background(cfg)
        with model_slot(cfg, background=background, lane=lane):
            result.extend(_lane_embed(page, cfg) if lane else _embed_texts(page, cfg))
    return result


def _lane_identity(cfg: Config, url: str) -> str:
    """Both endpoints must serve the configured tag with one verified digest."""
    from . import query_cache
    from .service.engine import ResourcePressure
    primary = query_cache.model_digest(cfg)
    if primary is None or query_cache.endpoint_digest(cfg, url) != primary:
        raise ResourcePressure('background_model_identity', 429)
    return primary


def _lane_embed(texts: list[str], cfg: Config) -> list[list[float]]:
    """One page on the background daemon; every failure keeps the attempt.

    Vectors are returned only if the primary and lane identities match before
    and after inference. Callers keep the primary identity for reuse keys, so
    no vector is ever labelled with a different daemon's configuration.
    """
    from .service.engine import ResourcePressure
    url = cfg.ollama_background_url.rstrip('/')
    expected = _lane_identity(cfg, url)
    try:
        with _client() as client:
            r = client.post(f"{url}/api/embed",
                            json=_payload(cfg, texts, cfg.ollama_background_num_thread),
                            timeout=background_timeout(cfg))
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError):
        raise ResourcePressure('background_model_unavailable', 429) from None
    from .providers import ProviderError, validate_vectors
    try:
        vectors = validate_vectors(data["embeddings"], len(texts), cfg.embed_dim)
    except (ProviderError, KeyError, TypeError, ValueError, AttributeError):
        raise ResourcePressure('background_model_identity', 429) from None
    if _lane_identity(cfg, url) != expected:
        raise ResourcePressure('background_model_identity', 429)
    return vectors


def _embed_texts(texts: list[str], cfg: Config, *, timeout: float | None = None) -> list[list[float]]:
    from .service.fence import LEASE
    # validation stays INSIDE the try: a malformed payload (e.g. embeddings=42)
    # must surface as EmbedError, never as a raw TypeError — try_embed_texts
    # promises to never raise
    try:
        with _client() as client:
            r = client.post(
                f"{cfg.ollama_url}/api/embed",
                json=_payload(cfg, texts, cfg.ollama_num_thread),
                **({"timeout":timeout} if timeout is not None else {"timeout":10.0} if cfg.service_mode == "server" and LEASE.get() is not None else {}),
            )
            r.raise_for_status()
            vecs = r.json()["embeddings"]
            from .providers import ProviderError, validate_vectors
            try:
                vecs = validate_vectors(vecs, len(texts), cfg.embed_dim)
            except ProviderError:
                raise EmbedError('embedding dimension or numeric value mismatch') from None
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        raise EmbedError('ollama embed failed; check provider availability and response format') from None
    return vecs


def try_embed_texts(texts: list[str], cfg: Config) -> list[list[float]] | None:
    try:
        return embed_texts(texts, cfg)
    except EmbedError:
        return None


def vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:g}" for x in vec) + "]"
