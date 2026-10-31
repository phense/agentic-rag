"""Static users/machines; secrets are never retained by server configuration."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import tomllib

_ID = re.compile(r'[A-Za-z0-9_-]{1,80}')


class AuthenticationError(Exception):
    def __init__(self):
        super().__init__('invalid credentials')


def protected_file(path: Path,*,max_bytes: int = 1024*1024) -> bytes:
    """Open without following links and reject group/world-readable secrets."""
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('credential configuration must be a regular file')
        if os.name != 'nt' and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
            raise ValueError('credential file permissions must be owner-only')
        if info.st_size > max_bytes:
            raise ValueError('credential configuration too large')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data=stream.read(max_bytes+1)
            if len(data)>max_bytes:raise ValueError('protected file too large')
            return data
    finally:
        os.close(fd)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError('password must contain 12..1024 characters')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32, maxmem=64*1024*1024)
    return f'scrypt$16384$8$1${salt.hex()}${digest.hex()}'


def _password_digest(password: str, verifier: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = verifier.split('$')
        if (algorithm, n, r, p) != ('scrypt', '16384', '8', '1') or len(salt) != 32 or len(expected) != 64:
            return False
        if not isinstance(password, str) or len(password) > 1024:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32, maxmem=64*1024*1024)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def hash_key(token: str) -> str:
    return 'sha256$' + hashlib.sha256(token.encode()).hexdigest()


def new_key(key_id: str) -> str:
    if not _ID.fullmatch(key_id):
        raise ValueError('invalid credential ID')
    return key_id + '.' + secrets.token_urlsafe(32)


def _scopes(row: dict, name: str) -> frozenset[str]:
    values = row.get(name, [])
    if not isinstance(values, list) or any(not isinstance(v, str) or not v or len(v)>4096 for v in values):
        raise ValueError(f'invalid {name}')
    if name.endswith('projects') and any(v not in {'*', 'global', 'unknown'} and not re.fullmatch(r'/[^\x00\r\n]*', v) for v in values):
        raise ValueError(f'invalid {name}')
    return frozenset(values)


def _intersect(a: frozenset[str], b: frozenset[str]) -> frozenset[str]:
    return b if '*' in a else a if '*' in b else a & b


def _teams(row: dict) -> frozenset[str]:
    values=row.get('session_teams',[])
    if not isinstance(values,list) or len(values)>16 or any(not isinstance(v,str) or not _ID.fullmatch(v) for v in values):
        raise ValueError('invalid session teams')
    return frozenset(values)


@dataclass(frozen=True)
class Principal:
    user_id: str
    machine_id: str | None
    credential_id: str
    read_domains: frozenset[str]
    write_domains: frozenset[str]
    read_projects: frozenset[str]
    write_projects: frozenset[str]
    admin: bool = False
    credential_revision: str = ""
    session_hash: str | None = None
    session_teams: frozenset[str] = frozenset()
    uploader_id: str | None = None

    @property
    def namespace(self) -> str:
        # Length-prefix-free canonical JSON avoids delimiter collisions.
        import json
        identity=[self.user_id,self.machine_id]
        if self.machine_id is None and self.uploader_id is not None:
            identity.append(self.uploader_id)
        return hashlib.sha256(json.dumps(identity,separators=(',', ':')).encode()).hexdigest()

    @property
    def readonly(self) -> bool:
        return not self.write_domains or not self.write_projects

    def can_read(self, domain: str, project: str) -> bool:
        return ('*' in self.read_domains or domain in self.read_domains) and ('*' in self.read_projects or project in self.read_projects)

    def can_write(self, domain: str, project: str) -> bool:
        return ('*' in self.write_domains or domain in self.write_domains) and ('*' in self.write_projects or project in self.write_projects)

    @property
    def actor(self) -> str:
        if self.machine_id is None:
            return 'service:human:' + self.user_id
        return 'service:machine:' + self.user_id + ':' + self.machine_id

    def session_id(self, session: str) -> str:
        if not isinstance(session, str) or not 1 <= len(session) <= 256 or '\x00' in session:
            raise ValueError('invalid session ID')
        return 'svc1:' + self.namespace + ':' + hashlib.sha256(session.encode()).hexdigest()


class Policy:
    def __init__(self, data: dict):
        if data.get('version') != 1:
            raise ValueError('unsupported credential configuration version')
        reranker = data.get('reranker', {})
        if not isinstance(reranker, dict) or set(reranker) - {'profile'}:
            raise ValueError('invalid reranker policy')
        self.reranker_profile = reranker.get('profile')
        if self.reranker_profile is not None:
            from ..reranker_profiles import preset
            preset(self.reranker_profile)
        self.users = data.get('users', {})
        self.machines = data.get('machines', {})
        self.keys: dict[str, tuple[str, str]] = {}
        if not isinstance(self.users,dict) or not isinstance(self.machines,dict):
            raise ValueError('invalid credential configuration')
        for name,row in [*self.users.items(), *self.machines.items()]:
            if not _ID.fullmatch(name) or not isinstance(row,dict):
                raise ValueError('invalid principal configuration')
            if type(row.get('enabled',True)) is not bool or type(row.get('admin',False)) is not bool:
                raise ValueError('enabled/admin must be booleans')
            for field in ('read_domains','write_domains','read_projects','write_projects'):
                _scopes(row,field)
            _teams(row)
        for name,row in self.users.items():
            verifier=row.get('password','')
            if verifier and (not isinstance(verifier,str) or not re.fullmatch(r'scrypt\$16384\$8\$1\$[a-f0-9]{32}\$[a-f0-9]{64}',verifier)):
                raise ValueError('invalid password verifier')
        for machine,row in self.machines.items():
            if row.get('user') not in self.users or not isinstance(row.get('keys',{}),dict):
                raise ValueError('machine requires a configured user and key verifiers')
            for key_id,verifier in row.get('keys',{}).items():
                if not _ID.fullmatch(key_id) or key_id=='session' or key_id in self.keys or not isinstance(verifier,str) or not re.fullmatch(r'sha256\$[a-f0-9]{64}',verifier):
                    raise ValueError('invalid or duplicate key verifier')
                self.keys[key_id]=(machine,verifier)

    @classmethod
    def load(cls, path: Path) -> Policy:
        return cls(tomllib.loads(protected_file(path).decode()))

    def principal(self, user_id: str, *, machine_id: str | None = None, credential_id: str = 'session') -> Principal:
        user=self.users.get(user_id)
        machine=self.machines.get(machine_id) if machine_id is not None else None
        if not user or not user.get('enabled',True) or (machine_id is not None and (not machine or not machine.get('enabled',True) or machine.get('user') != user_id)):
            raise AuthenticationError()
        rights={}
        for field in ('read_domains','write_domains','read_projects','write_projects'):
            rights[field]=_scopes(user,field)
            if machine is not None:
                rights[field]=_intersect(rights[field],_scopes(machine,field))
        # Write access always implies read access, never broadens it.
        rights['write_domains']=_intersect(rights['write_domains'],rights['read_domains'])
        rights['write_projects']=_intersect(rights['write_projects'],rights['read_projects'])
        teams=_teams(user)
        if machine is not None and 'session_teams' in machine:
            teams &= _teams(machine)
        revision=self.password_revision(user_id) if machine_id is None else self.keys.get(credential_id,('', ''))[1]
        return Principal(user_id,machine_id,credential_id,**rights,admin=bool(user.get('admin')) and machine is None,credential_revision=revision,session_teams=teams)

    def authenticate_key(self, token: str) -> Principal:
        if not isinstance(token,str) or len(token)>2048:
            raise AuthenticationError()
        found=self.keys.get(token.partition('.')[0])
        if not found or not hmac.compare_digest(hash_key(token),found[1]):
            raise AuthenticationError()
        machine_id=found[0]
        return self.principal(self.machines[machine_id]['user'],machine_id=machine_id,credential_id=token.partition('.')[0])

    def authenticate_password(self, user_id: str, password: str) -> Principal:
        user=self.users.get(user_id,{})
        # Match the same scrypt cost for unknown accounts, no username oracle.
        dummy='scrypt$16384$8$1$'+'00'*16+'$'+'00'*32
        if not _password_digest(password,user.get('password') or dummy):
            raise AuthenticationError()
        return self.principal(user_id)

    def password_revision(self, user_id: str) -> str:
        return hashlib.sha256(self.users.get(user_id,{}).get('password','').encode()).hexdigest()


def session_record(cfg,token_hash):
    """Trusted fixed lookup only; session state is never exposed to scoped SQL."""
    if not isinstance(token_hash,str) or not re.fullmatch(r'sha256\$[a-f0-9]{64}',token_hash):
        return None
    from .. import db
    from .context import CURRENT
    token=CURRENT.set(None)
    try:conn=db.connect(cfg)
    finally:CURRENT.reset(token)
    with conn:
        conn.execute('SET TRANSACTION READ ONLY')
        return conn.execute('SELECT user_id,password_revision,uploader_id::text AS uploader_id FROM public.service_sessions WHERE token_hash=%s AND expires_at>now()', (token_hash,)).fetchone()


def resolve_reference(cfg, reference):
    """Reload the exact authenticated credential, never adopt a new revision."""
    from dataclasses import replace
    if cfg.service_auth_file is None:
        raise AuthenticationError()
    policy = Policy.load(cfg.service_auth_file)
    try:
        if reference['machine'] is None:
            if policy.password_revision(reference['user']) != reference['revision']:
                raise AuthenticationError()
            session = session_record(cfg, reference.get('session'))
            if not session or not session['uploader_id'] or session['user_id'] != reference['user'] or session['password_revision'] != reference['revision'] or session['uploader_id'] != reference.get('uploader'):
                raise AuthenticationError()
        elif policy.keys.get(reference['credential']) != (reference['machine'], reference['revision']):
            raise AuthenticationError()
        return replace(policy.principal(reference['user'], machine_id=reference['machine'], credential_id=reference['credential']),
                       session_hash=reference.get('session') if reference['machine'] is None else None,
                       uploader_id=session['uploader_id'] if reference['machine'] is None else None)
    except (KeyError, TypeError):
        raise AuthenticationError() from None
