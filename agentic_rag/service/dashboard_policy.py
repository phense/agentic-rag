"""Explicit revision-checked file policy administration with durable nonsecret audit."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import uuid

import tomlkit

from .. import db
from .auth import Policy, AuthenticationError, _ID, hash_key, hash_password, new_key, protected_file
from .engine import ServiceError

FIELDS={'label','enabled','read_domains','write_domains','read_projects','write_projects','session_teams'}


def identity(path):
    return hashlib.sha256(str(Path(path).absolute()).encode()).hexdigest()


def revision(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def policy_lock(path):
    path=Path(path)
    fd=os.open(path.with_name(path.name+'.dashboard.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise ServiceError('unsafe_policy_lock',503)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ServiceError('policy_busy',409) from None
        yield
    finally:os.close(fd)


def _exclusive(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())


def _replace(path,data):
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    _exclusive(temporary,data)
    try:
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()


def arm_bootstrap(path,output):
    """Operator-only: create an empty policy only if absent; emit token privately."""
    path=Path(path).expanduser().absolute();output=Path(output).expanduser().absolute()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with policy_lock(path):
        if not path.exists():_exclusive(path,b'version = 1\n')
        policy=Policy.load(path)
        if policy.users or policy.machines:raise ServiceError('already_initialized',409)
        token=secrets.token_urlsafe(32)
        marker=path.with_name(path.name+'.bootstrap')
        # A failed/interrupted arming is explicit operator recovery, never overwrite.
        _exclusive(output,(token+'\n').encode())
        _exclusive(marker,json.dumps({'verifier':hash_key(token)}).encode())
    return {'armed':True,'token_file':str(output),'auth_file':str(path)}


def available(path):
    policy=Policy.load(path)
    if policy.users or policy.machines:return False
    try:
        marker=json.loads(protected_file(Path(path).with_name(Path(path).name+'.bootstrap'),max_bytes=256))
        return isinstance(marker.get('verifier'),str)
    except (OSError,ValueError):return False


def _recover(conn,path):
    digest=revision(protected_file(path))
    for row in conn.execute("SELECT * FROM dashboard_changes WHERE policy_id=%s AND state='prepared' ORDER BY created_at",(identity(path),)).fetchall():
        if digest==row['new_revision']:state='applied'
        elif digest==row['old_revision']:state='not_applied'
        else:raise ServiceError('policy_recovery_required',503)
        conn.execute('UPDATE dashboard_changes SET state=%s,finished_at=now() WHERE operation_id=%s',(state,row['operation_id']))
    conn.commit()


def _store(cfg,path,*,operation_id,actor,kind,subject,old,new,principal=None):
    """Caller holds file lock. Prepared audit survives a crash after file replace."""
    with db.connect(cfg) as conn:
        _recover(conn,path)
        if conn.execute('SELECT 1 FROM dashboard_changes WHERE operation_id=%s',(operation_id,)).fetchone():
            raise ServiceError('operation_already_recorded',409)
        if conn.execute('SELECT count(*) n FROM dashboard_changes').fetchone()['n']>=10000:
            raise ServiceError('administrative_audit_capacity',507)
        from .resources import admission
        with admission(cfg) as budget:
            budget.check(incoming=len(new)+4096)
            conn.execute("INSERT INTO dashboard_changes(operation_id,policy_id,actor,kind,subject,old_revision,new_revision,state) VALUES (%s,%s,%s,%s,%s,%s,%s,'prepared')",(operation_id,identity(path),actor,kind,subject,revision(old),revision(new)))
            conn.commit()
            # The prepared journal is durable before the authority transaction.
            # DELETE (logout/expiry cleanup) serializes on this exact row until
            # the file replace and applied-journal commit are both complete.
            if principal is not None:
                conn.execute("SET LOCAL lock_timeout='5s'")
                row=conn.execute('SELECT token_hash FROM service_sessions WHERE token_hash=%s FOR UPDATE',
                                 (principal.session_hash,)).fetchone()
                if not row:raise AuthenticationError()
                from .auth import resolve_reference
                from .ingest import credential_reference
                fresh=resolve_reference(cfg,credential_reference(principal,None))
                if fresh!=principal or not fresh.admin:raise AuthenticationError()
            if protected_file(path)!=old:raise ServiceError('policy_revision_conflict',409)
            if principal is not None and not conn.execute(
                'SELECT 1 FROM service_sessions WHERE token_hash=%s AND expires_at>clock_timestamp()',
                (principal.session_hash,)).fetchone():raise AuthenticationError()
            _replace(path,new)
            conn.execute("UPDATE dashboard_changes SET state='applied',finished_at=now() WHERE operation_id=%s",(operation_id,))
            conn.commit()


def bootstrap(cfg,path,data):
    if set(data)!={'token','username','password'} or not all(isinstance(v,str) for v in data.values()):
        raise ServiceError('invalid_request')
    if not _ID.fullmatch(data['username']):raise ServiceError('invalid_request')
    with policy_lock(path):
        if not available(path):raise ServiceError('already_initialized',409)
        marker=json.loads(protected_file(Path(path).with_name(Path(path).name+'.bootstrap'),max_bytes=256))
        if not hmac.compare_digest(hash_key(data['token']),marker['verifier']):raise AuthenticationError()
        old=protected_file(path);doc=tomlkit.parse(old.decode())
        doc['users']={data['username']:{'admin':True,'password':hash_password(data['password'])}}
        new=tomlkit.dumps(doc).encode();Policy(dict(doc.unwrap()))
        _store(cfg,path,operation_id=str(uuid.uuid4()),actor='bootstrap',kind='bootstrap',subject=data['username'],old=old,new=new)
    return {'initialized':True}


def _change(doc,change,*,generate=False):
    if not isinstance(change,dict) or not {'kind','id'}<=set(change):raise ServiceError('invalid_change')
    kind=change['kind'];subject=change['id'];secret=None
    if not isinstance(subject,str) or not _ID.fullmatch(subject):raise ServiceError('invalid_change')
    if kind=='reranker':
        if set(change)!={'kind','id'}:raise ServiceError('invalid_change')
        from ..reranker_profiles import preset
        preset(subject)
        doc['reranker']={'profile':subject}
        Policy(doc.unwrap())
        return kind,subject,None
    allowed={'kind','id','fields','password'} if kind=='user' else {'kind','id','fields','user'} if kind=='machine' else {'kind','id','key_id'}
    if set(change)-allowed:raise ServiceError('invalid_change')
    if 'users' not in doc:doc['users']={}
    if 'machines' not in doc:doc['machines']={}
    users,machines=doc['users'],doc['machines']
    if kind in {'user','machine'}:
        fields=change.get('fields',{})
        if not isinstance(fields,dict) or set(fields)-FIELDS-({'admin'} if kind=='user' else set()):raise ServiceError('invalid_change')
        for name,value in fields.items():
            if name=='label' and (not isinstance(value,str) or not 1<=len(value)<=120):raise ServiceError('invalid_label')
            if name in {'enabled','admin'} and type(value) is not bool:raise ServiceError('invalid_change')
            if name.endswith(('domains','projects')) and (not isinstance(value,list) or len(value)>64):raise ServiceError('invalid_change')
        table=users if kind=='user' else machines
        if len(table)>=256 and subject not in table:raise ServiceError('principal_capacity',507)
        if subject not in table:table[subject]={}
        row=table[subject]
        for key,value in fields.items():row[key]=value
        if kind=='user' and 'password' in change:row['password']=hash_password(change['password'])
        if kind=='machine':
            if 'user' in change:row['user']=change['user']
            if row.get('user') not in users:raise ServiceError('unknown_user')
        # OutOfOrderTableProxy may return a detached newly inserted Table.
        # Reassign the completed row so interleaved operator TOML remains valid.
        table[subject]=row
    elif kind in {'rotate','revoke'}:
        if subject not in machines:raise ServiceError('unknown_machine')
        key=change.get('key_id')
        if not isinstance(key,str) or not _ID.fullmatch(key) or key=='session':raise ServiceError('invalid_key_id')
        if 'keys' not in machines[subject]:machines[subject]['keys']={}
        keys=machines[subject]['keys']
        if kind=='rotate':
            # Credential ID ownership is stable; never steal another VM's ID.
            if any(key in row.get('keys',{}) for name,row in machines.items() if name!=subject):raise ServiceError('credential_id_conflict',409)
            if len(keys)>=8 and key not in keys:raise ServiceError('credential_capacity',507)
            secret=new_key(key) if generate else key+'.preview'
            keys[key]=hash_key(secret)
        else:
            if key not in keys:raise ServiceError('unknown_key')
            del keys[key]
        machines[subject]['keys']=keys
    else:raise ServiceError('invalid_change')
    Policy(doc.unwrap())
    if not any(row.get('enabled',True) and row.get('admin',False) and row.get('password') for row in users.values()):
        raise ServiceError('last_administrator_required',409)
    return kind,subject,secret


def policy_view(path):
    raw=protected_file(path);policy=Policy(tomlkit.parse(raw.decode()).unwrap())
    def safe(name,row,machine=False):
        return {'id':name,'label':row.get('label',name),'enabled':row.get('enabled',True),
                **{field:row.get(field,[]) for field in sorted(FIELDS-{'label','enabled'})},
                **({'user':row['user'],'keys':[{'id':key,'prefix':key+'.','revoked':False} for key in row.get('keys',{})]} if machine else {'admin':row.get('admin',False),'password_configured':bool(row.get('password'))})}
    return {'revision':revision(raw),'ownership':'file','users':[safe(n,r) for n,r in policy.users.items()],
            'machines':[safe(n,r,True) for n,r in policy.machines.items()]}


def change_policy(cfg,path,principal,data,*,apply=False):
    if not principal.admin:raise ServiceError('administrator_required',403)
    if not isinstance(data,dict) or set(data)-{'revision','change','operation_id'} or not {'revision','change'}<=set(data):raise ServiceError('invalid_request')
    with policy_lock(path):
        # Authentication may have changed while hashing a proposed password.
        from .auth import resolve_reference
        from .ingest import credential_reference
        def current():
            fresh=resolve_reference(cfg,credential_reference(principal,None))
            if not fresh.admin or fresh!=principal:raise AuthenticationError()
        current()
        old=protected_file(path)
        if data['revision']!=revision(old):raise ServiceError('policy_revision_conflict',409)
        doc=tomlkit.parse(old.decode())
        kind,subject,secret=_change(doc,data['change'],generate=apply)
        if kind=='reranker':
            from .dashboard_settings import probe
            probe(cfg,subject)
        current()
        if not apply:return {'valid':True,'revision':data['revision'],'kind':kind,'subject':subject,'ownership':'file','requires_explicit_apply':True}
        operation=str(uuid.UUID(data['operation_id']))
        new=tomlkit.dumps(doc).encode()
        if len(new)>1024*1024:raise ServiceError('policy_capacity',507)
        _store(cfg,path,operation_id=operation,actor=principal.actor,kind=kind,subject=subject,old=old,new=new,principal=principal)
        return {'applied':True,'revision':revision(new),'operation_id':operation,**({'secret_once':secret} if secret else {})}
