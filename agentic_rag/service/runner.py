"""Central serial inference loop; DB ownership precedes orphan recovery."""
import signal
import threading
import psycopg

from .. import db,worker
from ..config import load_config
from .schema import validate_schema
from .fence import worker_scope, WorkerAuthorityLost, assert_authority


def run(cfg,*,stop=None,interval=5):
    if cfg.service_mode=='client':raise ValueError('central worker cannot run in client mode')
    if not .01<=interval<=3600:raise ValueError('invalid worker interval')
    stop=stop if stop is not None else threading.Event()
    try:
        with worker.acquire_database_lock(cfg) as singleton:
            if singleton is None:return 1
            with worker_scope(singleton), db.connect(cfg,role='writer') as conn:
                validate_schema(conn)
                worker.requeue_orphans(conn,cfg)
                while not stop.is_set():
                    assert_authority()
                    worker.drain(conn,cfg,max_jobs=8,stop=stop)
                    assert_authority()
                    stop.wait(interval)
    except (WorkerAuthorityLost, psycopg.Error):
        return 1
    return 0


def run_with_signals(cfg):
    stop=threading.Event()
    previous={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        for sig in previous:signal.signal(sig,lambda *_:stop.set())
        return run(cfg,stop=stop)
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


def main():
    return run_with_signals(load_config())


if __name__=='__main__':raise SystemExit(main())
