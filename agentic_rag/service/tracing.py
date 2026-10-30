"""Bounded metadata-only diagnostics. This module never reads an HTTP body or URL.

The owner-only relation has application SQL scope predicates, not broad SQL grants.
Operational failure is isolated from the already completed canonical transaction.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
import json
import logging
import re
import threading
import time
import uuid

import psycopg
from psycopg.rows import dict_row

from .. import db, mcp_server
from .engine import ServiceError
from .auth import AuthenticationError

MAX_ROWS=20000
MAX_BYTES=64*1024*1024
PRUNE_BATCH=1000
SLOTS=threading.BoundedSemaphore(4)
CURRENT_TRACE=ContextVar('service_trace',default=None)
VERSION=version('agentic-rag')
SAFE_VERSION=re.compile(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:[a-z][0-9]{1,5})?\Z')
# Error classifications are static categories. Never retain arbitrary exception codes.
ERRORS={'invalid_credentials','scope_denied','invalid_request','not_found','unsupported_protocol',
        'request_too_large','capacity_exceeded','request_timeout','provider_unavailable',
        'provider_refused','authorization_changed','request_failed','disconnected','http_error',
        'mcp_error','operation_failed','internal_error','tls_required','tracing_unavailable','origin_denied','csrf_denied'}


def policy_id(cfg):
    from .dashboard_policy import identity
    return identity(cfg.service_auth_file)


def safe_uuid(value):
    try:return str(uuid.UUID(value)) if isinstance(value,str) and len(value)<=36 else None
    except (ValueError,TypeError,AttributeError):return None


@dataclass
class Trace:
    request_id: str
    correlation_id: str | None
    started_at: datetime
    operation: str='unknown'
    principal: object=None
    client_version: str=''
    error_class: str | None=None
    outcome: str | None=None
    job_id: str | None=None
    job_kind: str | None=None


def authenticated(principal):
    trace=CURRENT_TRACE.get()
    if trace is not None:trace.principal=principal


def semantic_error(code='mcp_error'):
    trace=CURRENT_TRACE.get()
    if trace is not None:
        trace.error_class=code if code in ERRORS else 'mcp_error'
        trace.outcome='failed'


def link_job(identity,kind,*,accepted=False):
    trace=CURRENT_TRACE.get()
    if trace is not None:
        trace.job_id=safe_uuid(str(identity));trace.job_kind=kind
        if accepted:trace.outcome='accepted'


def origin():
    trace=CURRENT_TRACE.get()
    return (trace.request_id,trace.correlation_id) if trace else (None,None)


def operation(scope):
    """Choose fixed vocabulary only. Route values and unknown tool names are discarded."""
    path=scope.get('path','');method=scope.get('method','')
    fixed={'/health':'health','/v1/login':'login','/v1/logout':'logout',
           '/v1/capabilities':'capabilities','/v1/openapi.json':'openapi',
           '/v1/windows':'source.submit','/v1/requests':'foreground.submit',
           '/v1/admin/status':'admin.status','/v1/sessions':'sessions.list',
           '/v1/checkpoints':'checkpoints.save','/dashboard':'dashboard.page',
           '/dashboard/':'dashboard.page','/dashboard/app.js':'dashboard.asset',
           '/dashboard/style.css':'dashboard.asset'}
    if path in fixed:return fixed[path]
    if path.startswith('/v1/tools/'):
        name=path.removeprefix('/v1/tools/')
        return 'tool.'+name if name in mcp_server.tool_names(False) else 'tool.unknown'
    if path.startswith('/mcp/'):return 'mcp'
    for prefix,label in [('/v1/jobs/','source'),('/v1/requests/','foreground')]:
        if path.startswith(prefix):
            parts=path[len(prefix):].split('/')
            if safe_uuid(parts[0]):
                suffix=parts[1] if len(parts)==2 and parts[1] in {'cancel','retry'} else 'status'
                return label+'.'+suffix
    if path.startswith('/v1/checkpoints/'):return 'checkpoints.latest'
    if path.startswith('/v1/sessions/'):return 'sessions.detail'
    if path=='/v1/traces' or path=='/dashboard/api/traces':return 'traces.list'
    if path=='/v1/traces/export' or path=='/dashboard/api/traces/export':return 'traces.export'
    if path.startswith('/v1/traces/') or path.startswith('/dashboard/api/traces/'):return 'traces.detail'
    if path.startswith('/dashboard/api/'):
        endpoint=path.removeprefix('/dashboard/api/')
        if endpoint in {'me','login','logout','bootstrap','overview','admin','policy','policy/preview','policy/apply','memories','tools','setup','setup/check','setup/complete'}:
            return 'dashboard.'+endpoint.replace('/','.')
        for prefix,label in [('requests/','foreground'),('memories/','memory')]:
            if endpoint.startswith(prefix):return 'dashboard.'+label
    return 'unknown'


@contextmanager
def connection(cfg):
    # Deliberate owner path; never reuse an audited/scoped business connection.
    with psycopg.connect(db.dsn(cfg),row_factory=dict_row,connect_timeout=1,
        options='-c statement_timeout=750 -c lock_timeout=150 -c idle_in_transaction_session_timeout=1500') as conn:
        yield conn


def prune_connection(conn):
    rows=conn.execute("""DELETE FROM request_traces WHERE request_id IN (
        SELECT request_id FROM request_traces WHERE started_at<now()-interval '7 days'
        ORDER BY started_at,request_id LIMIT %s) RETURNING request_id""",(PRUNE_BATCH,)).fetchall()
    return len(rows)


def prune(cfg):
    with connection(cfg) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('request_trace_budget'))")
        return {'pruned':prune_connection(conn),'batch_limit':PRUNE_BATCH,'retention_days':7}


class ProtocolObserver:
    """Observe typed MCP errors before JSON serialization, without result text.

    Delegate the low-level public server run interface; no global SDK patches.
    SessionMessage is already produced by MCP, never copied or retained here.
    """
    def __init__(self,server):self.server=server
    def __getattr__(self,name):return getattr(self.server,name)

    async def run(self,read_stream,write_stream,*args,**kwargs):
        from mcp.types import JSONRPCError,JSONRPCResponse
        class Output:
            def __getattr__(self,name):return getattr(write_stream,name)
            async def __aenter__(self):
                await write_stream.__aenter__()
                return self
            async def __aexit__(self,*exc):return await write_stream.__aexit__(*exc)
            async def send(self,message):
                root=message.message.root
                if isinstance(root,JSONRPCError) or (isinstance(root,JSONRPCResponse) and isinstance(root.result,dict) and root.result.get('isError') is True):
                    trace=CURRENT_TRACE.get()
                    if trace is not None and trace.outcome!='failed':semantic_error('mcp_error')
                await write_stream.send(message)
        return await self.server.run(read_stream,Output(),*args,**kwargs)


class Recorder:
    def __init__(self,cfg):
        self.cfg=cfg
        self.degraded=False
        self.dropped=0
        self.last_diagnostic=0.0
        self.lock=threading.Lock()

    def failure(self):
        with self.lock:
            self.degraded=True;self.dropped=min(2**63-1,self.dropped+1)
            now=time.monotonic()
            if now-self.last_diagnostic>=60:
                self.last_diagnostic=now
                logging.getLogger(__name__).warning('request_tracing_degraded')

    def record(self,trace,status,size,duration):
        if not SLOTS.acquire(blocking=False):self.failure();return
        try:
            p=trace.principal
            domains=sorted(p.read_domains | p.write_domains) if p else []
            projects=sorted(p.read_projects | p.write_projects) if p else []
            if len(domains)>64 or len(projects)>64 or len(json.dumps([domains,projects]).encode())>15000:
                self.failure();return
            row={'request_id':trace.request_id,'policy_id':policy_id(self.cfg),'started_at':trace.started_at,
                 'correlation_id':trace.correlation_id,'principal':p.user_id if p else None,
                 'client':p.machine_id if p else None,'owner_namespace':p.namespace if p else None,
                 'read_domains':domains,'read_projects':projects,'operation':trace.operation,
                 'status':status,'outcome':trace.outcome or ('failed' if status>=400 else 'completed'),
                 'error_class':trace.error_class or ('http_error' if status>=400 else None),
                 'duration_ms':max(0,min(duration,1e12-1)),'response_bytes':size,
                 'server_version':VERSION,'client_version':trace.client_version,
                 'job_id':trace.job_id,'job_kind':trace.job_kind}
            logical=len(json.dumps(row,default=str).encode())+512
            row['logical_bytes']=logical
            with connection(self.cfg) as conn:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext('request_trace_budget'))")
                prune_connection(conn)
                budget=conn.execute('SELECT count(*) n,coalesce(sum(logical_bytes),0) bytes FROM request_traces t').fetchone()
                if budget['n']>=MAX_ROWS or budget['bytes']+logical>MAX_BYTES:
                    self.failure();return
                from .resources import Budget
                Budget(conn,self.cfg).check(incoming=logical+8192)
                columns=','.join(row)
                conn.execute('INSERT INTO request_traces ('+columns+') VALUES ('+','.join(['%s']*len(row))+')',list(row.values()))
        except Exception:
            self.failure() # static diagnostic only, no repr/traceback/error strings
        finally:SLOTS.release()

    def capture(self,principal):
        if principal.admin and '*' in principal.read_domains and '*' in principal.read_projects:
            return {'status':'degraded' if self.degraded else 'ok','dropped':self.dropped,'payload_capture':False}
        return {'status':'restricted','payload_capture':False}


class Middleware:
    def __init__(self,app,recorder):
        self.app,self.recorder=app,recorder
        self.allowed_hosts=app.allowed_hosts
        self.pending=0

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        # Header reads have fixed names and bounded values. No generic headers copy.
        correlation=None;client_version=''
        for name,value in scope.get('headers',[]):
            if name==b'x-rag-correlation-id' and len(value)<=36:
                try:correlation=safe_uuid(value.decode('ascii'))
                except UnicodeDecodeError:pass
            if name==b'x-rag-client-version' and len(value)<=40:
                try:candidate=value.decode('ascii')
                except UnicodeDecodeError:continue
                if SAFE_VERSION.fullmatch(candidate):client_version=candidate
        trace=Trace(str(uuid.uuid4()),correlation,datetime.now(timezone.utc),operation(scope),client_version=client_version)
        binding=CURRENT_TRACE.set(trace);started=time.monotonic();status=500;size=0;response_started=False
        async def traced_send(message):
            nonlocal status,size,response_started
            if message['type']=='http.response.start':
                status=message['status'];response_started=True
                message={**message,'headers':[(k,v) for k,v in message.get('headers',[]) if k.lower()!=b'x-rag-request-id']+[(b'x-rag-request-id',trace.request_id.encode())]}
            # Count bytes actually emitted; never retain or parse body content.
            await send(message)
            if message['type']=='http.response.body':size+=len(message.get('body',b''))
        try:
            await self.app(scope,receive,traced_send)
            if not response_started:trace.outcome='disconnected';trace.error_class='disconnected'
        except BaseException:
            semantic_error('internal_error')
            raise
        finally:
            # Await bounded work; no detached per-request tasks or new inference.
            try:
                if self.pending>=4:self.recorder.failure()
                else:
                    self.pending+=1
                    loop=asyncio.get_running_loop()
                    duration=(time.monotonic()-started)*1000
                    def release():self.pending-=1
                    def record():
                        try:self.recorder.record(trace,status,size,duration)
                        finally:
                            try:loop.call_soon_threadsafe(release)
                            except RuntimeError:pass # closed loop, process is terminating
                    try:future=loop.run_in_executor(None,record)
                    except Exception:
                        release();self.recorder.failure()
                    else:
                        try:await asyncio.shield(future)
                        except asyncio.CancelledError:pass # the bounded thread still owns admission
                        except Exception:self.recorder.failure()
            finally:CURRENT_TRACE.reset(binding)


FIELDS='request_id,started_at,correlation_id,principal,client,operation,status,outcome,error_class,duration_ms,response_bytes,server_version,client_version,job_id,job_kind'
FILTERS={'since','until','principal','client','operation','status','request_id','correlation_id','job_id','limit','cursor'}


def _time(value):
    try:
        if not isinstance(value,str) or len(value)>40:raise ValueError()
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None:raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError):raise ServiceError('invalid_filter') from None


def _scope(cfg,principal):
    # Identity alone is insufficient after scope revocation. Entire original read
    # and write envelope must fit current read permissions, even for an owner.
    clauses=['policy_id=%s',"started_at>=now()-interval '7 days'"]
    params=[policy_id(cfg)]
    if not principal.read_domains or not principal.read_projects:
        return clauses+['false'],params
    full=principal.admin and '*' in principal.read_domains and '*' in principal.read_projects
    if not full:
        clauses.append('principal IS NOT NULL AND cardinality(read_domains)>0 AND cardinality(read_projects)>0')
        if not principal.admin:
            if principal.machine_id is None:clauses.append('principal=%s');params.append(principal.user_id)
            else:clauses.append('owner_namespace=%s');params.append(principal.namespace)
        if '*' not in principal.read_domains:
            clauses.append('read_domains <@ %s::text[]');params.append(sorted(principal.read_domains))
        if '*' not in principal.read_projects:
            clauses.append('read_projects <@ %s::text[]');params.append(sorted(principal.read_projects))
    return clauses,params


def plain(row):
    return {k:(v.isoformat() if isinstance(v,datetime) else str(v) if isinstance(v,uuid.UUID) else v) for k,v in row.items()}


def listing(cfg,principal,query,*,export=False,recorder=None):
    if export and not principal.admin:raise ServiceError('administrator_required',403)
    if set(query)-FILTERS:raise ServiceError('invalid_filter')
    try:limit=int(query.get('limit','25'))
    except (ValueError,TypeError):raise ServiceError('invalid_pagination') from None
    if not 1<=limit<=50:raise ServiceError('invalid_pagination')
    clauses,params=_scope(cfg,principal)
    anchor=datetime.now(timezone.utc);after=None
    if query.get('cursor'):
        try:
            raw=query['cursor']
            if len(raw)>512:raise ValueError()
            values=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
            if not isinstance(values,list) or len(values)!=3:raise ValueError()
            cursor_id=safe_uuid(values[2])
            if cursor_id is None:raise ValueError()
            anchor=_time(values[0]);after=(_time(values[1]),cursor_id)
            if after[0]>anchor or anchor>datetime.now(timezone.utc):raise ValueError()
        except (ValueError,TypeError,KeyError,UnicodeError,ServiceError):raise ServiceError('invalid_cursor') from None
    clauses.append('started_at<=%s');params.append(anchor)
    for key,column in [('since','started_at>='),('until','started_at<='),('principal','principal='),('client','client='),('operation','operation='),('status','status='),('request_id','request_id='),('correlation_id','correlation_id='),('job_id','job_id=')]:
        value=query.get(key)
        if not value:continue
        if key in {'since','until'}:value=_time(value)
        elif key.endswith('_id'):
            value=safe_uuid(value)
            if value is None:raise ServiceError('invalid_filter')
        elif key=='status':
            try:value=int(value)
            except (ValueError,TypeError):raise ServiceError('invalid_filter') from None
            if not 100<=value<=599:raise ServiceError('invalid_filter')
        elif not isinstance(value,str) or len(value)>96 or '\x00' in value:raise ServiceError('invalid_filter')
        clauses.append(column+'%s');params.append(value)
    where=' AND '.join(clauses)
    try:
        with connection(cfg) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total=conn.execute('SELECT count(*) n FROM request_traces WHERE '+where,params).fetchone()['n']
            if after:where+=' AND (started_at,request_id)<(%s,%s)';params+=list(after)
            rows=conn.execute('SELECT '+FIELDS+' FROM request_traces WHERE '+where+' ORDER BY started_at DESC,request_id DESC LIMIT %s',params+[limit+1]).fetchall()
        next_cursor=None
        if len(rows)>limit:
            last=rows[limit-1]
            next_cursor=base64.urlsafe_b64encode(json.dumps([anchor.isoformat(),last['started_at'].isoformat(),str(last['request_id'])]).encode()).decode().rstrip('=')
        return {'rows':[plain(r) for r in rows[:limit]],'total':total,'next_cursor':next_cursor,
                'capture':recorder.capture(principal) if recorder else {'status':'restricted','payload_capture':False}}
    except psycopg.Error:raise ServiceError('tracing_unavailable',503) from None


def detail(cfg,principal,identity,*,recorder=None):
    identity=safe_uuid(identity)
    if not identity:raise ServiceError('not_found',404)
    found=listing(cfg,principal,{'request_id':identity,'limit':'1'},recorder=recorder)
    if not found['rows']:raise ServiceError('not_found',404)
    row=found['rows'][0];job=None
    if row['job_id']:
        try:
            if row['job_kind']=='source':
                from .ingest import receipt_status
                job=receipt_status(cfg,principal,row['job_id'])
            elif row['job_kind']=='foreground':
                from .requests import status
                result=status(cfg,principal,row['job_id'])
                # Foreground status can contain tool knowledge. Only metadata here.
                job={k:v for k,v in result.items() if k in {'request_id','state','durable','expires_at','code','origin_request_id','origin_correlation_id'}}
                if job.get('code') not in {'request_expired','result_expired','authorization_changed','request_failed','provider_unavailable','result_too_large','result_budget_exceeded','result_capacity_exceeded','scope_denied','invalid_arguments','operation_failed'}:job.pop('code',None)
                if result['state']=='completed' and isinstance(result.get('result'),dict) and result['result'].get('error'):job['outcome']='failed'
        except (ServiceError,PermissionError,AuthenticationError):job=None
    if job and job.get('state')=='completed' and job.get('code')!='result_expired':job.pop('code',None)
    return {'trace':row,'job':mcp_server._plain(job),'capture':found['capture']}
