"""One validated dispatcher for REST and remote MCP, reusing existing tools."""
from __future__ import annotations

import asyncio
from functools import lru_cache
import hashlib
import inspect
import json

from pydantic import validate_call, ValidationError

from .context import request_scope
from .schema import ServiceSchemaError
from ..evidence_contract import EvidenceConflict, EvidenceUnavailable


class JobBlocked(Exception):
    pass


class ServiceError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code,status


class ResourcePressure(ServiceError):
    """Transient admission/storage pressure; acknowledged jobs remain retryable."""


@lru_cache(maxsize=32)
def validator(name):
    from .. import mcp_server
    functions={fn.__name__:fn for fn in (*mcp_server.READ_TOOLS,*mcp_server.WRITE_TOOLS)}
    if name not in functions:
        raise ServiceError('unknown_tool',404)
    return validate_call(functions[name]),name in {f.__name__ for f in mcp_server.WRITE_TOOLS}


async def invoke(name: str, arguments: dict, principal, cfg, *, read_only=False):
    from .priority import foreground
    from contextlib import ExitStack
    with ExitStack() as stack:
        if cfg.service_auth_file is not None or cfg.service_mode == 'server':
            stack.enter_context(foreground(cfg))
        return await _invoke(name, arguments, principal, cfg, read_only=read_only)


async def _invoke(name: str, arguments: dict, principal, cfg, *, read_only=False):
    fn,write=validator(name)
    if write and (read_only or principal.readonly):
        raise ServiceError('scope_denied',403)
    if not isinstance(arguments,dict):
        raise ServiceError('invalid_arguments')
    args=dict(arguments)
    if name=='memory_context' and args.get('session_id'):
        args['session_id']=principal.session_id(args['session_id'])
    if name in {'memory_assert','memory_entity_alias'} and isinstance(args.get('evidence'),dict):
        evidence=dict(args['evidence'])
        legacy=evidence.get('namespace','manual')
        evidence['namespace']='svc1:'+principal.namespace+':manual:'+hashlib.sha256(str(legacy).encode()).hexdigest()
        args['evidence']=evidence
    # Prevent resource amplification even where legacy tools accepted loose ints.
    for field,limit in [('k',50),('depth',3),('max_depth',8),('graph_depth',3)]:
        if field in args and (type(args[field]) is not int or not 0 <= args[field] <= limit):
            raise ServiceError('invalid_arguments')
    if len(json.dumps(args,default=str).encode())>256*1024:
        raise ServiceError('request_too_large',413)
    with request_scope(principal,cfg,read_only=read_only or not write):
        if write and isinstance(args.get('domain'),str):
            domain=args['domain']
            if '*' not in principal.write_domains and domain not in principal.write_domains:
                raise ServiceError('scope_denied',403)
            if args.get('project') is not None or args.get('scope') in {'global','unknown'} or (name=='memory_save' and not args.get('doc_id')):
                from ..scope import write_scope
                try:
                    selected=write_scope(args.get('project'),args.get('scope')) or 'unknown'
                except (ValueError,TypeError):
                    raise ServiceError('invalid_arguments') from None
                if not principal.can_write(domain,selected):
                    raise ServiceError('scope_denied',403)
        try:
            async def execute():
                if inspect.iscoroutinefunction(fn):return await fn(**args)
                return await asyncio.to_thread(fn,**args)
            if not write:return await execute()
            from .resources import admission
            # Gate acquisition/check run off-loop. Keep the aggregate lock until
            # the canonical gateway's own commits have completed.
            from contextlib import ExitStack
            with ExitStack() as stack:
                budget=await asyncio.to_thread(stack.enter_context,admission(cfg))
                await asyncio.to_thread(budget.check,incoming=len(json.dumps(args).encode())*16+65536,owner=principal.namespace,queue=True)
                return await execute()
        except ServiceError:
            raise
        except JobBlocked:
            raise ServiceError('authorization_changed',403) from None
        except ServiceSchemaError:
            raise ServiceError('incompatible_service_schema',503) from None
        except EvidenceConflict:
            raise ServiceError('evidence_conflict',409) from None
        except EvidenceUnavailable:
            raise ServiceError('evidence_unavailable',404) from None
        except (ValidationError,ValueError,TypeError):
            raise ServiceError('invalid_arguments') from None
        except Exception:
            # SQL uniqueness/RLS and provider messages can contain foreign values.
            raise ServiceError('operation_failed') from None
