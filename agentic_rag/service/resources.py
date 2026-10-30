"""Finite central admission budgets; acknowledged evidence is never evicted."""
from contextlib import contextmanager
from pathlib import Path
import shutil

from .. import db
from .context import CURRENT
from .engine import ResourcePressure

ADMISSION_LOCK=5840919371552460


class Budget:
    def __init__(self,conn,cfg):self.conn,self.cfg=conn,cfg

    def check(self,*,owner=None,incoming=0,queue=False):
        cfg,conn=self.cfg,self.conn
        size=conn.execute('SELECT pg_database_size(current_database()) bytes').fetchone()['bytes']
        if size+incoming>cfg.service_max_database_bytes:
            raise ResourcePressure('database_budget_exceeded',507)
        # This process must share the DB filesystem or receive its explicit local
        # mount in storage_path. Remote PostgreSQL is not silently measured on /.
        try:
            location=cfg.service_storage_path
            if location is None:
                if cfg.db_host and cfg.db_host not in {'localhost','127.0.0.1','::1'}:
                    raise OSError('remote storage path required')
                location=Path(conn.execute('SHOW data_directory').fetchone()['data_directory'])
            free=shutil.disk_usage(location).free
        except OSError:
            raise ResourcePressure('storage_check_unavailable',503) from None
        if free<cfg.service_min_free_bytes+incoming:
            raise ResourcePressure('storage_low',507)
        if not queue:return
        pending=conn.execute("SELECT count(*) n FROM public.mining_queue WHERE status IN ('pending','processing','error')").fetchone()['n']
        if pending>=cfg.service_max_pending:raise ResourcePressure('backlog_full',429)
        rows=conn.execute("""SELECT count(*) FILTER(WHERE owner_namespace=%s) own,
            COALESCE(sum(octet_length(payload::text)),0) bytes FROM public.service_windows
            WHERE state NOT IN ('applied','cancelled')""",(owner,)).fetchone()
        if rows['own']>=cfg.service_max_pending_per_owner:raise ResourcePressure('owner_backlog_full',429)
        if rows['bytes']+incoming>cfg.service_max_pending_bytes:raise ResourcePressure('backlog_bytes_exceeded',429)


@contextmanager
def admission(cfg):
    # Only this fixed aggregate check uses the trusted owner connection. It never
    # accepts SQL or returns other principals' rows to the caller. Scoped business
    # connections retain their original authority, including worker fencing.
    token=CURRENT.set(None)
    try:conn=db.connect(cfg)
    finally:CURRENT.reset(token)
    try:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) ok',(ADMISSION_LOCK,)).fetchone()['ok']:
            raise ResourcePressure('write_capacity_exceeded',429)
        yield Budget(conn,cfg)
    finally:conn.close()  # read-only aggregate transaction releases the gate


def check_worker(cfg):
    with admission(cfg) as budget:budget.check(incoming=1048576)
