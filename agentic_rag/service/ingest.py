"""Versioned source windows and owned durable receipts; canonical writes stay in mining."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from .. import db
from ..mining_window import MiningWindow
from ..secrets import strip_secrets, strip_secrets_json
from ..validity import parse_time
from .context import request_scope
from .engine import ServiceError
from .spool import canonical
from . import tracing


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Event(Contract):
    source_id: StrictStr=Field(min_length=1,max_length=512)
    role: Literal['user','assistant','unknown']
    timestamp: StrictStr | None=None
    text: StrictStr=Field(min_length=1,max_length=12000)
    offset: StrictInt=Field(ge=0,le=2**63-1)
    complete: StrictBool

    @model_validator(mode='after')
    def valid_fragment(self):
        if '\x00' in self.source_id or '\x00' in self.text or (self.complete and self.offset):
            raise ValueError('invalid evidence fragment')
        return self

    @field_validator('timestamp')
    @classmethod
    def timestamp_valid(cls,value):
        if value is not None: parse_time(value)
        return value


class Window(Contract):
    text: StrictStr=Field(max_length=12000)
    events: list[Event]=Field(max_length=64)
    warnings: list[StrictStr]=Field(max_length=16)
    synthetic: StrictBool
    has_more: StrictBool

    @model_validator(mode='after')
    def consistent_evidence(self):
        if self.text != '\n'.join(event.text for event in self.events):
            raise ValueError('window text must match its consumed evidence fragments')
        if len({event.source_id for event in self.events})!=len(self.events) or any(len(w)>256 or '\x00' in w for w in self.warnings):
            raise ValueError('duplicate events or oversized warning')
        return self


class Envelope(Contract):
    version: StrictInt=Field(ge=1,le=1)
    session_id: StrictStr=Field(min_length=1,max_length=256)
    input_cursor: StrictStr=Field(max_length=4096)
    output_cursor: StrictStr=Field(min_length=1,max_length=4096)
    project: StrictStr=Field(min_length=1,max_length=4096)
    window: Window

    @model_validator(mode='after')
    def cursor_advanced(self):
        if self.input_cursor==self.output_cursor or any('\x00' in v for v in (self.session_id,self.input_cursor,self.output_cursor,self.project)):
            raise ValueError('invalid cursor')
        return self


def normalize(data):
    try:
        return Envelope.model_validate(data)
    except (ValidationError,ValueError,TypeError):
        raise ServiceError('invalid_window') from None


def _project(envelope,principal):
    from ..scope import project_id
    project=project_id(envelope.project) if envelope.project not in {'global','unknown'} else envelope.project
    if principal.readonly or ('*' not in principal.write_projects and project not in principal.write_projects):
        raise ServiceError('scope_denied',403)
    return project


def credential_reference(principal,policy):
    # Capture the credential that actually authenticated this request. Reopening
    # a newer policy must never adopt an unrelated replacement key/password.
    revision=principal.credential_revision
    if not revision:
        from .auth import AuthenticationError
        raise AuthenticationError()
    return {'user':principal.user_id,'machine':principal.machine_id,'credential':principal.credential_id,'revision':revision,'session':principal.session_hash,'uploader':principal.uploader_id}


def accept(cfg,principal,policy,data):
    envelope=normalize(data)
    digest=hashlib.sha256(canonical(envelope.model_dump()).encode()).hexdigest()
    session=principal.session_id(envelope.session_id)
    from .resources import admission
    with admission(cfg) as budget, request_scope(principal,cfg):
        project=_project(envelope,principal)
        with db.connect(cfg,role='writer') as conn:
            # Protect empty streams and exact retries across simultaneous requests.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('service_stream'),hashtext(%s))",(session,))
            existing=conn.execute('SELECT id,content_hash,state,origin_request_id,origin_correlation_id FROM service_windows WHERE session_id=%s AND input_cursor=%s',(session,envelope.input_cursor)).fetchone()
            if existing:
                if existing['content_hash']!=digest: raise ServiceError('cursor_conflict',409)
                tracing.link_job(existing['id'],'source',accepted=True)
                return {'receipt':str(existing['id']),'durable':True,'state':existing['state'],
                        'origin_request_id':str(existing['origin_request_id']) if existing['origin_request_id'] else None,
                        'origin_correlation_id':str(existing['origin_correlation_id']) if existing['origin_correlation_id'] else None}
            stream=conn.execute('SELECT project,last_cursor FROM service_streams WHERE session_id=%s',(session,)).fetchone()
            if (stream and (stream['last_cursor']!=envelope.input_cursor or stream['project']!=project)) or (not stream and envelope.input_cursor):
                raise ServiceError('cursor_conflict',409)
            if conn.execute('SELECT 1 FROM service_windows WHERE session_id=%s AND output_cursor=%s',(session,envelope.output_cursor)).fetchone():
                raise ServiceError('cursor_conflict',409)
            budget.check(owner=principal.namespace,incoming=len(canonical(envelope.model_dump()).encode())+8192,queue=True)
            from .session_logs import publish
            publish(conn,principal,session,project)
            if not stream:
                conn.execute('INSERT INTO service_streams(session_id,owner_namespace,project) VALUES (%s,%s,%s)',(session,principal.namespace,project))
            # Redact again at the server boundary; never retain raw bearer-like input.
            clean,_=strip_secrets_json(envelope.model_dump())
            clean['window']['text']='\n'.join(event['text'] for event in clean['window']['events'])
            clean['_principal']=credential_reference(principal,policy)
            row=conn.execute('''INSERT INTO service_windows(owner_namespace,session_id,input_cursor,output_cursor,content_hash,payload,project,origin_request_id,origin_correlation_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',(principal.namespace,session,envelope.input_cursor,envelope.output_cursor,digest,json.dumps(clean),project,*tracing.origin())).fetchone()
            receipt=str(row['id'])
            job=conn.execute("INSERT INTO mining_queue(kind,session_id,payload,last_uuid) VALUES ('source_window',%s,%s,%s) RETURNING id",(session,json.dumps({'receipt':receipt}),envelope.input_cursor or None)).fetchone()
            conn.execute('UPDATE service_windows SET queue_id=%s WHERE id=%s',(job['id'],receipt))
            conn.execute('UPDATE service_streams SET last_cursor=%s WHERE session_id=%s',(envelope.output_cursor,session))
            conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES (%s,'source_window_accept',%s)",(principal.actor,'accepted source window '+receipt))
        # Connection context commits source, stream and queue together before returning.
    tracing.link_job(receipt,'source',accepted=True)
    request_id,correlation_id=tracing.origin()
    return {'receipt':receipt,'durable':True,'state':'queued','origin_request_id':request_id,'origin_correlation_id':correlation_id}


def receipt_status(cfg,principal,receipt,*,cancel=False):
    try: receipt=str(uuid.UUID(receipt))
    except (ValueError,TypeError): raise ServiceError('not_found',404) from None
    with request_scope(principal,cfg,read_only=not cancel),db.connect(cfg,role='writer' if cancel else 'reader') as conn:
        row=conn.execute('SELECT id,state,queue_id,created_at,applied_at,result,owner_namespace,project,origin_request_id,origin_correlation_id FROM service_windows WHERE id=%s',(receipt,)).fetchone()
        if not row: raise ServiceError('not_found',404)
        if cancel:
            if row['owner_namespace']!=principal.namespace:raise ServiceError('not_found',404)
            if principal.readonly or ('*' not in principal.write_projects and row['project'] not in principal.write_projects):
                raise ServiceError('scope_denied',403)
            locked=conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('service_window'),hashtext(%s)) ok",(receipt,)).fetchone()['ok']
            if not locked: raise ServiceError('job_in_progress',409)
            # Re-read under the same lock held throughout worker application.
            row=conn.execute('SELECT id,state,queue_id,created_at,applied_at,result,origin_request_id,origin_correlation_id FROM service_windows WHERE id=%s',(receipt,)).fetchone()
            if row['state']!='cancelled':
                if row['state']=='applied': raise ServiceError('already_applied',409)
                applied=conn.execute('''SELECT 1 FROM mining_batches b JOIN service_windows w
                    ON w.session_id=b.session_id AND w.input_cursor=b.input_cursor
                    WHERE w.id=%s AND b.applied_at IS NOT NULL''',(receipt,)).fetchone()
                if applied:raise ServiceError('already_applied',409)
                changed=conn.execute("UPDATE service_windows SET state='cancelled' WHERE id=%s RETURNING id",(receipt,)).fetchone()
                if changed is None:raise ServiceError('scope_denied',403)
                queued=conn.execute("UPDATE mining_queue SET status='done',finished_at=now(),payload=payload||'{\"cancelled\":true}'::jsonb WHERE id=%s RETURNING id",(row['queue_id'],)).fetchone()
                if queued is None:raise ServiceError('job_state_conflict',409)
                conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES (%s,'source_window_cancel',%s)",(principal.actor,'cancelled source window '+receipt))
                row['state']='cancelled'
        tracing.link_job(receipt,'source')
        queue=conn.execute('SELECT status,attempts,next_attempt_at FROM mining_queue WHERE id=%s',(row['queue_id'],)).fetchone()
        result=row.get('result')
        code=result.get('code') if isinstance(result,dict) else None
        allowed={'authorization_or_predecessor_blocked','provider_unavailable','processing_failed','database_budget_exceeded','storage_low','storage_check_unavailable','write_capacity_exceeded'}
        return {'origin_request_id':str(row['origin_request_id']) if row['origin_request_id'] else None,'origin_correlation_id':str(row['origin_correlation_id']) if row['origin_correlation_id'] else None,'code':code if code in allowed else None,'receipt':str(row['id']),'state':row['state'],'queue':dict(queue) if queue else None,
                'created_at':row['created_at'].isoformat(),'applied_at':row['applied_at'].isoformat() if row['applied_at'] else None}


def retry_receipt(cfg,principal,policy,receipt):
    """Explicit current authority for an owned blocked receipt, with provenance."""
    try:receipt=str(uuid.UUID(receipt))
    except (ValueError,TypeError):raise ServiceError('not_found',404) from None
    from .resources import admission
    with admission(cfg) as budget,request_scope(principal,cfg),db.connect(cfg,role='writer') as conn:
        row=conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone()
        if row is None or row['owner_namespace']!=principal.namespace:raise ServiceError('not_found',404)
        if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtext('service_window'),hashtext(%s)) ok",(receipt,)).fetchone()['ok']:
            raise ServiceError('job_in_progress',409)
        row=conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone()
        if row['state'] not in {'blocked','error'}:raise ServiceError('job_not_retryable',409)
        if principal.readonly or not principal.write_domains or ('*' not in principal.write_projects and row['project'] not in principal.write_projects):raise ServiceError('scope_denied',403)
        if conn.execute('SELECT 1 FROM mining_batches WHERE session_id=%s AND input_cursor=%s AND applied_at IS NOT NULL',(row['session_id'],row['input_cursor'])).fetchone():raise ServiceError('already_applied',409)
        budget.check(incoming=8192)
        payload=dict(row['payload']);payload.setdefault('_original_principal',payload['_principal'])
        payload['_principal']=credential_reference(principal,policy)
        conn.execute("UPDATE service_windows SET payload=%s,state='queued',result='{}' WHERE id=%s",(json.dumps(payload),receipt))
        conn.execute("UPDATE mining_queue SET status='pending',attempts=0,next_attempt_at=now(),finished_at=NULL,last_error=NULL WHERE id=%s",(row['queue_id'],))
        conn.execute("INSERT INTO audit_log(actor,op,summary) VALUES (%s,'source_window_reauthorize',%s)",(principal.actor,'explicitly reauthorized source window '+receipt))
    return receipt_status(cfg,principal,receipt)


def mining_window(payload):
    window=payload['window']
    return MiningWindow(window['text'],payload['output_cursor'],window['has_more'],tuple(window['warnings']),window['synthetic'],tuple(window['events']))
