"""Bounded loopback inference: trust only ordering, never model evidence payloads."""
from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from urllib.parse import urlsplit

import httpx

from .retrieval import terms, strong_symbols

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
    return (len(query) <= QUERY_CHARS and len(terms(query)) >= 3 and not strong_symbols(query)
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


async def _scores(url, query, passages, *, model=MODEL, deadline=None, diagnostics=None):
    # A single cancellable deadline covers discovery, headers and streamed bodies.
    deadline = min(DEADLINE_SECONDS, deadline if deadline is not None else DEADLINE_SECONDS)
    async with asyncio.timeout(deadline):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                    timeout=deadline) as client:
            try:
                identity = await _json(client, 'GET', url + '/v1/models')
            except httpx.ConnectError:
                return None  # The optional local runtime is not installed/running.
            if not isinstance(identity, dict) or not isinstance(identity.get('data'), list):
                raise ValueError('invalid model discovery')
            if not any(isinstance(m, dict) and m.get('id') == model for m in identity['data']):
                return None  # Never send private passages to an unrelated local service.
            client.cookies.clear()
            if diagnostics is not None:
                diagnostics.update(candidates=len(passages),passage_chars=sum(map(len,passages)))
            result = await _json(client, 'POST', url + '/v1/rerank', json={
                'model': model, 'query': query, 'documents': passages,
                'top_n': len(passages), 'return_documents': False,
            })
            if not isinstance(result, dict) or result.get('model') != model:
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


def inspect(cfg):
    """Offline configuration description; an alias/revision is an operator assertion."""
    return {'route': cfg.rerank_policy, 'model': cfg.rerank_model,
            'revision': cfg.rerank_revision, 'outcome': 'bypass',
            'candidates': 0, 'passage_chars': 0}


def diagnostic_text(info):
    """Only fields created here enter client-visible diagnostics."""
    return ('rerank diagnostic: route={route} model={model} revision={revision} '
            'outcome={outcome} candidates={candidates} passage_chars={passage_chars}').format(**info)


def order(query, hits, cfg, *, diagnostics=None):
    info = inspect(cfg)
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(info)
        info = diagnostics
    if not eligible(query, hits):
        return hits
    # search is synchronous; avoid nested event loops for direct async callers.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        info['outcome'] = 'async_bypass'
        return hits
    gate = _slots
    if not gate.acquire(blocking=False):
        info['outcome'] = 'pressure'
        return hits
    try:
        url = _url(cfg.rerank_url)
        count, chars = (6, 600) if cfg.rerank_policy == 'focused-v1' else (MAX_CANDIDATES, PASSAGE_CHARS)
        prefix = hits[:count]
        passages = [(h.title + '\n' + h.snippet)[:chars] for h in prefix]
        scores = asyncio.run(_scores(url, query, passages, model=cfg.rerank_model,
                                   deadline=cfg.rerank_timeout_seconds,diagnostics=info))
        if scores is None:
            info['outcome'] = 'unavailable'
            return hits
        indices = sorted(scores, key=lambda i: (-scores[i], i))
        info.update(outcome='ranked', candidates=len(prefix), passage_chars=sum(map(len, passages)))
        return [prefix[i] for i in indices] + hits[count:]
    except (TimeoutError, httpx.TimeoutException):
        info['outcome'] = 'timeout'
        raise
    except Exception:
        info['outcome'] = 'invalid'
        raise
    finally:
        gate.release()
