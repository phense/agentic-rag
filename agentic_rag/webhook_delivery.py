"""Explicit bounded sender and pinned HTTP transport. No implicit background task."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit,urlunsplit
import uuid

from . import db
from .service.auth import protected_file
from .webhooks import WebhookError,schema_valid

ATTEMPT_SECONDS=10
LEASE_SECONDS=30
MAX_ATTEMPTS=6
BACKOFF=(5,30,120,600,1800,3600)


def normalize_endpoint(endpoint,*,allow_http=False):
    if not isinstance(endpoint,str) or not 8<=len(endpoint)<=2048 or any(ord(c)<33 or ord(c)>126 for c in endpoint):raise ValueError('webhook_destination')
    try:
        parsed=urlsplit(endpoint)
        port=parsed.port
        host=(parsed.hostname or '').encode('idna').decode().lower()
    except (ValueError,UnicodeError):raise ValueError('webhook_destination') from None
    if parsed.scheme not in (('https','http') if allow_http else ('https',)) or not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or '?' in endpoint or '#' in endpoint or '\\' in endpoint:
        raise ValueError('webhook_destination')
    if len(host)>253 or '%' in host or (port is not None and not 1<=port<=65535):raise ValueError('webhook_destination')
    if not re.fullmatch(r'[a-z0-9.:-]+',host):raise ValueError('webhook_destination')
    authority=('['+host+']') if ':' in host else host
    if port is not None and port!=(443 if parsed.scheme=='https' else 80):authority+=':'+str(port)
    return urlunsplit((parsed.scheme,authority,parsed.path or '/', '', ''))


def origin(endpoint):
    p=urlsplit(endpoint)
    return p.scheme+'://'+p.netloc


def validate_addresses(endpoint,addresses,policy,*,test_http=False):
    normalized=normalize_endpoint(endpoint,allow_http=test_http)
    allowed=policy.get(origin(normalized),[])
    if not isinstance(allowed,list) or len(allowed)>16:raise ValueError('webhook_destination')
    networks=[ipaddress.ip_network(value,strict=True) for value in allowed]
    if not addresses or len(addresses)>16:raise ValueError('webhook_destination')
    valid=[]
    for value in addresses:
        address=ipaddress.ip_address(value)
        address=address.ipv4_mapped if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped else address
        # Metadata and special-use addresses are never authorized by a CIDR.
        if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved or (isinstance(address,ipaddress.IPv6Address) and address.is_site_local) or str(address) in {'100.100.100.200','168.63.129.16'}:
            raise ValueError('webhook_destination')
        exact=any(address.version==network.version and address in network for network in networks)
        if not address.is_global and not exact:raise ValueError('webhook_destination')
        if urlsplit(normalized).scheme=='http' and not (test_http and address.is_loopback and exact):raise ValueError('webhook_destination')
        valid.append(str(address))
    return list(dict.fromkeys(valid))


def resolve(host,port,deadline):
    """Resolver dies with its subprocess; no abandoned unbounded resolver thread."""
    remaining=min(2.0,deadline-time.monotonic())
    if remaining<=0:raise TimeoutError()
    code="import socket,json,sys; a=socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM); print(json.dumps(list(dict.fromkeys(x[4][0] for x in a))[:17]))"
    try:
        result=subprocess.run([sys.executable,'-I','-c',code,host,str(port)],capture_output=True,timeout=remaining,check=True)
        if len(result.stdout)>4096:raise ValueError('webhook_destination')
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:raise TimeoutError() from None
    except (subprocess.SubprocessError,ValueError):raise ValueError('webhook_destination') from None


def _remaining(deadline):
    value=deadline-time.monotonic()
    if value<=0:raise TimeoutError()
    return value


def transmit(endpoint,body,headers,*,policy=None,test_http=False,before_socket=None):
    """No proxy/redirect client; socket uses only the validated numeric address."""
    deadline=time.monotonic()+ATTEMPT_SECONDS
    endpoint=normalize_endpoint(endpoint,allow_http=test_http)
    parsed=urlsplit(endpoint); port=parsed.port or (443 if parsed.scheme=='https' else 80)
    addresses=validate_addresses(endpoint,resolve(parsed.hostname,port,deadline),policy or {},test_http=test_http)
    if before_socket is not None:before_socket()
    address=addresses[0]
    family=socket.AF_INET6 if ':' in address else socket.AF_INET
    with socket.socket(family,socket.SOCK_STREAM) as raw:
        raw.settimeout(min(3,_remaining(deadline)))
        raw.connect((address,port))
        stream=raw
        if parsed.scheme=='https':
            raw.settimeout(_remaining(deadline))
            stream=ssl.create_default_context().wrap_socket(raw,server_hostname=parsed.hostname)
        try:
            path=parsed.path or '/'
            request=(f'POST {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n'+
                     ''.join(f'{key}: {value}\r\n' for key,value in headers.items())+'\r\n').encode('ascii')+body
            stream.settimeout(_remaining(deadline));stream.sendall(request)
            # Bound all response bytes, header count and wall time; never expose body.
            response=bytearray()
            while b'\r\n\r\n' not in response:
                stream.settimeout(_remaining(deadline))
                part=stream.recv(min(1024,8193-len(response)))
                if not part:break
                response.extend(part)
                if len(response)>8192:raise ValueError('webhook_response')
            if b'\r\n\r\n' not in response:raise ValueError('webhook_response')
            head=bytes(response).split(b'\r\n\r\n',1)[0].split(b'\r\n')
            if len(head)>100 or any(b':' not in line or line[:1] in (b' ',b'\t') for line in head[1:]):raise ValueError('webhook_response')
            line=head[0]
            if not re.fullmatch(rb'HTTP/1\.[01] [0-9]{3} [^\r\n]*',line):raise ValueError('webhook_response')
            return int(line.split()[1])
        finally:
            if stream is not raw:stream.close()


def _operator(cfg):
    from .service.context import CURRENT
    from .service.queued_transaction import GROUP,EXECUTION
    from .service.fence import LEASE
    if CURRENT.get() is not None or GROUP.get() is not None or EXECUTION.get() is not None or LEASE.get() is not None or cfg.service_mode=='client':
        raise WebhookError('operator_local_configuration_required')


def _outside_git(path):
    path=Path(path).expanduser().absolute()
    parent=path.parent.resolve(strict=True)
    if any((candidate/'.git').exists() for candidate in (parent,*parent.parents)):
        raise WebhookError('webhook_private_file_outside_git_required')
    return parent/path.name


def _exclusive(path,data):
    path=_outside_git(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    return {'created':True}


def key_init(cfg,path):
    _operator(cfg)
    return _exclusive(path,secrets.token_bytes(32))


def signing_key(path,subscription_id,generation):
    root=protected_file(_outside_git(path),max_bytes=32)
    if len(root)!=32:raise ValueError('webhook_key')
    root_id=hashlib.sha256(b'RAG-WEBHOOK-ROOT-v1\0'+root).hexdigest()[:24]
    identity='wh1:'+root_id+':'+str(subscription_id)+':'+str(generation)
    key=hmac.digest(root,identity.encode(),'sha256')
    return identity,key


def key_export(cfg,*,subscription_id,output):
    _operator(cfg)
    with db.connect(cfg) as conn:
        _valid(conn)
        row=conn.execute('SELECT id,generation FROM public.webhook_subscriptions WHERE id=%s',(uuid.UUID(subscription_id),)).fetchone()
        if row is None:raise WebhookError('webhook_unavailable',404)
    identity,key=signing_key(cfg.webhook_key_file,row['id'],row['generation'])
    return {**_exclusive(output,json.dumps({'key_id':identity,'key_hex':key.hex()},sort_keys=True).encode()+b'\n'),'key_id':identity}


def signature_headers(path,subscription_id,generation,body,*,timestamp=None):
    identity,key=signing_key(path,subscription_id,generation)
    timestamp=int(time.time()) if timestamp is None else timestamp
    signature=hmac.digest(key,str(timestamp).encode()+b'.'+body,'sha256').hex()
    return {'X-RAG-Timestamp':str(timestamp),'X-RAG-Key-Id':identity,'X-RAG-Signature':'v1='+signature}


def verify_signature(key,body,headers,*,now=None,window=300):
    try:
        timestamp=int(headers['X-RAG-Timestamp'])
        if abs((time.time() if now is None else now)-timestamp)>window:return False
        expected='v1='+hmac.digest(key,str(timestamp).encode()+b'.'+body,'sha256').hex()
        return hmac.compare_digest(expected,headers['X-RAG-Signature'])
    except (KeyError,ValueError,TypeError):return False


def _valid(conn):
    if not schema_valid(conn):raise WebhookError('incompatible_service_schema',503)


def capture(cfg,enabled):
    _operator(cfg)
    if type(enabled) is not bool:raise WebhookError('webhook_invalid')
    with db.connect(cfg) as conn:
        _valid(conn)
        conn.execute('UPDATE public.webhook_control SET enabled=%s',(enabled,))
        conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES('webhook:operator','webhook.capture',%s)",('enabled' if enabled else 'disabled',))
    return {'capture_enabled':enabled}


def _authority(cfg,row):
    reference=row['credential_reference']
    if 'local_uid' in reference:
        if reference!={'local_uid':os.getuid()} or row['namespace']!='local' or row['actor']!='webhook:local':raise WebhookError('webhook_revoked')
        principal=None
    else:
        from .service.auth import resolve_reference
        try:principal=resolve_reference(cfg,reference)
        except Exception:raise WebhookError('webhook_revoked') from None
        if principal.namespace!=row['namespace'] or principal.actor!=row['actor'] or principal.readonly:raise WebhookError('webhook_revoked')
        if row['domain'] is None:
            if not principal.write_domains or ('*' not in principal.write_projects and row['project'] not in principal.write_projects):raise WebhookError('webhook_revoked')
        elif not principal.can_write(row['domain'],row['project']):raise WebhookError('webhook_revoked')
    # Read current anchor visibility with normal scoped RLS. Source notices
    # require a still-visible dependent in the exact captured scope.
    from .service.context import request_scope
    from contextlib import nullcontext
    with request_scope(principal,cfg,read_only=True) if principal else nullcontext():
        with db.connect(cfg,role='reader') as conn:
            if row['anchors']:
                count=conn.execute('SELECT count(*) n FROM documents WHERE id=ANY(%s) AND domain=%s AND project_scope=%s',
                    (row['anchors'],row['domain'],row['project'])).fetchone()['n']
                if count!=len(set(row['anchors'])):raise WebhookError('webhook_revoked')
            elif row['kind']=='source.changed':
                found=conn.execute("""SELECT EXISTS(SELECT 1 FROM claim_evidence e JOIN documents d ON d.id=e.document_id
                    WHERE encode(sha256(convert_to(e.source_key,'UTF8')),'hex')=%s AND d.domain=%s AND d.project_scope=%s) ok""",
                    (row['resource'],row['domain'],row['project'])).fetchone()['ok']
                if not found:raise WebhookError('webhook_revoked')
            elif row['kind'].startswith('job.'):
                found=conn.execute('SELECT EXISTS(SELECT 1 FROM service_windows WHERE id=%s AND owner_namespace=%s AND project=%s) ok',
                    (uuid.UUID(row['resource']),row['namespace'],row['project'])).fetchone()['ok']
                if not found:raise WebhookError('webhook_revoked')


def claim(cfg):
    _operator(cfg)
    with db.connect(cfg) as conn:
        _valid(conn)
        if not conn.execute('SELECT enabled FROM webhook_control').fetchone()['enabled']:return None
        conn.execute("""UPDATE webhook_deliveries SET state='dead',outcome='exhausted',lease=NULL,lease_until=NULL,updated_at=now()
            WHERE state='leased' AND lease_until<=now() AND attempts>=6""")
        row=conn.execute("""SELECT id FROM webhook_deliveries WHERE attempts<6 AND
            ((state IN ('pending','retry') AND due_at<=now()) OR (state='leased' AND lease_until<=now()))
            ORDER BY due_at,id FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if row is None:return None
        lease=uuid.uuid4()
        conn.execute("""UPDATE webhook_deliveries SET state='leased',attempts=attempts+1,lease=%s,
            lease_until=now()+interval '30 seconds',updated_at=now() WHERE id=%s""",(lease,row['id']))
        result=conn.execute("""SELECT d.id delivery_id,d.lease,d.attempts,d.lease_until,s.*,e.kind,e.resource,e.anchors,e.wire,
             e.id event_id,e.owner_namespace FROM webhook_deliveries d JOIN webhook_subscriptions s ON s.id=d.subscription_id
             JOIN webhook_events e ON e.id=d.event_id WHERE d.id=%s""",(row['id'],)).fetchone()
        return result


def _before_socket(cfg,row):
    _authority(cfg,row)
    with db.connect(cfg) as conn:
        _valid(conn)
        state=conn.execute("""SELECT c.enabled capture_enabled,s.enabled,s.revision,d.state,d.lease,
             d.lease_until>clock_timestamp()+interval '11 seconds' time_ok FROM webhook_control c
             CROSS JOIN webhook_subscriptions s JOIN webhook_deliveries d ON d.subscription_id=s.id
             WHERE s.id=%s AND d.id=%s""",(row['id'],row['delivery_id'])).fetchone()
        if not state or not state['capture_enabled']:raise WebhookError('webhook_off')
        if not state['enabled']:raise WebhookError('webhook_disabled')
        if state['revision']!=row['revision'] or state['lease']!=row['lease'] or state['state']!='leased' or not state['time_ok']:raise WebhookError('webhook_revoked')


def complete(cfg,row,outcome):
    _operator(cfg)
    if outcome=='acknowledged':state='acknowledged'
    elif outcome in ('revoked','disabled'):state=outcome
    elif outcome=='off':state='retry'
    else:state='dead' if row['attempts']>=MAX_ATTEMPTS else 'retry'
    with db.connect(cfg) as conn:
        _valid(conn)
        updated=conn.execute("""UPDATE webhook_deliveries SET state=%s,outcome=%s,lease=NULL,lease_until=NULL,
            due_at=now()+make_interval(secs=>%s),updated_at=now() WHERE id=%s AND lease=%s AND state='leased'
            AND lease_until>clock_timestamp() RETURNING id""",(state,outcome,BACKOFF[row['attempts']-1],row['delivery_id'],row['lease'])).fetchone()
        return updated is not None


def send_one(cfg):
    row=claim(cfg)
    if row is None:return {'state':'idle'}
    try:
        _before_socket(cfg,row)
        body=row['wire'].encode('utf-8')
        try:headers=signature_headers(cfg.webhook_key_file,row['id'],row['generation'],body)
        except (OSError,ValueError,TypeError):raise WebhookError('webhook_key') from None
        code=transmit(row['endpoint'],body,headers,policy=cfg.webhook_private_origins,
                      test_http=cfg.webhook_test_http,before_socket=lambda:_before_socket(cfg,row))
        outcome='acknowledged' if 200<=code<300 else 'response'
    except WebhookError as error:
        outcome=error.code.removeprefix('webhook_')
        if outcome not in ('off','disabled','revoked','key'):outcome='revoked'
    except (TimeoutError,socket.timeout):outcome='timeout'
    except ValueError:outcome='destination'
    except Exception:outcome='network'
    fenced=complete(cfg,row,outcome)
    return {'delivery_id':str(row['delivery_id']),'event_id':str(row['event_id']),'outcome':outcome,'completed':fenced}


def prune(cfg):
    _operator(cfg)
    with db.connect(cfg) as conn:
        _valid(conn);conn.execute('SELECT pg_advisory_xact_lock(72038,1)')
        count=conn.execute("""DELETE FROM webhook_deliveries WHERE state IN ('acknowledged','cancelled')
            AND updated_at<now()-interval '7 days' RETURNING id""").fetchall()
        events=conn.execute("""DELETE FROM webhook_events e WHERE created_at<now()-interval '7 days'
            AND NOT EXISTS(SELECT 1 FROM webhook_deliveries d WHERE d.event_id=e.id) RETURNING id""").fetchall()
        conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES('webhook:operator','webhook.prune',%s)",(str(len(count))+':'+str(len(events)),))
    return {'deliveries':len(count),'events':len(events)}
