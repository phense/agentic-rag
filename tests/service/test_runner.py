"""The long-running worker owns the database fence before orphan recovery."""
import threading

from .test_scope import service_store


def test_supervisor_holds_cross_host_fence_across_recovery_and_drain(service_store,monkeypatch):
    from agentic_rag.service.runner import run
    from agentic_rag import worker
    cfg,_=service_store;stop=threading.Event();events=[]
    def recovery(conn,cfg):
        with worker.acquire_database_lock(cfg) as other:assert other is None
        events.append('recover')
    def drain(conn,cfg,**kwargs):
        conn.commit()
        with worker.acquire_database_lock(cfg) as other:assert other is None
        events.append('drain');stop.set()
        return {'done':0,'failed':0,'provider_unavailable':0}
    monkeypatch.setattr(worker,'requeue_orphans',recovery)
    monkeypatch.setattr(worker,'drain',drain)
    assert run(cfg,stop=stop,interval=.01)==0
    assert events==['recover','drain']
    with worker.acquire_database_lock(cfg) as recovered:assert recovered is not None
