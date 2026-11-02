"""Finite shared compute admission: interactive work precedes log extraction."""
from contextlib import contextmanager
from contextvars import ContextVar
import uuid

from .engine import ResourcePressure

ACTIVE = ContextVar('rag_foreground_active', default=False)
MODEL_LOCK = 684096810
# Issue92 A2: separate admission for the optional legacy background daemon.
# At most one lane inference runs alongside one foreground inference.
BACKGROUND_MODEL_LOCK = 684096811


@contextmanager
def foreground(cfg):
    if ACTIVE.get():
        yield
        return
    from .requests import owner
    identity = uuid.uuid4()
    with owner(cfg) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('foreground_activity_admission'))")
        conn.execute('DELETE FROM service_foreground WHERE expires_at<=now()')
        if conn.execute('SELECT count(*) n FROM service_foreground').fetchone()['n'] >= 64:
            raise ResourcePressure('foreground_capacity_exceeded', 429)
        conn.execute("INSERT INTO service_foreground VALUES (%s,now()+interval '10 minutes')", (identity,))
    token = ACTIVE.set(True)
    try:
        yield
    finally:
        ACTIVE.reset(token)
        with owner(cfg) as conn:
            conn.execute('DELETE FROM service_foreground WHERE id=%s', (identity,))


def background_ready(cfg):
    if cfg.service_mode != 'server':
        return True
    from .requests import owner
    with owner(cfg) as conn:
        return not conn.execute("""SELECT EXISTS(SELECT 1 FROM service_foreground WHERE expires_at>now())
            OR EXISTS(SELECT 1 FROM service_requests WHERE expires_at>now() AND
                (state='running' OR (state='pending' AND COALESCE(code,'') NOT IN
                 ('backlog_full','owner_backlog_full','backlog_bytes_exceeded')))) busy""").fetchone()['busy']


def check_background(cfg):
    if not background_ready(cfg):
        raise ResourcePressure('foreground_busy', 429)


@contextmanager
def model_slot(cfg, *, background=False, lane=False):
    """One embedding call on the shared Ollama; no 20-session batch fan-out.

    `lane=True` (only the fenced legacy background route with a configured
    background daemon) uses its own lock; managed profiles never set it.
    """
    from .requests import owner
    if lane and not background:
        raise ValueError('the background lane admits only background work')
    if background:
        check_background(cfg)
    with owner(cfg) as conn:
        # A foreground waiter may wait finitely for a single <=10s background
        # call. Background never queues ahead of new foreground demand.
        conn.execute("SELECT set_config('lock_timeout',%s,true)", ('1ms' if background else '15000',))
        if background:
            key = BACKGROUND_MODEL_LOCK if lane else MODEL_LOCK
            if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) ok', (key,)).fetchone()['ok']:
                raise ResourcePressure('model_busy', 429)
            check_background(cfg)
        else:
            import psycopg
            try:
                conn.execute('SELECT pg_advisory_xact_lock(%s)', (MODEL_LOCK,))
            except psycopg.errors.LockNotAvailable:
                raise ResourcePressure('model_busy', 429) from None
        yield
