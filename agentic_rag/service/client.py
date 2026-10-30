"""One bounded HTTP connector shared by hooks, stdio and operator commands."""
from __future__ import annotations

import hashlib
import ipaddress
import json
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

    def __enter__(self): return self
    def __exit__(self,*args):
        self.spool.conn.close()
        if self.owns_sender:self.sender.close()

    def request(self,method,path,payload=None,*,seconds=1):
        deadline=time.monotonic()+seconds
        try:
            with self.sender.stream(method,self.url+path,headers={'authorization':'Bearer '+self.token,'x-rag-protocol':'1'},
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

    def negotiate(self):
        if not self.negotiated:
            capabilities=self.request('GET','/v1/capabilities')
            if capabilities.get('protocol')!=1:raise RemoteError('unsupported_protocol',426)
            self.negotiated=True

    def invoke(self,name,arguments,*,seconds=30):
        self.negotiate()
        return self.request('POST','/v1/tools/'+name,arguments,seconds=seconds)

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
                self.spool.ack(row['id'],{'receipt':receipt})
                accepted+=1
            except RemoteError as exc:
                self.spool.fail(row['id'],exc.code,blocked=400<=exc.status<500 and exc.status not in {408,429})
        return {'accepted':accepted,'pending':len(self.spool.pending())}

    def context(self,session,project,*,prompt=None):
        try:
            result=self.invoke('memory_context',{'session_id':session,'project':project,**({'prompt':prompt} if prompt is not None else {})},seconds=1)
            text=result.get('text','')
            if not isinstance(text,str) or len(text)>10000:raise RemoteError('invalid_response')
            if prompt is None:self.spool.cache(session,project,text)
            return text
        except RemoteError as exc:
            cached=self.spool.cached(session,project) if prompt is None else None
            if cached:return '⚠️ STALE cached agentic-rag context; service unavailable ('+exc.code+').\n'+cached
            return '⚠️ agentic-rag unavailable: '+exc.code if prompt is None else ''
