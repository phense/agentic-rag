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


def embed_texts(texts: list[str], cfg: Config) -> list[list[float]]:
    # validation stays INSIDE the try: a malformed payload (e.g. embeddings=42)
    # must surface as EmbedError, never as a raw TypeError — try_embed_texts
    # promises to never raise
    try:
        with _client() as client:
            r = client.post(
                f"{cfg.ollama_url}/api/embed",
                json={"model": cfg.embed_model, "input": texts},
            )
            r.raise_for_status()
            vecs = r.json()["embeddings"]
            if len(vecs) != len(texts) or any(
                len(v) != cfg.embed_dim for v in vecs
            ):
                raise EmbedError(
                    f"embedding dimension mismatch: expected {cfg.embed_dim}"
                )
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        raise EmbedError(f"ollama embed failed: {e}") from e
    return vecs


def try_embed_texts(texts: list[str], cfg: Config) -> list[list[float]] | None:
    try:
        return embed_texts(texts, cfg)
    except EmbedError:
        return None


def vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:g}" for x in vec) + "]"
