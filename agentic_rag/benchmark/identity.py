"""Frozen local embedding identity for attributable offline comparisons."""
from hashlib import sha256
import re
from urllib.parse import urlsplit
from ..query_cache import model_digest


def local_model(cfg):
    endpoint=urlsplit(cfg.ollama_url)
    if (endpoint.scheme not in ('http','https') or endpoint.hostname not in ('localhost','127.0.0.1','::1')
        or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('benchmark requires an existing local embedding endpoint without credentials')
    if cfg.embed_dim!=1024:raise ValueError('benchmark requires the existing1024-dimensional schema')
    digest=model_digest(cfg)
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
        raise ValueError('known immutable embedding model identity required')
    return dict(endpoint_sha256=sha256(cfg.ollama_url.encode()).hexdigest(),model=cfg.embed_model,
        dimension=cfg.embed_dim,digest=digest)


def model_guard(cfg,expected):
    if local_model(cfg)!=expected:
        raise ValueError('embedding model identity changed; discard comparison')
