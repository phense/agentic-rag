"""Explicit operator commands; no production mutation merely by inspecting a plan."""
from dataclasses import replace
import getpass
import ipaddress
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import tomlkit

from .. import db
from .auth import Policy,hash_key,hash_password,new_key,protected_file
from . import upgrade


def add_parser(sub):
    parser=sub.add_parser('service',help='operate a standalone or central deployment')
    parser.add_argument('--config',type=Path)
    commands=parser.add_subparsers(dest='service_command',required=True)
    key=commands.add_parser('key');key.add_argument('--id',required=True);key.add_argument('--output',type=Path,required=True)
    password=commands.add_parser('password');password.add_argument('--password-file',type=Path)
    policy=commands.add_parser('check-policy');policy.add_argument('--file',type=Path,required=True)
    client=commands.add_parser('client-config');client.add_argument('--url',required=True);client.add_argument('--token-file',type=Path,required=True);client.add_argument('--output',type=Path,required=True);client.add_argument('--spool-dir',type=Path,required=True)
    login=commands.add_parser('login');login.add_argument('--url',required=True);login.add_argument('--username',required=True);login.add_argument('--password-file',type=Path);login.add_argument('--output',type=Path,required=True)
    login.add_argument('--uploader-file',type=Path,help='stable private uploader identity; reuse on this VM when renewing login')
    commands.add_parser('logout')
    retry=commands.add_parser('job-retry');retry.add_argument('receipt')
    serve=commands.add_parser('serve');serve.add_argument('--auth-file',type=Path,required=True);serve.add_argument('--host',default='127.0.0.1');serve.add_argument('--port',type=int,default=8765);serve.add_argument('--allowed-host',action='append',default=[])
    commands.add_parser('worker');commands.add_parser('status')
    spool=commands.add_parser('spool');spool.add_argument('--retry-blocked',action='store_true');spool.add_argument('--flush',action='store_true')
    inventory=commands.add_parser('inventory');inventory.add_argument('--source-version',required=True);inventory.add_argument('--identities',action='store_true');inventory.add_argument('--output',type=Path,required=True)
    preflight=commands.add_parser('preflight');preflight.add_argument('--source-version',required=True);preflight.add_argument('--mode',choices=['local','remote'],default='local')
    collision=commands.add_parser('collisions');collision.add_argument('inventories',nargs='+',type=Path);collision.add_argument('--output',type=Path,required=True)
    backup=commands.add_parser('verified-backup');backup.add_argument('--source-version',required=True);backup.add_argument('--output',type=Path,required=True)
    for name in ('upgrade','prepare-cutover'):
        command=commands.add_parser(name);command.add_argument('--source-version',required=True);command.add_argument('--dump',type=Path,required=True);command.add_argument('--apply',action='store_true');command.add_argument('--writers-stopped',action='store_true')
    restore=commands.add_parser('restore-target');restore.add_argument('--dump',type=Path,required=True);restore.add_argument('--manifest',type=Path,required=True);restore.add_argument('--apply',action='store_true');restore.add_argument('--resume',action='store_true')
    return parser


def _write(path,data):
    path=Path(path).expanduser().absolute();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return path


def _url(value):
    parsed=urlsplit(value)
    try:local=ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:local=parsed.hostname=='localhost'
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in {'https','http'} or (parsed.scheme=='http' and not local):raise ValueError('service_url_requires_https_or_loopback')
    return value.rstrip('/')


def _json(path):
    return json.loads(protected_file(path,max_bytes=64*1024*1024))


def _password(args):
    return protected_file(args.password_file).decode().rstrip('\r\n') if args.password_file else getpass.getpass('Password: ')


def _login(args):
    # No token exists before login. Send only to a verified TLS/loopback origin;
    # refuse redirects/proxy environment, bound the response and persist privately.
    if args.output.exists():raise FileExistsError(str(args.output))
    url=_url(args.url)
    uploader_file=(getattr(args,'uploader_file',None) or args.output.with_name(args.output.name+'.uploader')).expanduser().absolute()
    if not uploader_file.exists():
        try:
            _write(uploader_file,(str(uuid.uuid4())+'\n').encode())
            directory=os.open(uploader_file.expanduser().absolute().parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        except FileExistsError:pass
    uploader=str(uuid.UUID(protected_file(uploader_file,max_bytes=128).decode().strip()))
    payload={'username':args.username,'password':_password(args),'uploader_id':uploader}
    with httpx.stream('POST',url+'/v1/login',headers={'x-rag-protocol':'1'},json=payload,timeout=5,follow_redirects=False,trust_env=False) as response:
        content=bytearray()
        for chunk in response.iter_bytes():
            if len(content)+len(chunk)>1048576:raise ValueError('login_response_too_large')
            content.extend(chunk)
        if response.status_code!=200:raise ValueError('login_failed')
        data=json.loads(content)
    token=data.get('access_token')
    if not isinstance(token,str) or not token.startswith('session.') or len(token)>2048 or any(c.isspace() for c in token):raise ValueError('invalid_login_response')
    if data.get('uploader_id')!=uploader:raise ValueError('invalid_login_uploader')
    path=_write(args.output,(token+'\n').encode())
    return {'token_file':str(path),'expires_at':data.get('expires_at'),'uploader_file':str(uploader_file)}


def status(cfg):
    if cfg.service_mode=='client':
        from .client import RemoteClient
        with RemoteClient(cfg) as client:return {'mode':'client','spool':client.spool.status()}
    from .schema import validate_schema,ServiceSchemaError
    with db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        values=dict(conn.execute("SELECT pg_database_size(current_database()) bytes,(SELECT count(*) FROM mining_queue WHERE status IN ('pending','processing','error')) pending").fetchone())
        try:validate_schema(conn);values['service_ready']=True
        except ServiceSchemaError:conn.rollback();values['service_ready']=False
    return {'mode':cfg.service_mode,'database':values,'limits':{'database_bytes':cfg.service_max_database_bytes,'minimum_free_bytes':cfg.service_min_free_bytes,'pending':cfg.service_max_pending,'pending_per_owner':cfg.service_max_pending_per_owner,'pending_window_bytes':cfg.service_max_pending_bytes}}


def run(args,cfg):
    command=args.service_command
    if command=='key':
        token=new_key(args.id);path=_write(args.output,(token+'\n').encode());result={'id':args.id,'verifier':hash_key(token),'token_file':str(path)}
    elif command=='password':result={'verifier':hash_password(_password(args))}
    elif command=='check-policy':
        policy=Policy.load(args.file);result={'valid':True,'users':len(policy.users),'machines':len(policy.machines),'credential_ids':sorted(policy.keys)}
    elif command=='client-config':
        url=_url(args.url);token_file=args.token_file.expanduser().absolute();protected_file(token_file)
        document=tomlkit.document();document['service']={'mode':'client','url':url,'token_file':str(token_file),'spool_dir':str(args.spool_dir.expanduser().absolute())}
        result={'configuration':str(_write(args.output,tomlkit.dumps(document).encode()))}
    elif command=='login':result=_login(args)
    elif command in {'serve','worker'}:
        if cfg.service_mode!='server':raise ValueError('explicit_server_mode_required')
        if command=='worker':
            from .runner import run_with_signals as worker_run
            return worker_run(cfg)
        if not 1<=args.port<=65535:raise ValueError('invalid_service_port')
        import uvicorn
        from .api import create_app
        app=create_app(cfg,args.auth_file,allowed_hosts=tuple(args.allowed_host or ['localhost','127.0.0.1','[::1]']))
        uvicorn.run(app,host=args.host,port=args.port,workers=1,limit_concurrency=64,backlog=64,timeout_keep_alive=30,
                    h11_max_incomplete_event_size=16384,proxy_headers=False,access_log=False)
        return 0
    elif command=='status':result=status(cfg)
    elif command in {'spool','logout','job-retry'}:
        if cfg.service_mode!='client':raise ValueError('client_mode_required')
        from .client import RemoteClient
        with RemoteClient(cfg) as client:
            if command=='logout':result=client.request('POST','/v1/logout',{})
            elif command=='job-retry':
                import uuid
                result=client.request('POST','/v1/jobs/'+str(uuid.UUID(args.receipt))+'/retry',{})
            else:
                if args.retry_blocked:client.spool.retry_blocked()
                if args.flush:
                    from .local import stage_sources
                    try:stage_sources(client)
                    except Exception:
                        client.spool.note('source_staging_failed')
                    # Capacity/malformed fresh source must not prevent an ACK
                    # from retiring previously staged durable input.
                    client.flush()
                result=client.spool.status()
    elif command=='inventory':
        result=upgrade.inventory(cfg,args.source_version,identities=args.identities);upgrade.private_json(args.output,result);result={'inventory':str(args.output),'supported':True}
    elif command=='preflight':result=upgrade.preflight(cfg,args.source_version,mode=args.mode)
    elif command=='collisions':
        result=upgrade.collision_report([_json(path) for path in args.inventories]);upgrade.private_json(args.output,result);result={'report':str(args.output),'ready':result['ready'],'requires_explicit_mapping':result['requires_explicit_mapping']}
    elif command=='verified-backup':result=upgrade.verified_backup(cfg,args.source_version,args.output)
    elif command in {'upgrade','prepare-cutover'}:
        fn=upgrade.local_upgrade if command=='upgrade' else upgrade.prepare_cutover
        result=fn(cfg,args.source_version,args.dump,apply=args.apply,writers_stopped=args.writers_stopped)
    elif command=='restore-target':result=upgrade.restore_target(cfg,args.dump,_json(args.manifest),apply=args.apply,resume=args.resume)
    else:raise ValueError('unknown_service_command')
    print(json.dumps(result,sort_keys=True,default=str))
    return 0
