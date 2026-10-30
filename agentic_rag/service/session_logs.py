"""Bounded team-readable source logs, without job credentials or mutation grants."""
import json
import re
import uuid
from dataclasses import asdict

from .. import db
from ..continuity import store
from ..continuity.render import render_checkpoint
from .context import request_scope
from .engine import ServiceError
from .read_limits import rows

_SESSION=re.compile(r'svc1:[a-f0-9]{64}:[a-f0-9]{64}')


def publish(conn,principal,session,project):
    """Publish once with immutable team attribution, alongside the durable input."""
    conn.execute('''INSERT INTO service_session_access(session_id,owner_namespace,project,teams,actor)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT(session_id) DO NOTHING''',
                 (session,principal.namespace,project,json.dumps(sorted(principal.session_teams)),principal.actor))
    access=conn.execute('SELECT owner_namespace,project FROM service_session_access WHERE session_id=%s',(session,)).fetchone()
    if access is None or access['owner_namespace']!=principal.namespace or access['project']!=project:
        raise ServiceError('session_project_conflict',409)


def _visible(conn,session):
    if not isinstance(session,str) or not _SESSION.fullmatch(session):raise ServiceError('not_found',404)
    if conn.execute('SELECT 1 FROM service_session_access WHERE session_id=%s',(session,)).fetchone() is None:
        raise ServiceError('not_found',404)


def listing(cfg,principal,*,before=None,limit=50):
    if type(limit) is not int or not 1<=limit<=100:raise ServiceError('invalid_arguments')
    with request_scope(principal,cfg,read_only=True),db.connect(cfg,role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        condition='';params=[]
        if before is not None:
            _visible(conn,before)
            condition='WHERE (created_at,session_id)<(SELECT created_at,session_id FROM service_session_access WHERE session_id=%s)'
            params.append(before)
        params.append(limit)
        result=rows(conn,'SELECT session_id,project,actor,created_at FROM service_session_access '+condition+' ORDER BY created_at DESC,session_id DESC LIMIT %s',params)
        return {'sessions':result,'next':result[-1]['session_id'] if len(result)==limit else None}


def windows(cfg,principal,session,*,after=None,limit=1):
    if type(limit) is not int or not 1<=limit<=4:raise ServiceError('invalid_arguments')
    with request_scope(principal,cfg,read_only=True),db.connect(cfg,role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        _visible(conn,session)
        condition='';params=[session]
        if after is not None:
            try:after=str(uuid.UUID(after))
            except (ValueError,TypeError):raise ServiceError('not_found',404) from None
            if conn.execute('SELECT 1 FROM service_windows WHERE session_id=%s AND id=%s',(session,after)).fetchone() is None:
                raise ServiceError('not_found',404)
            condition='AND (created_at,id)>(SELECT created_at,id FROM service_windows WHERE id=%s)'
            params.append(after)
        params.append(limit)
        result=rows(conn,"SELECT id,input_cursor,output_cursor,state,created_at,applied_at,payload->'window' AS window FROM service_windows WHERE session_id=%s "+condition+' ORDER BY created_at,id LIMIT %s',params)
        return {'session_id':session,'windows':result,'next':str(result[-1]['id']) if len(result)==limit else None}


def checkpoint(cfg,principal,session):
    with request_scope(principal,cfg,read_only=True),db.connect(cfg,role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        _visible(conn,session)
        result=rows(conn,'SELECT * FROM continuation_checkpoints WHERE session_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(session,))
        if not result:raise ServiceError('not_found',404)
        item=store._checkpoint(result[0])
        return {'checkpoint':asdict(item),'rendered':render_checkpoint(item,max_chars=cfg.checkpoint_render_max_chars,
                    current_cwd=item.cwd,current_project_root=item.project_root,stale_days=cfg.stale_days)}
