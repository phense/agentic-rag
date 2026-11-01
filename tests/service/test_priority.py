"""Foreground work reserves compute before source/model background pages."""
from dataclasses import replace
import threading
from agentic_rag.service.engine import ResourcePressure
from .test_scope import service_store
import pytest


def test_background_pauses_without_consuming_jobs_when_foreground_active(service_store):
    from agentic_rag.service.priority import foreground, background_ready
    cfg,_=service_store
    cfg=replace(cfg,service_mode='server')
    assert background_ready(cfg)
    with foreground(cfg):
        assert not background_ready(cfg)
    assert background_ready(cfg)


def test_background_embedding_checks_priority_between_single_input_pages(service_store,monkeypatch):
    from agentic_rag import embed
    from agentic_rag.service import priority
    from agentic_rag.service.fence import LEASE
    cfg,_=service_store;cfg=replace(cfg,service_mode='server')
    calls=[]
    monkeypatch.setattr(priority,'background_ready',lambda cfg:len(calls)<1)
    monkeypatch.setattr(embed,'_embed_texts',lambda texts,cfg:(calls.append(texts) or [[0.0]*1024 for _ in texts]))
    from agentic_rag.worker import acquire_database_lock
    from agentic_rag.service.fence import worker_scope
    with acquire_database_lock(cfg) as keeper,worker_scope(keeper):
        with pytest.raises(ResourcePressure):embed.embed_texts(['first','second'],cfg)
    assert calls==[['first']]


@pytest.mark.parametrize('busy_after', [0, 1])
def test_prepared_background_embeddings_yield_to_foreground(service_store, monkeypatch, busy_after):
    # Regression: an inference executor that drops LEASE treats worker batches
    # as foreground and sends every input despite interactive demand.
    from agentic_rag import embed, embedding_reuse
    from agentic_rag.service import priority
    from agentic_rag.service.fence import worker_scope
    from agentic_rag.worker import acquire_database_lock
    cfg, _ = service_store
    cfg = replace(cfg, service_mode='server')
    calls = []
    monkeypatch.setattr(priority, 'background_ready', lambda cfg: len(calls) < busy_after)
    monkeypatch.setattr(embed, '_embed_texts',
        lambda texts, cfg: calls.append(texts) or [[0.0] * 1024 for _ in texts])
    with acquire_database_lock(cfg) as keeper, worker_scope(keeper):
        with pytest.raises(ResourcePressure, match='foreground_busy'):
            embedding_reuse._compute(['first', 'second'], cfg, embed.try_embed_texts)
    assert calls == ([] if busy_after == 0 else [['first']])


def test_prepared_worker_http_keeps_short_timeout_and_single_input_pages(service_store, monkeypatch):
    # HTTP is the only double: real compute, worker fencing, admission and
    # embed client policy must retain background semantics through preparation.
    from contextlib import contextmanager
    from agentic_rag import embed, embedding_reuse
    from agentic_rag.service.fence import worker_scope
    from agentic_rag.worker import acquire_database_lock
    cfg, _ = service_store
    cfg = replace(cfg, service_mode='server')
    calls = []

    class Response:
        def __init__(self, count): self.count = count
        def raise_for_status(self): pass
        def json(self): return {'embeddings': [[1.0] + [0.0] * 1023 for _ in range(self.count)]}

    class Client:
        def post(self, url, *, json, timeout=None):
            calls.append((json['input'], timeout, threading.get_ident()))
            return Response(len(json['input']))

    @contextmanager
    def client(): yield Client()
    monkeypatch.setattr(embed, '_client', client)
    main_thread = threading.get_ident()
    with acquire_database_lock(cfg) as keeper, worker_scope(keeper):
        vectors = embedding_reuse._compute(['first', 'second'], cfg, embed.try_embed_texts)
    assert vectors == [[1.0] + [0.0] * 1023, [1.0] + [0.0] * 1023]
    assert calls == [(['first'], 10.0, main_thread), (['second'], 10.0, main_thread)]
