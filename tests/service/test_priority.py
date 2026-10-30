"""Foreground work reserves compute before source/model background pages."""
from dataclasses import replace
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
