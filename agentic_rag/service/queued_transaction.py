"""One canonical commit for a queued mutation and its durable result.

Legacy gateways may use multiple connection contexts/commit calls. Only queued
writes bind these to one outer transaction; ordinary local/service calls retain
normal psycopg semantics. Each actual data connection also pins execution.
"""
from contextvars import ContextVar
from contextlib import contextmanager

GROUP = ContextVar('rag_queued_transaction', default=None)
EXECUTION = ContextVar('rag_request_execution', default=None)


class ExecutionLost(RuntimeError):
    pass


def pin(conn):
    execution = EXECUTION.get()
    if execution is not None:
        execution.check()
        conn.execute('SELECT pg_advisory_lock_shared(%s)', (execution.key,))
        conn.commit()


class DeferredConnection:
    def __init__(self, group, real):
        self.group, self.real = group, real

    def __getattr__(self, name):
        return getattr(self.real, name)

    def commit(self):
        self.group.execution.check()
        self.real.check_commit_authority()

    def close(self):
        pass  # outer group owns this connection

    def rollback(self):
        self.group.aborted = True
        self.real.rollback()

    def __enter__(self):
        return self

    def __exit__(self, typ, value, tb):
        if typ is not None:
            self.rollback()
        else:
            self.commit()

    @contextmanager
    def transaction(self, *args, **kwargs):
        # A SELECT opened the root transaction before the first gateway call.
        with self.real.transaction(*args, **kwargs) as tx:
            yield tx
            self.commit()


class TransactionGroup:
    def __init__(self, cfg, execution):
        self.cfg, self.execution = cfg, execution
        self.real = self.proxy = None
        self.aborted = False

    def connection(self):
        if self.real is None:
            from .. import db
            token = GROUP.set(None)
            try:
                self.real = db.connect(self.cfg, role='writer')
            finally:
                GROUP.reset(token)
            self.real.execute('SELECT 1')
            self.proxy = DeferredConnection(self, self.real)
        if self.aborted:
            raise ExecutionLost('queued_transaction_aborted')
        return self.proxy

    def close(self):
        if self.real is not None:
            self.real.rollback()
            self.real.close()
