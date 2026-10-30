"""Bounded authenticated ASGI REST + stateless MCP transports."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import hmac
from importlib.metadata import version
import inspect
import ipaddress
import json
from pathlib import Path
import secrets
import time
import uuid
from typing import get_type_hints

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .. import db, mcp_server
from .auth import AuthenticationError, Policy, hash_key
from .context import CURRENT, request_scope
from .engine import ServiceError, invoke
from .schema import validate_schema

PROTOCOL='1'
MAX_BODY=1048576
BODY_TIMEOUT=5.0


class Gateway:
    def __init__(self, app, cfg, auth_file):
        self.app,self.cfg,self.auth_file=app,cfg,auth_file
        from .dashboard import Dashboard
        self.dashboard=Dashboard(cfg,auth_file)
        self.slots=asyncio.Semaphore(8)
        self.control_slots=asyncio.Semaphore(4)
        self.logins=OrderedDict()
        self.polls=OrderedDict()
        self.rejections=OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        request=Request(scope)
        path=scope['path']
        response_started=False
        async def tracked_send(message):
            nonlocal response_started
            if message['type']=='http.response.start':response_started=True
            await send(message)
        async def error(code,status):
            if path.startswith('/v1/requests') and status in {429,507}:
                self.rejections[code]=min(2**63-1,self.rejections.get(code,0)+1)
                while len(self.rejections)>16:self.rejections.popitem(last=False)
            if response_started:
                raise  # preserve the original downstream error after its 500 response
            await JSONResponse({'error':code},status_code=status)(scope,receive,send)
        if path=='/health':
            return await self.app(scope,receive,send)
        peer=(scope.get('client') or ('',0))[0]
        try:
            loopback=ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback=False
        if scope['scheme']!='https' and not loopback:
            return await error('tls_required',400)
        if path=='/dashboard' or path.startswith('/dashboard/'):
            return await self.dashboard(scope,receive,send)
        # Stateless JSON MCP has no server-initiated event channel. Reject it
        # before reserving shared capacity, including idle GET/SSE requests.
        if path.startswith('/mcp/') and scope['method']!='POST':
            return await JSONResponse({'error':'method_not_allowed'},status_code=405,
                headers={'Allow':'POST'})(scope,receive,send)
        if path.startswith('/v1/') and request.headers.get('x-rag-protocol')!=PROTOCOL:
            # Authentication absence has a uniform result, independent of version.
            if path!='/v1/login' and not request.headers.get('authorization'):
                return await error('invalid_credentials',401)
            return await error('unsupported_protocol',426)
        slots=self.control_slots if path.startswith('/v1/requests') else self.slots
        if slots.locked():
            return await error('capacity_exceeded',429)
        await slots.acquire()
        try:
            body=bytearray()
            async with asyncio.timeout(BODY_TIMEOUT):
                while True:
                    message=await receive()
                    if message['type']=='http.disconnect':
                        return
                    chunk=message.get('body',b'')
                    if len(body)+len(chunk)>MAX_BODY:
                        return await error('request_too_large',413)
                    body.extend(chunk)
                    if not message.get('more_body',False):
                        break
            consumed=False
            async def bounded_receive():
                nonlocal consumed
                if not consumed:
                    consumed=True
                    return {'type':'http.request','body':bytes(body),'more_body':False}
                return await receive()
            policy=await asyncio.to_thread(Policy.load,self.auth_file)
            state=scope.setdefault('state',{})
            state['policy']=policy
            if path=='/v1/login':
                now=time.monotonic()
                # One bounded bucket per transport peer, never asserted forwarding headers.
                start,count=self.logins.pop(peer,(now,0))
                if now-start>60:
                    start,count=now,0
                self.logins[peer]=(start,count+1)
                while len(self.logins)>1024:
                    self.logins.popitem(last=False)
                if count>=5:
                    return await error('login_rate_limited',429)
            else:
                scheme,_,token=request.headers.get('authorization','').partition(' ')
                if scheme.lower()!='bearer' or not token or len(token)>2048:
                    raise AuthenticationError()
                principal=await asyncio.to_thread(authenticate,policy,self.cfg,token)
                state['principal'],state['token_hash']=principal,hash_key(token)
                from .dashboard_presence import observe
                await asyncio.to_thread(observe,self.cfg,self.auth_file,principal,request.headers.get('x-rag-client-version',''),request.headers.get('x-rag-client-capabilities',''))
                if path.startswith('/v1/requests'):
                    now=time.monotonic()
                    start,count=self.polls.pop(principal.namespace,(now,0))
                    if now-start>=1:start,count=now,0
                    self.polls[principal.namespace]=(start,count+1)
                    while len(self.polls)>1024:self.polls.popitem(last=False)
                    if count>=12:return await error('request_rate_limited',429)
                if path.startswith('/mcp/rw') and principal.readonly:
                    raise ServiceError('scope_denied',403)
            if path.startswith('/mcp/'):
                with request_scope(state['principal'],self.cfg,read_only=path.startswith('/mcp/ro')):
                    await self.app(scope,bounded_receive,tracked_send)
            else:
                await self.app(scope,bounded_receive,tracked_send)
        except TimeoutError:
            await error('request_timeout',408)
        except AuthenticationError:
            await error('invalid_credentials',401)
        except ServiceError as exc:
            await error(exc.code,exc.status)
        except (ValueError,KeyError,TypeError,RecursionError):
            await error('invalid_request',400)
        finally:
            slots.release()


def authenticate(policy,cfg,token):
    if not token.startswith('session.'):
        return policy.authenticate_key(token)
    from dataclasses import replace
    from .auth import session_record
    reference=hash_key(token)
    row=session_record(cfg,reference)
    if row is None or not row['uploader_id'] or not hmac.compare_digest(row['password_revision'],policy.password_revision(row['user_id'])):
        raise AuthenticationError()
    return replace(policy.principal(row['user_id']),session_hash=reference,uploader_id=str(row['uploader_id']) if row['uploader_id'] else None)


def _remote_tool(fn, cfg, read_only):
    @wraps(fn)
    async def wrapped(*args,**kwargs):
        scope=CURRENT.get()
        if scope is None:
            raise ValueError('authentication_required')
        try:
            return await invoke(fn.__name__,kwargs,scope.principal,cfg,read_only=read_only)
        except ServiceError as exc:
            raise ValueError(exc.code) from None
    hints=get_type_hints(fn)
    signature=inspect.signature(fn)
    wrapped.__signature__=signature.replace(parameters=[p.replace(annotation=hints.get(p.name,p.annotation)) for p in signature.parameters.values()],return_annotation=dict)
    wrapped.__annotations__=hints
    return wrapped


def create_app(cfg, auth_file: Path, *, allowed_hosts=('localhost','127.0.0.1','[::1]')):
    from dataclasses import replace
    auth_file=Path(auth_file)
    cfg=replace(cfg,service_auth_file=auth_file)
    Policy.load(auth_file)  # fail startup on malformed/exposed credentials
    with db.connect(cfg) as conn:
        validate_schema(conn)  # never expose transports against an unprotected legacy store
    servers=[]
    mounts=[]
    for read_only,name in [(True,'ro'),(False,'rw')]:
        server=FastMCP('agentic-rag',stateless_http=True,json_response=True,
                       streamable_http_path='/',max_request_body_size=MAX_BODY,
                       # TrustedHostMiddleware below validates configured hosts on both transports.
                       transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
        for fn in (*mcp_server.READ_TOOLS,*(() if read_only else mcp_server.WRITE_TOOLS)):
            server.add_tool(_remote_tool(fn,cfg,read_only))
        mounts.append(Mount('/mcp/'+name,app=server.streamable_http_app()))
        servers.append(server)

    @asynccontextmanager
    async def lifespan(app):
        from .requests import Executor
        async with servers[0].session_manager.run(),servers[1].session_manager.run(),Executor(cfg):
            yield

    async def health(request):
        return JSONResponse({'status':'ok'})

    async def login(request):
        data=await request.json()
        if not isinstance(data,dict) or not {'username','password'}<=set(data) or set(data)-{'username','password','uploader_id'} or not all(isinstance(v,str) for v in data.values()) or len(data['username'])>80:
            raise ServiceError('invalid_request')
        try:uploader=str(uuid.UUID(data['uploader_id'])) if 'uploader_id' in data else str(uuid.uuid4())
        except ValueError:raise ServiceError('invalid_request') from None
        policy=request.state.policy
        principal=await asyncio.to_thread(policy.authenticate_password,data['username'],data['password'])
        from .dashboard import persist_session
        token,expiry=await asyncio.to_thread(persist_session,cfg,policy,principal,uploader)
        return JSONResponse({'access_token':token,'token_type':'Bearer','expires_at':expiry.isoformat(),'uploader_id':uploader})

    async def logout(request):
        if request.state.principal.machine_id is not None:
            raise ServiceError('human_session_required',403)
        def remove():
            with db.connect(cfg) as conn:
                conn.execute('DELETE FROM service_sessions WHERE token_hash=%s',(request.state.token_hash,))
        await asyncio.to_thread(remove)
        return JSONResponse({'logged_out':True})

    async def capabilities(request):
        p=request.state.principal
        def schema():
            with db.connect(cfg,role='reader') as conn:
                return [r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
        return JSONResponse({'extensions':{'queued_tools':1},'protocol':1,'server_version':version('agentic-rag'),'migrations':await asyncio.to_thread(schema),
                             'tools':mcp_server.tool_names(p.readonly),'limits':{'request_bytes':MAX_BODY,'window_chars':12000,'window_events':64,'inflight_requests':8},
                             'principal':{'user':p.user_id,'machine':p.machine_id,'read_only':p.readonly}})

    async def tool(request):
        args=await request.json()
        result=await invoke(request.path_params['name'],args,request.state.principal,cfg)
        return JSONResponse(mcp_server._plain(result))

    async def queued_request(request):
        from . import requests as queue
        if 'identity' not in request.path_params:
            try:result=await asyncio.to_thread(queue.submit,cfg,request.state.principal,await request.json())
            except ServiceError as exc:
                if exc.status in {429,507}:
                    gateway.rejections[exc.code]=min(2**63-1,gateway.rejections.get(exc.code,0)+1)
                    while len(gateway.rejections)>16:gateway.rejections.popitem(last=False)
                raise
            if request.headers.get('prefer')=='wait=0.1':
                deadline=time.monotonic()+.1
                while result['state'] in {'pending','running'} and time.monotonic()<deadline:
                    await asyncio.sleep(.01)
                    result=await asyncio.to_thread(queue.status,cfg,request.state.principal,result['request_id'])
            return JSONResponse(result,status_code=200 if result['state']=='completed' and request.headers.get('prefer')=='wait=0.1' else 202,headers={'Retry-After':'1'})
        result=await asyncio.to_thread(queue.status,cfg,request.state.principal,
            request.path_params['identity'],cancel=request.method=='POST')
        return JSONResponse(result,headers={'Retry-After':'1'})

    async def checkpoint(request):
        from . import checkpoints
        if request.method=='POST':
            data=await request.json()
            result=await asyncio.to_thread(checkpoints.save,cfg,request.state.principal,data)
        else:
            result=await asyncio.to_thread(checkpoints.latest,cfg,request.state.principal,request.path_params['session'])
        return JSONResponse(mcp_server._plain(result))

    async def submit_window(request):
        from .ingest import accept
        data=await request.json()
        result=await asyncio.to_thread(accept,cfg,request.state.principal,request.state.policy,data)
        return JSONResponse(result,status_code=202)

    async def job_status(request):
        from .ingest import receipt_status
        result=await asyncio.to_thread(receipt_status,cfg,request.state.principal,request.path_params['receipt'],cancel=request.method=='POST')
        return JSONResponse(mcp_server._plain(result))

    async def job_retry(request):
        from .ingest import retry_receipt
        result=await asyncio.to_thread(retry_receipt,cfg,request.state.principal,request.state.policy,request.path_params['receipt'])
        return JSONResponse(mcp_server._plain(result))

    async def session_logs(request):
        from . import session_logs as logs
        principal=request.state.principal
        if 'session' not in request.path_params:
            result=await asyncio.to_thread(logs.listing,cfg,principal,
                before=request.query_params.get('before'),limit=int(request.query_params.get('limit','50')))
        elif request.path_params['kind']=='windows':
            result=await asyncio.to_thread(logs.windows,cfg,principal,request.path_params['session'],
                after=request.query_params.get('after'),limit=int(request.query_params.get('limit','1')))
        elif request.path_params['kind']=='checkpoint':
            result=await asyncio.to_thread(logs.checkpoint,cfg,principal,request.path_params['session'])
        else:raise ServiceError('not_found',404)
        return JSONResponse(mcp_server._plain(result))

    async def admin_status(request):
        if not request.state.principal.admin:
            raise ServiceError('administrator_required',403)
        def counts():
            with db.connect(cfg) as conn:
                return {r['status']:r['n'] for r in conn.execute('SELECT status,count(*) n FROM mining_queue GROUP BY status')}
        policy=request.state.policy
        machines=[{'id':name,'label':row.get('label',name),'enabled':row.get('enabled',True),'user':row['user']} for name,row in policy.machines.items()]
        def foreground_counts():
            with db.connect(cfg) as conn:
                return conn.execute("""SELECT count(*) FILTER(WHERE state='pending') pending,
                    count(*) FILTER(WHERE state='running') running,
                    COALESCE(max(EXTRACT(epoch FROM now()-created_at)) FILTER(WHERE state='pending'),0)::float oldest_seconds,
                    COALESCE(sum(octet_length(arguments::text)),0) input_bytes,
                    COALESCE(sum(octet_length(result::text)),0) result_bytes,
                    count(*) FILTER(WHERE state='expired') expired,
                    count(*) FILTER(WHERE code='result_expired') result_expired,
                    COALESCE(percentile_cont(0.95) WITHIN GROUP(ORDER BY EXTRACT(epoch FROM dispatched_at-created_at)),0)::float wait_p95_seconds,
                    COALESCE(percentile_cont(0.95) WITHIN GROUP(ORDER BY EXTRACT(epoch FROM finished_at-dispatched_at)),0)::float execution_p95_seconds
                    FROM service_requests""").fetchone()
        def fairness():
            with db.connect(cfg) as conn:
                return conn.execute("SELECT team,count(*) FILTER(WHERE state='pending') pending,count(*) FILTER(WHERE state='running') running,count(*) FILTER(WHERE state='completed') completed,COALESCE(max(extract(epoch FROM now()-created_at)) FILTER(WHERE state='pending'),0)::float oldest_seconds FROM service_requests GROUP BY team ORDER BY team LIMIT 64").fetchall()
        return JSONResponse({'status':'ok','queue':await asyncio.to_thread(counts),
            'admission_rejections':dict(gateway.rejections) if isinstance(gateway,Gateway) else {},
            'fairness':await asyncio.to_thread(fairness),
            'foreground':await asyncio.to_thread(foreground_counts),'machines':machines,'protocol':1})

    async def openapi(request):
        from .openapi import document
        tools=await mcp_server.build_server(request.state.principal.readonly).list_tools()
        return JSONResponse(document(tools))

    routes=[Route('/v1/requests',queued_request,methods=['POST']),Route('/v1/requests/{identity}',queued_request),Route('/v1/requests/{identity}/cancel',queued_request,methods=['POST']),Route('/v1/checkpoints',checkpoint,methods=['POST']),Route('/v1/checkpoints/{session:path}',checkpoint),Route('/v1/windows',submit_window,methods=['POST']),Route('/v1/jobs/{receipt}',job_status),Route('/v1/jobs/{receipt}/cancel',job_status,methods=['POST']),Route('/health',health),Route('/v1/login',login,methods=['POST']),Route('/v1/logout',logout,methods=['POST']),Route('/v1/capabilities',capabilities),Route('/v1/tools/{name}',tool,methods=['POST']),Route('/v1/admin/status',admin_status),Route('/v1/openapi.json',openapi),*mounts]
    routes.insert(0,Route('/v1/jobs/{receipt}/retry',job_retry,methods=['POST']))
    routes.insert(0,Route('/v1/sessions',session_logs))
    routes.insert(0,Route('/v1/sessions/{session}/{kind}',session_logs))
    async def service_error(request, exc):
        return JSONResponse({'error':exc.code},status_code=exc.status)
    async def authentication_error(request, exc):
        return JSONResponse({'error':'invalid_credentials'},status_code=401)
    async def invalid_request(request, exc):
        return JSONResponse({'error':'invalid_request'},status_code=400)
    app=Starlette(routes=routes,lifespan=lifespan,exception_handlers={ServiceError:service_error,AuthenticationError:authentication_error,ValueError:invalid_request})
    gateway=Gateway(app,cfg,auth_file)
    return TrustedHostMiddleware(gateway,allowed_hosts=list(allowed_hosts))
