"""Immutable request authority, explicitly propagated to all engine connections."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json

from .auth import Principal
from .fence import FencedConnection


@dataclass(frozen=True)
class RequestScope:
    principal: Principal
    config: object
    read_only: bool = False


CURRENT: ContextVar[RequestScope | None] = ContextVar('rag_service_request',default=None)


class ServiceConnection(FencedConnection):
    """Bind commit authority to this connection, including transaction contexts."""
    authority_scope = None

    def check_commit_authority(self):
        scope = self.authority_scope
        if scope is None or scope.read_only or scope.principal.readonly:
            return
        from .auth import AuthenticationError, resolve_reference
        from .engine import JobBlocked
        from .ingest import credential_reference
        try:
            fresh = resolve_reference(scope.config, credential_reference(scope.principal, None))
            if fresh != scope.principal:
                raise AuthenticationError()
        except (AuthenticationError, OSError, ValueError):
            self.rollback()
            raise JobBlocked('authorization_changed') from None

    def commit(self):
        self.check_commit_authority()
        return super().commit()

    def commit_accepted_extraction(self):
        # Mining's dedicated staging transaction contains only the immutable
        # provider result and its acceptance audit. Retain this paid-for result
        # after revocation; it grants no authority to apply canonical knowledge.
        # Execution ownership is still fenced by the base connection.
        return super().commit()

    @contextmanager
    def transaction(self, *args, **kwargs):
        with super().transaction(*args, **kwargs) as transaction:
            yield transaction
            self.check_commit_authority()


@contextmanager
def request_scope(principal, config, *, read_only=False):
    token=CURRENT.set(RequestScope(principal,config,read_only))
    try:
        yield
    finally:
        CURRENT.reset(token)


def apply_connection(conn, scope: RequestScope):
    from .schema import validate_schema
    validate_schema(conn)
    p=scope.principal
    values={'active':'1','namespace':p.namespace,'actor':p.actor,
            'read_teams':sorted(p.session_teams),'write_teams':[] if scope.read_only else sorted(p.session_teams),
            'read_domains':sorted(p.read_domains),'read_projects':sorted(p.read_projects),
            'write_domains':[] if scope.read_only else sorted(p.write_domains),
            'write_projects':[] if scope.read_only else sorted(p.write_projects)}
    for key,value in values.items():
        conn.execute('SELECT set_config(%s,%s,false)',('rag_service.'+key,json.dumps(value) if isinstance(value,list) else value))
    # Session values must be committed before a gateway rollback can occur.
    conn.commit()
    # Arm only after the fixed session settings have been committed. Local
    # internal scope probes without an authentication policy remain supported.
    if isinstance(conn, ServiceConnection) and scope.config.service_auth_file is not None:
        conn.authority_scope = scope
    return conn


def actor(default: str) -> str:
    scope=CURRENT.get()
    return scope.principal.actor if scope else default


def wire_scope():
    """Trusted parent-to-owned-subprocess authority; never accept from HTTP input."""
    from dataclasses import asdict
    scope=CURRENT.get()
    if scope is None:
        return None
    return {**asdict(scope.principal),**{k:sorted(getattr(scope.principal,k)) for k in ('read_domains','write_domains','read_projects','write_projects','session_teams')}}
