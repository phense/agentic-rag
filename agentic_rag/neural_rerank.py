"""Bounded loopback inference: trust only ordering, never model evidence payloads."""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from urllib.parse import urlsplit

import httpx

from .retrieval import terms

MODEL = 'agentic-rag-qwen3-reranker-0.6b-q8'
MAX_CANDIDATES = 12
PASSAGE_CHARS = 1200
QUERY_CHARS = 512
DEADLINE_SECONDS = 1.5
MAX_RESPONSE_BYTES = 32768
_slots = threading.BoundedSemaphore(2)


def _after_fork():
    global _slots
    _slots = threading.BoundedSemaphore(2)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def eligible(query, hits):
    """Near-tied ordinary questions justify the bounded extra inference stage."""
    distinct = {}
    for hit in hits[:MAX_CANDIDATES]:
        distinct.setdefault(hit.document_id, hit.score)
    scores = list(distinct.values())
    return (len(query) <= QUERY_CHARS and len(terms(query)) >= 3
            and len(scores) >= 3 and scores[0] > 0 and scores[1] >= .8 * scores[0])


def _url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1')
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or '?' in value or '#' in value):
        raise ValueError('reranker requires a literal loopback HTTP origin')
    # Validate the port too; never include the configured URL in errors.
    try:
        parsed.port
    except ValueError:
        raise ValueError('invalid local reranker port') from None
    return value.rstrip('/')


async def _json(client, method, url, **kwargs):
    async with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise ValueError('oversized local reranker response')
            body.extend(chunk)
        return json.loads(body)


async def _scores(url, query, passages):
    # A single cancellable deadline covers discovery, headers and streamed bodies.
    async with asyncio.timeout(DEADLINE_SECONDS):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                    timeout=DEADLINE_SECONDS) as client:
            try:
                identity = await _json(client, 'GET', url + '/v1/models')
            except httpx.ConnectError:
                return None  # The optional local runtime is not installed/running.
            if not isinstance(identity, dict) or not isinstance(identity.get('data'), list):
                raise ValueError('invalid model discovery')
            if not any(isinstance(m, dict) and m.get('id') == MODEL for m in identity['data']):
                return None  # Never send private passages to an unrelated local service.
            client.cookies.clear()
            result = await _json(client, 'POST', url + '/v1/rerank', json={
                'model': MODEL, 'query': query, 'documents': passages,
                'top_n': len(passages), 'return_documents': False,
            })
            if not isinstance(result, dict) or result.get('model') != MODEL:
                raise ValueError('reranker model changed')
            rows = result.get('results')
            if not isinstance(rows, list) or len(rows) != len(passages):
                raise ValueError('incomplete reranker scores')
            scores = {}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('invalid reranker score')
                index, score = row.get('index'), row.get('relevance_score')
                if (type(index) is not int or not 0 <= index < len(passages)
                        or index in scores or type(score) not in (float, int)
                        or not math.isfinite(score) or not 0 <= score <= 1):
                    raise ValueError('invalid reranker score')
                scores[index] = score
            return scores


def order(query, hits, cfg):
    if not eligible(query, hits):
        return hits
    # search is synchronous; avoid nested event loops for direct async callers.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return hits
    gate = _slots
    if not gate.acquire(blocking=False):
        return hits
    try:
        url = _url(cfg.rerank_url)
        prefix = hits[:MAX_CANDIDATES]
        passages = [(h.title + '\n' + h.snippet)[:PASSAGE_CHARS] for h in prefix]
        scores = asyncio.run(_scores(url, query, passages))
        if scores is None:
            return hits
        indices = sorted(scores, key=lambda i: (-scores[i], i))
        return [prefix[i] for i in indices] + hits[MAX_CANDIDATES:]
    finally:
        gate.release()
