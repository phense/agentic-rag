"""Worker authority and execution pins survive separate connection failures."""
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg

OWNER_LOCK=5840919371552458
EXECUTION_LOCK=OWNER_LOCK+1
LEASE=ContextVar('rag_worker_lease',default=None)


class WorkerAuthorityLost(RuntimeError):
    def __init__(self):super().__init__('worker_authority_lost')


def assert_authority():
    keeper=LEASE.get()
    if keeper is None:return
    try:
        row=keeper.execute('''SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks
            WHERE locktype='advisory' AND pid=pg_backend_pid() AND granted
            AND classid=%s AND objid=%s AND objsubid=1) ok''',
            (OWNER_LOCK>>32,OWNER_LOCK&0xffffffff)).fetchone()
        keeper.commit()
        if not row['ok']:raise WorkerAuthorityLost()
    except psycopg.Error:
        raise WorkerAuthorityLost() from None


@contextmanager
def worker_scope(keeper):
    token=LEASE.set(keeper)
    try:
        assert_authority()
        yield
    finally:LEASE.reset(token)


class FencedConnection(psycopg.Connection):
    def execute(self,*args,**kwargs):
        assert_authority()
        return super().execute(*args,**kwargs)

    def commit(self):
        assert_authority()
        return super().commit()

    @contextmanager
    def transaction(self,*args,**kwargs):
        with super().transaction(*args,**kwargs) as transaction:
            yield transaction
            assert_authority()

    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()  # including a failed commit-authority check


def pin_execution(connection):
    # Every live data connection holds a shared execution pin. A replacement
    # owner must acquire the exclusive pin before orphan recovery. Losing only
    # the keeper or parent connection can never overlap an existing inference.
    row=connection.execute('SELECT pg_try_advisory_lock_shared(%s) ok',(EXECUTION_LOCK,)).fetchone()
    if not row['ok']:raise WorkerAuthorityLost()
    connection.commit()
    assert_authority()
    return connection
