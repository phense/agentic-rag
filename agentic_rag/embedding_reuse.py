"""Exact sanitized-input reuse; only HTTP inference runs in parallel.

Cache SQL is optional and savepoint-isolated. Cache writes stay in the gateway's
transaction. No database connection, dedup decision or source cursor enters a thread.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
import threading

import psycopg

from .embed import EmbedError, vec_literal
from . import query_cache


def model_digest(cfg):
    return query_cache.model_digest(cfg)

PAGE = 256
BATCH = 16
MAX_BYTES = 1024 * 1024
_slots = threading.BoundedSemaphore(2)
_prepared = ContextVar('embedding_prepared', default=None)
_metrics = ContextVar('embedding_metrics', default=None)


def _after_fork():
    global _slots
    _slots = threading.BoundedSemaphore(2)
    _prepared.set(None)
    _metrics.set(None)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


@dataclass
class Metrics:
    generated_inputs: int = 0
    cache_inputs: int = 0
    prepared_inputs: int = 0
    embedding_calls: int = 0
    fallback_calls: int = 0


@contextmanager
def measure():
    result = Metrics()
    token = _metrics.set(result)
    try:
        yield result
    finally:
        _metrics.reset(token)


def _count(field, n):
    result = _metrics.get()
    if result is not None:
        setattr(result, field, getattr(result, field) + n)


@contextmanager
def _optional(conn):
    # Explicit SAVEPOINT never owns/commits even an initially idle connection.
    conn.execute('SAVEPOINT embedding_reuse_optional')
    try:
        yield
    except BaseException:
        conn.execute('ROLLBACK TO SAVEPOINT embedding_reuse_optional')
        raise
    finally:
        conn.execute('RELEASE SAVEPOINT embedding_reuse_optional')


def _available(conn):
    try:
        with _optional(conn):
            return conn.execute("SELECT to_regclass('public.embedding_reuse_cache') AS t").fetchone()['t'] is not None
    except psycopg.Error:
        return False


def _model(cfg, digest):
    tag = cfg.embed_model if ':' in cfg.embed_model else cfg.embed_model + ':latest'
    return sha256(json.dumps([cfg.ollama_url, tag, cfg.embed_dim, digest], separators=(',', ':')).encode()).hexdigest()


def _hash(text):
    return sha256(text.encode()).hexdigest()


def _valid(vectors, count, dim):
    return (isinstance(vectors, list) and len(vectors) == count
        and all(isinstance(v, list) and len(v) == dim
                and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 65504 for x in v)
                for v in vectors))


def _lookup(conn, model, representation, hashes, dim):
    try:
        with _optional(conn):
            rows = conn.execute('SELECT input_hash,embedding::text AS vector FROM embedding_reuse_cache '
                'WHERE model_key=%s AND representation=%s AND input_hash=ANY(%s)',
                (model, representation, hashes)).fetchall()
            result = {}
            for row in rows:
                vector = json.loads(row['vector'])
                if _valid([vector], 1, dim):
                    result[row['input_hash']] = vector
            return result
    except (psycopg.Error, ValueError, TypeError):
        return {}


def _persist(conn, model, representation, entries, actor):
    if not entries:
        return
    try:
        with _optional(conn):
            conn.execute('SELECT put_embedding_reuse(%s,%s,%s,%s,%s)',
                (model, representation, list(entries), [vec_literal(v) for v in entries.values()], actor))
    except psycopg.Error:
        pass  # savepoint preserves earlier caller-owned canonical effects


def _infer(texts, cfg, loader):
    with _slots:
        return loader(texts, cfg)


def _compute(texts, cfg, loader):
    # Only two futures (each <=16 inputs) exist at once. No unbounded submission.
    output = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='rag-embed') as pool:
        for start in range(0, len(texts), BATCH * 2):
            batches = [texts[i:i+BATCH] for i in range(start, min(start+BATCH*2, len(texts)), BATCH)]
            futures = [pool.submit(_infer, batch, cfg, loader) for batch in batches]
            _count('embedding_calls', len(futures))
            _count('generated_inputs', sum(map(len, batches)))
            for batch, future in zip(batches, futures):
                vectors = future.result()
                if not _valid(vectors, len(batch), cfg.embed_dim):
                    return None
                output.extend(vectors)
    return output


def _fallback(texts, cfg, loader):
    _count('fallback_calls', 1)
    _count('embedding_calls', 1)
    _count('generated_inputs', len(texts))
    return _infer(texts, cfg, loader)


def vectors(conn, cfg, texts, *, loader, actor, representation='raw-v1', strict=False, persist=True, expected_digest=None):
    """Keep complete ordered input; optional cache never owns the outer transaction."""
    if representation not in ('raw-v1', 'context-v1'):
        raise ValueError('unknown embedding representation')
    if not texts:
        return []
    if not _available(conn) or cfg.embed_dim != 1024:
        return _fallback(texts, cfg, loader)
    digest = expected_digest if expected_digest is not None else model_digest(cfg)
    if digest is None:
        return _fallback(texts, cfg, loader)
    model = _model(cfg, digest)
    prepared = _prepared.get() or {}
    output = []
    for start in range(0, len(texts), PAGE):
        page = texts[start:start+PAGE]
        # Oversized inputs retain the original inference route without preparation.
        if sum(len(t.encode()) for t in page) > MAX_BYTES:
            result = _fallback(page, cfg, loader)
            if result is None:
                output = None
                break
            output.extend(result)
            continue
        hashes = [_hash(t) for t in page]
        cached = _lookup(conn, model, representation, hashes, cfg.embed_dim)
        for key in hashes:
            value = prepared.get((model, representation, key))
            if value is not None:
                cached[key] = list(value)
        missing = {key: text for key, text in zip(hashes, page) if key not in cached}
        inferred = _compute(list(missing.values()), cfg, loader) if missing else []
        if inferred is None:
            output = None
            break
        generated = dict(zip(missing, inferred))
        _count('prepared_inputs', sum((model, representation, key) in prepared for key in hashes))
        _count('cache_inputs', sum(key in cached and (model, representation, key) not in prepared for key in hashes))
        cached.update(generated)
        # Check hits as well as misses. Never apply a mixed old/new model result.
        if model_digest(cfg) != digest:
            output = None
            break
        if persist:
            # Includes prepared vectors, which were computed without cache mutation.
            _persist(conn, model, representation, cached, actor)
        output.extend(list(cached[key]) for key in hashes)
    if output is not None and model_digest(cfg) != digest:
        output = None
    if output is None and strict:
        raise EmbedError('embedding unavailable or model identity changed; retry')
    return output


@contextmanager
def prepare_documents(conn, cfg, documents, *, loader):
    """Precompute a bounded group of final title/body inputs, with no cache writes.

    All remaining documents use the normal gateway. Exact sanitization and chunking
    here must match save_document; no metadata or dedup inference is speculative.
    """
    from .chunker import chunk_markdown
    from .secrets import strip_secrets
    texts, size = [], 0
    for title, body in documents[:16]:
        if len(title.encode()) + len(body.encode()) > MAX_BYTES:
            break
        chunks = chunk_markdown(f'# {strip_secrets(title)[0]}\n\n{strip_secrets(body)[0]}')
        nbytes = sum(len(t.encode()) for t in chunks)
        if len(texts)+len(chunks)>PAGE or size+nbytes>MAX_BYTES:
            break
        texts.extend(chunks)
        size += nbytes
    entries = {}
    # Avoid speculative inference entirely on018 or unknown identity.
    if texts and cfg.embed_dim == 1024 and _available(conn):
        digest = model_digest(cfg)
        if digest is not None:
            result = vectors(conn, cfg, texts, loader=loader, actor='mining', persist=False, expected_digest=digest)
            if result is not None and model_digest(cfg) == digest:
                model = _model(cfg, digest)
                entries = {(model, 'raw-v1', _hash(t)): tuple(v) for t, v in zip(texts, result)}
    token = _prepared.set(entries)
    try:
        yield
    finally:
        _prepared.reset(token)
