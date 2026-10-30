"""Browser boundary: cookie sessions never authenticate the legacy Bearer API."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime,timedelta,timezone
import hmac
import ipaddress
import json
from pathlib import Path
import secrets
import time
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse,Response

from .. import db
from .auth import AuthenticationError,Policy,hash_key
from .engine import ServiceError
from . import dashboard_policy as policies

ASSETS=Path(__file__).with_name('dashboard_assets')
ASSET_NAMES={'app.js':'text/javascript','style.css':'text/css','index.html':'text/html'}
SAFE_HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
              'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
              'Permissions-Policy':'camera=(), microphone=(), geolocation=()'}


def cookie_name(request):
    return '__Host-rag_dashboard' if request.url.scheme=='https' else 'rag_dashboard_loopback'


def persist_session(cfg,policy,principal,uploader=None):
    token='session.'+secrets.token_urlsafe(32)
    uploader=uploader or str(uuid.uuid4())
    expiry=datetime.now(timezone.utc)+timedelta(hours=8)
    with db.connect(cfg) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('service_session_enrollment'))")
        conn.execute('DELETE FROM service_sessions WHERE expires_at<=now()')
        row=conn.execute('SELECT count(*) n,count(*) FILTER(WHERE user_id=%s) own FROM service_sessions',(principal.user_id,)).fetchone()
        if row['n']>=10000 or row['own']>=16:raise ServiceError('session_capacity_exceeded',429)
        # Recheck file authority after the expensive password operation.
        fresh=Policy.load(cfg.service_auth_file)
        if fresh.password_revision(principal.user_id)!=policy.password_revision(principal.user_id):raise AuthenticationError()
        fresh.principal(principal.user_id)
        conn.execute('INSERT INTO service_sessions(token_hash,user_id,password_revision,uploader_id,expires_at) VALUES (%s,%s,%s,%s,%s)',(hash_key(token),principal.user_id,policy.password_revision(principal.user_id),uploader,expiry))
    return token,expiry


class Dashboard:
    def __init__(self,cfg,path):
        self.cfg,self.path=cfg,Path(path)
        self.slots=asyncio.Semaphore(4)
        self.attempts=OrderedDict()

    async def __call__(self,scope,receive,send):
        request=Request(scope,receive)
        path=scope['path'].removeprefix('/dashboard').rstrip('/')
        async def reply(response):
            response.headers.update(SAFE_HEADERS)
            await response(scope,receive,send)
        if scope['method']=='GET' and (path in {'','/'} or path in {'/app.js','/style.css'}):
            name='index.html' if path in {'','/'} else path[1:]
            return await reply(Response((ASSETS/name).read_bytes(),media_type=ASSET_NAMES[name]))
        if not path.startswith('/api/'):
            return await reply(JSONResponse({'error':'not_found'},404))
        if self.slots.locked():return await reply(JSONResponse({'error':'dashboard_capacity'},429,headers={'Retry-After':'1'}))
        await self.slots.acquire()
        try:
            if scope['method'] not in {'GET','POST'}:raise ServiceError('method_not_allowed',405)
            if scope['method']=='POST':
                expected=str(request.url.replace(path='/',query='',fragment='')).rstrip('/')
                if request.headers.get('origin')!=expected or request.headers.get('x-rag-browser')!='1':raise ServiceError('origin_denied',403)
                if request.headers.get('content-type','').partition(';')[0]!='application/json':raise ServiceError('json_required',415)
            body=bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body)+len(chunk)>65536:raise ServiceError('request_too_large',413)
                    body.extend(chunk)
            data=json.loads(body) if body else {}
            if not isinstance(data,dict):raise ServiceError('invalid_request')
            policy=await asyncio.to_thread(Policy.load,self.path)
            if path=='/api/bootstrap' and scope['method']=='GET':
                return await reply(JSONResponse({'available':await asyncio.to_thread(policies.available,self.path)}))
            if path in {'/api/login','/api/bootstrap'} and scope['method']=='POST':
                peer=(scope.get('client') or ('',0))[0];now=time.monotonic()
                start,count=self.attempts.pop(peer,(now,0))
                if now-start>=60:start,count=now,0
                self.attempts[peer]=(start,count+1)
                while len(self.attempts)>1024:self.attempts.popitem(last=False)
                if count>=5:raise ServiceError('login_rate_limited',429)
                if path=='/api/bootstrap':return await reply(JSONResponse(await asyncio.to_thread(policies.bootstrap,self.cfg,self.path,data)))
                if set(data)!={'username','password'} or not all(isinstance(v,str) for v in data.values()) or len(data['username'])>80:raise ServiceError('invalid_request')
                principal=await asyncio.to_thread(policy.authenticate_password,data['username'],data['password'])
                token,expiry=await asyncio.to_thread(persist_session,self.cfg,policy,principal)
                response=JSONResponse({'authenticated':True,'expires_at':expiry.isoformat()})
                response.set_cookie(cookie_name(request),token,max_age=8*3600,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
                return await reply(response)
            from .api import authenticate
            token=request.cookies.get(cookie_name(request),'')
            if not token.startswith('session.') or len(token)>2048:raise AuthenticationError()
            principal=await asyncio.to_thread(authenticate,policy,self.cfg,token)
            if principal.machine_id is not None:raise AuthenticationError()
            from .dashboard_presence import observe
            await asyncio.to_thread(observe,self.cfg,self.path,principal)
            csrf=hash_key('dashboard-csrf:'+token)
            if scope['method']=='POST' and not hmac.compare_digest(request.headers.get('x-rag-csrf',''),csrf):raise ServiceError('csrf_denied',403)
            if path=='/api/me' and scope['method']=='GET':
                result={'user':principal.user_id,'admin':principal.admin,'readonly':principal.readonly,'csrf':csrf,
                        'permissions':{name:sorted(getattr(principal,name)) for name in ('read_domains','write_domains','read_projects','write_projects','session_teams')}}
            elif path=='/api/logout' and scope['method']=='POST':
                def remove():
                    with db.connect(self.cfg) as conn:conn.execute('DELETE FROM service_sessions WHERE token_hash=%s',(hash_key(token),))
                await asyncio.to_thread(remove)
                response=JSONResponse({'logged_out':True});response.delete_cookie(cookie_name(request),path='/',secure=request.url.scheme=='https',httponly=True,samesite='strict')
                return await reply(response)
            elif path=='/api/policy' and scope['method']=='GET':
                if not principal.admin:raise ServiceError('administrator_required',403)
                result=await asyncio.to_thread(policies.policy_view,self.path)
            elif path in {'/api/policy/preview','/api/policy/apply'} and scope['method']=='POST':
                result=await asyncio.to_thread(policies.change_policy,self.cfg,self.path,principal,data,apply=path.endswith('/apply'))
            else:
                from .dashboard_views import dispatch
                result=await dispatch(self.cfg,self.path,principal,path,scope['method'],data,request.query_params)
            from ..mcp_server import _plain
            response=JSONResponse(_plain(result))
            if len(response.body)>512*1024:raise ServiceError('result_too_large',413)
            return await reply(response)
        except AuthenticationError:return await reply(JSONResponse({'error':'invalid_credentials'},401))
        except ServiceError as exc:return await reply(JSONResponse({'error':exc.code},exc.status))
        except TimeoutError:return await reply(JSONResponse({'error':'request_timeout'},408))
        except (ValueError,KeyError,TypeError,RecursionError):return await reply(JSONResponse({'error':'invalid_request'},400))
        except Exception:return await reply(JSONResponse({'error':'dashboard_unavailable'},503))
        finally:self.slots.release()
