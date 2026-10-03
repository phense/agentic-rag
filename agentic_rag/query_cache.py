"""Process-local query vectors only. SQL remains the authority on every request."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from hashlib import sha256
import json
import math
import os
import re
import threading
import time
import weakref

import httpx

from . import embed

_instances = weakref.WeakSet()


def _after_fork():
    # Called once before a child starts new threads; weak references allow normal GC.
    for cache in list(_instances):
        cache.clear()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def model_digest(cfg):
    """Unknown/unavailable identity never authorizes reusing a query vector."""
    name = cfg.embed_model if ':' in cfg.embed_model else cfg.embed_model + ':latest'
    try:
        with embed._client() as client:
            response = client.get(cfg.ollama_url + '/api/tags', timeout=2)
            response.raise_for_status()
            models = response.json()['models']
        digests = {row['digest'] for row in models if row.get('name', row.get('model')) == name}
        if len(digests) == 1:
            digest = digests.pop()
            if isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest):
                return digest
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError):
        pass
    return None


class QueryCache:
    """Bounded LRU/TTL with bounded coalescing; keys contain no raw query text."""
    def __init__(self, capacity=256, ttl=300, max_inflight=8):
        if type(capacity) is not int or capacity < 1 or type(max_inflight) is not int or max_inflight < 1:
            raise ValueError('cache capacities must be positive integers')
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError('cache ttl must be positive and finite')
        self.capacity, self.ttl, self.max_inflight = capacity, ttl, max_inflight
        self.clear()
        _instances.add(self)

    def clear(self):
        """New process/isolated lifecycle; do not call concurrently with requests."""
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._inflight = {}

    def vectors(self, query, cfg, context, loader):
        digest = model_digest(cfg)
        if digest is None:
            return loader([query], cfg)
        encoded = json.dumps([cfg.ollama_url, cfg.embed_model, cfg.embed_dim, digest,
                              context, query], sort_keys=True, separators=(',', ':'))
        key = sha256(encoded.encode()).digest()
        now = time.monotonic()
        with self._lock:
            # Sweep expiry so rarely reused entries do not hold vectors indefinitely.
            for expired in [k for k, (deadline, _) in self._entries.items() if deadline <= now]:
                del self._entries[expired]
            cached = self._entries.get(key)
            if cached:
                self._entries.move_to_end(key)
                return [list(cached[1])]
            future = self._inflight.get(key)
            owner = future is None
            if owner and len(self._inflight) < self.max_inflight:
                future = self._inflight[key] = Future()
        if future is None:
            return loader([query], cfg)  # capacity pressure preserves uncached behavior
        if not owner:
            vectors = future.result()
            # A wait can cross a model replacement; validate before using that vector.
            if model_digest(cfg) != digest:
                return loader([query], cfg)
            return None if vectors is None else [list(vectors[0])]
        try:
            vectors = loader([query], cfg)
            valid = (isinstance(vectors, list) and len(vectors) == 1
                     and isinstance(vectors[0], list) and len(vectors[0]) == cfg.embed_dim
                     and all(type(v) in (float, int) and math.isfinite(v) for v in vectors[0]))
            # Do not bind a vector to an old digest if replacement raced inference.
            if valid and model_digest(cfg) == digest:
                with self._lock:
                    self._entries[key] = (time.monotonic() + self.ttl, tuple(vectors[0]))
                    self._entries.move_to_end(key)
                    while len(self._entries) > self.capacity:
                        self._entries.popitem(last=False)
            future.set_result(None if vectors is None else tuple(tuple(v) for v in vectors))
            return vectors
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
