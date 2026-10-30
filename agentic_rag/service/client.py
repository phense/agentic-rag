"""One bounded HTTP connector shared by hooks, stdio and operator commands."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import random
import time
import uuid
from urllib.parse import urlsplit

import httpx

from .auth import protected_file
from .ingest import normalize
from .spool import Spool


class RemoteError(Exception):
    def __init__(self,code,status=0):
        self.code,self.status=code,status
        super().__init__(code)


class RemoteClient:
    def __init__(self,cfg,*,sender=None):
        self.cfg=cfg
        url=urlsplit(cfg.service_url)
        try: loopback=ipaddress.ip_address(url.hostname or '').is_loopback
        except ValueError: loopback=url.hostname=='localhost'
        if url.scheme not in {'http','https'} or (url.scheme!='https' and not loopback) or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('service URL requires HTTPS or loopback HTTP and no credentials/query')
        if cfg.service_token_file is None: raise ValueError('service token file required')
        self.token=protected_file(cfg.service_token_file).decode().strip()
        if not 1<=len(self.token)<=2048 or any(c.isspace() for c in self.token): raise ValueError('invalid service token file')
        self.url=cfg.service_url.rstrip('/')
        self.partition=hashlib.sha256((self.url+'\0'+hashlib.sha256(self.token.encode()).hexdigest()).encode()).hexdigest()
        self.spool=Spool(cfg.service_spool_dir/'spool.sqlite',self.partition)
        self.owns_sender=sender is None
        self.sender=sender or httpx.Client(timeout=httpx.Timeout(1.0,connect=.3),follow_redirects=False,trust_env=False)
        self.negotiated=False
        self.queued_tools=False

    def __enter__(self): return self
    def __exit__(self,*args):
        self.spool.conn.close()
        if self.owns_sender:self.sender.close()

    def request(self,method,path,payload=None,*,seconds=1,headers=None):
        deadline=time.monotonic()+seconds
        try:
            with self.sender.stream(method,self.url+path,headers={'authorization':'Bearer '+self.token,'x-rag-protocol':'1',**(headers or {})},
                                    timeout=httpx.Timeout(seconds,connect=min(.3,seconds)),
                                    **({'json':payload} if payload is not None else {})) as response:
                content=bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic()>deadline:raise RemoteError('response_timeout')
                    if len(content)+len(chunk)>1048576: raise RemoteError('response_too_large',response.status_code)
                    content.extend(chunk)
                try:data=json.loads(content)
                except (ValueError,UnicodeDecodeError):raise RemoteError('invalid_response',response.status_code) from None
                if not isinstance(data,dict):raise RemoteError('invalid_response',response.status_code)
                if not 200<=response.status_code<300:
                    code=data.get('error','request_failed')
                    if not isinstance(code,str) or not code.replace('_','').isalnum() or len(code)>80:code='request_failed'
                    raise RemoteError(code,response.status_code)
                return data
        except httpx.HTTPError:
            raise RemoteError('network_unavailable') from None

    def negotiate(self,*,seconds=1):
        if not self.negotiated:
            capabilities=self.request('GET','/v1/capabilities',seconds=seconds)
            if capabilities.get('protocol')!=1:raise RemoteError('unsupported_protocol',426)
            self.queued_tools=capabilities.get('extensions',{}).get('queued_tools')==1
            self.negotiated=True

    def invoke(self,name,arguments,*,seconds=None):
        seconds=self.cfg.service_tool_wait_seconds if seconds is None else seconds
        deadline=time.monotonic()+seconds
        handle=self.spool.stage_request(name,arguments)  # durable before discovery
        try:self.negotiate(seconds=max(.01,min(1,seconds)))
        except RemoteError as exc:
            self.spool.request_error(handle,exc.code)
            return {'request_id':handle,'local_request_id':handle,'state':'pending','waiting':True,'durable':False,'code':exc.code}
        if not self.queued_tools:
            # Legacy writes have no idempotency protocol: an ambiguous failure
            # must never be auto-replayed as a queued operation.
            self.spool.request_error(handle,'legacy_outcome_unknown')
            result=self.request('POST','/v1/tools/'+name,arguments,seconds=max(.01,deadline-time.monotonic()))
            self.spool.request_finish(handle)
            return result
        poll_delay=self.cfg.service_poll_seconds
        while True:
            result=self.request_status(handle,seconds=max(.01,min(1,deadline-time.monotonic())))
            if result.get('code')=='result_expired':
                self.spool.request_finish(handle)
                raise RemoteError('result_expired')
            if result.get('state')=='completed':
                self.spool.request_finish(handle)
                return result['result']
            if result.get('state') in {'failed','cancelled','expired'}:
                self.spool.request_finish(handle)
                raise RemoteError(result.get('code','request_'+result['state']))
            remaining=deadline-time.monotonic()
            if remaining<=.2 or not result.get('durable'):
                return {**result,'waiting':True,'local_request_id':handle}
            time.sleep(min(poll_delay*(1+random.random()*.25),max(0,remaining-.2)))
            poll_delay=min(8,max(self.cfg.service_poll_seconds,poll_delay*2))

    def request_status(self,handle,*,cancel=False,seconds=1,consume=True):
        deadline=time.monotonic()+seconds
        if not isinstance(handle,str) or len(handle)>80:raise ValueError('invalid request handle')
        if not handle.startswith('local.'):
            try:identity=str(uuid.UUID(handle))
            except ValueError:raise ValueError('invalid request handle') from None
            local=self.spool.request_by_server(identity)
            if local:return self.request_status(local,cancel=cancel,seconds=seconds,consume=consume)
            return self.request('POST' if cancel else 'GET','/v1/requests/'+identity+('/cancel' if cancel else ''),seconds=seconds)
        row=self.spool.request_record(handle)
        self.spool.request_touch(handle)
        if row['code']=='legacy_outcome_unknown':
            return {'request_id':handle,'state':'blocked','durable':False,'code':'legacy_outcome_unknown','waiting':True}
        if cancel and row['server_id'] is None:
            # Lost ACK may already have committed the request. Reconcile before
            # cancellation; never claim that deleting a local envelope stopped it.
            pass
        try:
            if row['server_id'] is None:
                result=self.request('POST','/v1/requests',json.loads(row['envelope']),seconds=seconds,headers={'Prefer':'wait=0.1'})
                if result.get('durable') is not True:raise RemoteError('invalid_receipt')
                self.spool.request_ack(handle,result['request_id'])
                row=self.spool.request_record(handle)
                if result.get('state') in {'completed','failed','cancelled','expired'}:
                    if consume:self.spool.request_finish(handle)
                    return result
            remaining=deadline-time.monotonic()
            if remaining<=0:return {'request_id':row['server_id'],'state':'pending','durable':True,'waiting':True}
            result=self.request('POST' if cancel else 'GET','/v1/requests/'+row['server_id']+('/cancel' if cancel else ''),seconds=remaining)
            if consume and result.get('state') in {'completed','failed','cancelled','expired'}:self.spool.request_finish(handle)
            return result
        except RemoteError as exc:
            self.spool.request_error(handle,exc.code)
            if exc.status==404 and row['server_id'] is not None:
                if consume:self.spool.request_finish(handle)
                return {'request_id':row['server_id'],'state':'expired','durable':True,'code':'result_expired'}
            terminal=400<=exc.status<500 and exc.status not in {408,429}
            return {'request_id':row['server_id'] or handle,'state':'blocked' if terminal else 'pending',
                    'durable':row['server_id'] is not None,'code':exc.code,'waiting':True}

    def flush_requests(self,*,max_items=8,seconds=2):
        started=time.monotonic();completed=0
        for row in self.spool.pending_requests()[:max_items]:
            if time.monotonic()-started>=seconds:break
            result=self.request_status(row['id'],consume=False,seconds=min(1,max(.01,seconds-(time.monotonic()-started))))
            if result.get('state') in {'completed','failed','cancelled','expired'}:
                # Results are not persisted in the source outbox. Keep the small
                # handle for explicit agent retrieval until TTL; do not discard
                # completed output just because the uploader observed it first.
                completed+=1
        return {'observed_terminal':completed,'pending':len(self.spool.pending_requests())}

    def stage_window(self,payload):
        validated=normalize(payload).model_dump()
        return self.spool.enqueue('window',validated['session_id'],validated)

    def stage_checkpoint(self,payload):
        from .checkpoints import Packet
        validated=Packet.model_validate(payload).model_dump()
        identity=self.spool.enqueue('checkpoint',validated['session_id'],validated)
        return identity

    def flush(self,*,max_items=8,seconds=3):
        accepted=0;started=time.monotonic()
        for _ in range(max_items):
            if time.monotonic()-started>=seconds:break
            due=self.spool.due()
            if not due:break
            row=due[0]
            try:
                self.negotiate()
                path='/v1/windows' if row['kind']=='window' else '/v1/checkpoints'
                result=self.request('POST',path,json.loads(row['payload']))
                if result.get('durable') is not True or (row['kind']=='window' and not isinstance(result.get('receipt'),str)) or (row['kind']!='window' and not isinstance(result.get('checkpoint',{}).get('id'),str)):
                    raise RemoteError('invalid_receipt',400)
                receipt=result.get('receipt') or result['checkpoint']['id']
                try:uuid.UUID(receipt)
                except (ValueError,TypeError):raise RemoteError('invalid_receipt',400) from None
                self.spool.ack(row['id'],{'receipt':receipt,'session':row['session'],'kind':row['kind'],
                    'state':result.get('state','accepted'),'observed_at':time.time()})
                accepted+=1
            except RemoteError as exc:
                self.spool.fail(row['id'],exc.code,blocked=400<=exc.status<500 and exc.status not in {408,429})
        return {'accepted':accepted,'pending':len(self.spool.pending())}

    def extraction_states(self,session,*,seconds=.3):
        deadline=time.monotonic()+seconds
        rows=self.spool.extraction_states(session)
        for row in rows[:3]:
            remaining=deadline-time.monotonic()
            if remaining<=0:break
            try:
                result=self.request('GET','/v1/jobs/'+row['receipt'],seconds=remaining)
                row.update({k:result[k] for k in ('state','code') if k in result})
                row['observed_at']=time.time();row.pop('status_error',None)
                self.spool.receipt_state(row)
            except RemoteError as exc:
                row['status_error']=exc.code
        return rows[:3]

    def context(self,session,project,*,prompt=None):
        try:
            result=self.invoke('memory_context',{'session_id':session,'project':project,**({'prompt':prompt} if prompt is not None else {})},seconds=self.cfg.service_hook_wait_seconds)
            if result.get('waiting'):
                cached=self.spool.cached(session,project) if prompt is None else None
                return '⚠️ agentic-rag context waiting: '+result['request_id']+'; extraction/context not yet completed.'+('\nSTALE retained context:\n'+cached if cached else '')
            text=result.get('text','')
            if not isinstance(text,str) or len(text)>10000:raise RemoteError('invalid_response')
            if prompt is None:self.spool.cache(session,project,text)
            return text
        except RemoteError as exc:
            cached=self.spool.cached(session,project) if prompt is None else None
            if cached:return '⚠️ STALE cached agentic-rag context; service unavailable ('+exc.code+').\n'+cached
            return '⚠️ agentic-rag unavailable: '+exc.code if prompt is None else ''
