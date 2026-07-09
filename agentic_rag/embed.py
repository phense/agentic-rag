"""Ollama embedding client. The ONLY embedding path — never load models in-process."""
from __future__ import annotations

import httpx

from .config import Config


class EmbedError(RuntimeError):
    pass


def _client() -> httpx.Client:  # separate fn so tests can inject a MockTransport
    return httpx.Client(timeout=120)


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
