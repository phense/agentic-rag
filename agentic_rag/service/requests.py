"""Durable bounded foreground tool requests. No prompt/result in public diagnostics."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import threading
import uuid

import psycopg
from psycopg.types.json import Jsonb

from .. import db, mcp_server
from .auth import AuthenticationError, resolve_reference
from .context import CURRENT, request_scope
from .engine import ResourcePressure, ServiceError, invoke, validator
from .ingest import credential_reference
from .queued_transaction import EXECUTION, GROUP, ExecutionLost, TransactionGroup

MAX_ACTIVE = 128
MAX_OWNER = 48
MAX_TEAM = 64
MAX_ROWS = 4096
TTL = 300
TERMINAL = {'completed', 'failed', 'cancelled', 'expired'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def permissions(principal):
    row = asdict(principal)
    return hashlib.sha256(encoded({k: sorted(v) if isinstance(v, frozenset) else v for k, v in row.items()})).hexdigest()


@contextmanager
def owner(cfg):
    token = CURRENT.set(None)
    group = GROUP.set(None)
    execution = EXECUTION.set(None)
    try:
        with db.connect(cfg) as conn:
            yield conn
    finally:
        EXECUTION.reset(execution)
        GROUP.reset(group)
        CURRENT.reset(token)


def cleanup(conn):
    # Only owner-side control state. Never delete acknowledged source evidence.
    conn.execute("UPDATE service_requests SET state='expired',code='request_expired',arguments=NULL,result=NULL,finished_at=now() WHERE expires_at<=now() AND state IN ('pending','running')")
    conn.execute("UPDATE service_requests SET code=CASE WHEN state='completed' THEN 'result_expired' ELSE code END,result=NULL,arguments=NULL WHERE expires_at<=now() AND (result IS NOT NULL OR arguments IS NOT NULL)")
    conn.execute("DELETE FROM service_requests WHERE expires_at<now()-interval '10 minutes'")


def public(row):
    result = {'request_id': str(row['id']), 'state': row['state'], 'durable': True,
              'expires_at': row['expires_at'].isoformat(), 'status_url':'/v1/requests/'+str(row['id']), 'retry_after':1}
    if row.get('code'):
        result['code'] = row['code']
    if row['state']=='completed' and row['expires_at']<=datetime.now(timezone.utc):
        result['code']='result_expired'
        row={**row,'result':None}
    if row['state'] == 'completed':
        result['result'] = row['result']
    return result


def authorize(cfg, row, principal=None):
    fresh = resolve_reference(cfg, row['authority'])
    if permissions(fresh) != row['permission_hash'] or (principal is not None and permissions(principal) != row['permission_hash']):
        raise AuthenticationError()
    return fresh


def submit(cfg, principal, value):
    if not isinstance(value, dict) or set(value) != {'idempotency_key', 'created_at', 'tool', 'arguments'}:
        raise ServiceError('invalid_request')
    try:
        key = str(uuid.UUID(value['idempotency_key']))
        timestamp = datetime.fromisoformat(value['created_at'])
        if timestamp.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError):
        raise ServiceError('invalid_request') from None
    if not isinstance(value['tool'], str) or not isinstance(value['arguments'], dict):
        raise ServiceError('invalid_request')
    _, write = validator(value['tool'])
    if write and principal.readonly:
        raise ServiceError('scope_denied', 403)
    data = encoded(value)
    if len(data) > 60*1024:
        raise ServiceError('request_too_large', 413)
    digest = hashlib.sha256(data).hexdigest()
    identity = uuid.uuid5(uuid.NAMESPACE_URL, principal.namespace + ':' + key)
    team = min(principal.session_teams) if principal.session_teams else principal.user_id
    from .resources import admission
    with admission(cfg, lock=5840919371552461) as budget, owner(cfg) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('foreground_queue_admission'))")
        cleanup(conn)
        existing = conn.execute('SELECT * FROM service_requests WHERE id=%s', (identity,)).fetchone()
        if existing:
            if existing['envelope_hash'] != digest:
                raise ServiceError('idempotency_conflict', 409)
            authorize(cfg, existing, principal)
            return public(existing)
        # Old envelopes cannot become fresh work after bounded tombstone cleanup.
        if abs((datetime.now(timezone.utc)-timestamp).total_seconds()) > 60:
            raise ServiceError('request_envelope_expired', 409)
        counts = conn.execute("""SELECT count(*) total,
            count(*) FILTER(WHERE state IN ('pending','running')) active,
            count(*) FILTER(WHERE state IN ('pending','running') AND owner_namespace=%s) own,
            count(*) FILTER(WHERE state IN ('pending','running') AND team=%s) team
            FROM service_requests""", (principal.namespace, team)).fetchone()
        if counts['total'] >= MAX_ROWS or counts['active'] >= MAX_ACTIVE or counts['own'] >= MAX_OWNER or counts['team'] >= MAX_TEAM:
            raise ServiceError('request_queue_full', 429)
        total=conn.execute('SELECT COALESCE(sum(octet_length(arguments::text)),0) bytes FROM service_requests').fetchone()['bytes']
        if total+len(data)>4*1024*1024:raise ServiceError('request_queue_bytes_exceeded',429)
        budget.check(incoming=len(data)*4+65536, owner=principal.namespace)
        row = conn.execute("""INSERT INTO service_requests
            (id,owner_namespace,team,envelope_hash,authority,permission_hash,tool,arguments,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()+interval '300 seconds') RETURNING *""",
            (identity, principal.namespace, team, digest, Jsonb(credential_reference(principal, None)),
             permissions(principal), value['tool'], Jsonb(value['arguments']))).fetchone()
        return public(row)


def status(cfg, principal, identity, *, cancel=False):
    try:
        identity = uuid.UUID(identity)
    except ValueError:
        raise ServiceError('not_found', 404) from None
    with owner(cfg) as conn:
        # Terminal read/cancel never appends an audit row or renews retention.
        row = conn.execute('SELECT * FROM service_requests WHERE id=%s AND owner_namespace=%s FOR UPDATE', (identity, principal.namespace)).fetchone()
        if row is None:
            raise ServiceError('not_found', 404)
        authorize(cfg, row, principal)
        if row['expires_at'] <= datetime.now(timezone.utc):
            if row['state'] not in TERMINAL:
                row = conn.execute("UPDATE service_requests SET state='expired',code='request_expired',arguments=NULL,result=NULL,finished_at=now() WHERE id=%s RETURNING *", (identity,)).fetchone()
            elif row['result'] is not None:
                return {**public({**row, 'result': None}), 'code': 'result_expired'}
        elif cancel and row['state'] not in TERMINAL:
            row = conn.execute("UPDATE service_requests SET state='cancelled',arguments=NULL,result=NULL,finished_at=now() WHERE id=%s RETURNING *", (identity,)).fetchone()
        return public(row)


class Execution:
    def __init__(self, keeper, row):
        self.keeper, self.row = keeper, row
        self.key = int.from_bytes(hashlib.sha256(('rag-queue:'+str(row['id'])).encode()).digest()[:8], 'big', signed=True)
        self.lock = threading.RLock()

    def check(self):
        with self.lock:
            try:
                row = self.keeper.execute('SELECT state,lease,expires_at FROM service_requests WHERE id=%s', (self.row['id'],)).fetchone()
                self.keeper.commit()
                if not row or row['state'] != 'running' or row['lease'] != self.row['lease'] or row['expires_at'] <= datetime.now(timezone.utc):
                    raise ExecutionLost('request_authority_lost')
            except psycopg.Error:
                raise ExecutionLost('request_authority_lost') from None


def claim(cfg):
    conn = None
    token = CURRENT.set(None)
    try:
        conn = db.connect(cfg)
        cleanup(conn)
        # Least recently dispatched team/owner first, then FIFO within owner.
        rows = conn.execute("""SELECT q.* FROM service_requests q
            WHERE state IN ('pending','running') AND expires_at>now() AND retry_at<=now()
            ORDER BY COALESCE((SELECT max(dispatched_at) FROM service_requests t WHERE t.team=q.team),'-infinity'),
             COALESCE((SELECT max(dispatched_at) FROM service_requests o WHERE o.owner_namespace=q.owner_namespace),'-infinity'),q.created_at
            LIMIT 128 FOR UPDATE OF q SKIP LOCKED""").fetchall()
        for row in rows:
            execution = Execution(conn, row)
            if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) ok', (execution.key,)).fetchone()['ok']:
                continue
            conn.execute('SELECT pg_advisory_lock_shared(%s)', (execution.key,))
            row = conn.execute("UPDATE service_requests SET state='running',lease=%s,dispatched_at=now() WHERE id=%s RETURNING *", (uuid.uuid4(), row['id'])).fetchone()
            conn.commit()
            execution.row = row
            return execution
        conn.commit()
        conn.close()
        return None
    except BaseException:
        if conn is not None:
            conn.close()
        raise
    finally:
        CURRENT.reset(token)


def finish(conn, execution, result):
    execution.check()
    row = conn.execute('SELECT state,lease,expires_at FROM service_requests WHERE id=%s FOR UPDATE', (execution.row['id'],)).fetchone()
    if not row or row['state'] != 'running' or row['lease'] != execution.row['lease'] or row['expires_at'] <= datetime.now(timezone.utc):
        raise ExecutionLost('request_authority_lost')
    conn.execute("UPDATE service_requests SET state='completed',result=%s,arguments=NULL,finished_at=now() WHERE id=%s", (Jsonb(result), execution.row['id']))
    conn.commit()


def run_one(cfg):
    execution = claim(cfg)
    if execution is None:
        return False
    row = execution.row
    group = None
    pin_connection = None
    token = EXECUTION.set(execution)
    try:
        pin_connection=db.connect(cfg)
        pin_connection.execute('SELECT pg_advisory_lock_shared(%s)',(execution.key,))
        pin_connection.commit()
        execution.check()
        principal = authorize(cfg, row)
        _, write = validator(row['tool'])
        group = TransactionGroup(cfg, execution) if write else None
        binding = GROUP.set(group)
        try:
            result = mcp_server._plain(asyncio.run(invoke(row['tool'], row['arguments'], principal, cfg)))
            if len(encoded(result)) > 120*1024:
                raise ServiceError('result_too_large', 413)
            authorize(cfg, row)
            # Serialize only bounded result publication, not tool execution.
            with owner(cfg) as budget:
                budget.execute("SET LOCAL lock_timeout='1s'")
                try:
                    budget.execute("SELECT pg_advisory_xact_lock(hashtext('request_result_budget'))")
                except psycopg.errors.LockNotAvailable:
                    # A competing publisher is transient pressure, not a failed
                    # accepted request. Roll back effects and retain its input.
                    raise ResourcePressure('result_capacity_exceeded',429) from None
                used=budget.execute('SELECT COALESCE(sum(octet_length(result::text)),0) bytes FROM service_requests').fetchone()['bytes']
                if used+len(encoded(result))>8*1024*1024:raise ServiceError('result_budget_exceeded',507)
                if group is not None:
                    with request_scope(principal,cfg):
                        connection=group.connection().real
                        finish(connection,execution,result)
                else:
                    finish(budget,execution,result)
        finally:
            GROUP.reset(binding)
    except Exception as exc:
        if group is not None:
            group.close()
            group = None
        code = exc.code if isinstance(exc, ServiceError) else 'authorization_changed' if isinstance(exc, AuthenticationError) else 'request_failed'
        with owner(cfg) as conn:
            if isinstance(exc,ResourcePressure):
                conn.execute("UPDATE service_requests SET state='pending',code=%s,lease=NULL,retry_at=now()+interval '1 second' WHERE id=%s AND lease=%s AND state='running'",(code,row['id'],row['lease']))
            else:
                conn.execute("UPDATE service_requests SET state='failed',code=%s,arguments=NULL,result=NULL,finished_at=now() WHERE id=%s AND lease=%s AND state='running'", (code, row['id'], row['lease']))
    finally:
        if group is not None:
            group.close()
        EXECUTION.reset(token)
        if pin_connection is not None:pin_connection.close()
        execution.keeper.close()
    return True


class Executor:
    """Exactly two consumers per API process, irrespective of session count."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.stop = asyncio.Event()
        self.tasks = []

    async def consume(self):
        while not self.stop.is_set():
            try:
                found = await asyncio.to_thread(run_one, self.cfg)
            except Exception:
                found = False  # next bounded poll; never log input or credentials
            if not found:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=0.2)
                except TimeoutError:
                    pass

    async def __aenter__(self):
        self.tasks = [asyncio.create_task(self.consume()) for _ in range(2)]
        return self

    async def __aexit__(self, *args):
        self.stop.set()
        # Do not cancel a to_thread call and start replacement work while its
        # underlying gateway is still alive. Gateway/model deadlines are finite.
        await asyncio.gather(*self.tasks)
