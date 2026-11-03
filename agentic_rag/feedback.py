"""Audited retrieval metadata gateway, independent of canonical knowledge writes.

No raw query or result body is persisted. Operator approval/export deliberately
lives outside this writer gateway; approval validity is bound to signal revision.
"""
from __future__ import annotations

from contextlib import contextmanager
import dataclasses
import pwd
import hashlib
import json
import os
import socket
import uuid
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from .service.context import CURRENT
from .secrets import strip_secrets
from .evidence_contract import SOURCE_VERSION_SQL

MAX_EVENTS = 1024
MAX_SIGNALS = 2048
MAX_BYTES = 16 * 1024**2
MAX_HOURLY = 120
MAX_REVISIONS = 32
KINDS = ('useful','not_useful','wrong_source','missing_evidence')


class FeedbackError(ValueError):
    def __init__(self, code='feedback_unavailable', status=404):
        super().__init__(code)
        self.code, self.status = code, status


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise FeedbackError() from None


def identity():
    scope = CURRENT.get()
    if scope:
        p = scope.principal
        return dict(namespace=p.namespace, actor=p.actor, client=p.machine_id or p.uploader_id or 'human',
                    independence_id=_digest(['service-user', p.user_id]))
    username=pwd.getpwuid(os.getuid()).pw_name
    actor = 'local:' + str(os.getuid()) + ':' + username
    client = socket.gethostname()
    return dict(namespace=_digest([actor, client]), actor=actor, client=client,
                independence_id=_digest(['local-user', os.getuid(), username]))


def _write(cfg, domain=None, project_scope=None):
    if not cfg.feedback_enabled:
        raise FeedbackError('feedback_disabled',409)
    request = CURRENT.get()
    if os.environ.get('RAG_READONLY','').strip() == '1' or (request and
        (request.read_only or request.principal.readonly or (domain is not None and
         not request.principal.can_write(domain,project_scope)))):
        raise FeedbackError()


def _lock(conn):
    owner=identity()
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,71))',(owner['namespace'],))
    return owner


def _budget(conn, owner, *, event=False, signal=False, incoming=0):
    row=conn.execute('SELECT * FROM retrieval_feedback_usage WHERE namespace=%s',
                     (owner['namespace'],)).fetchone() or dict(events=0,signals=0,bytes=0,recent=[])
    now=conn.execute('SELECT clock_timestamp() now').fetchone()['now']
    recent=[at for at in row['recent'] if (now-datetime.fromisoformat(at)).total_seconds()<3600]
    if (event and row['events']>=MAX_EVENTS) or (signal and row['signals']>=MAX_SIGNALS) or row['bytes']+incoming>MAX_BYTES:
        raise FeedbackError('feedback_quota',429)
    if len(recent)>=MAX_HOURLY:
        raise FeedbackError('feedback_rate_limit',429)
    return row,recent,now


def _reserve(conn, owner, *, event=False, signal=False, incoming=0):
    row,recent,now=_budget(conn,owner,event=event,signal=signal,incoming=incoming)
    # Charge conservatively for JSON/row overhead; acknowledged usage never
    # shrinks when permission changes hide a retained event or signal.
    conn.execute('''INSERT INTO retrieval_feedback_usage(namespace,actor,events,signals,bytes,recent)
        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(namespace) DO UPDATE SET
        events=excluded.events,signals=excluded.signals,bytes=excluded.bytes,recent=excluded.recent''',
        (owner['namespace'],owner['actor'],row['events']+int(event),row['signals']+int(signal),
         row['bytes']+incoming,Jsonb(recent+[now.isoformat()])))


def _audit(conn,owner,operation,identifier):
    conn.execute('INSERT INTO audit_log(actor,op,summary) VALUES (%s,%s,%s)',
                 (owner['actor'],'feedback_'+operation,str(identifier)))


def document_snapshot(conn, document_id):
    """Public narrow seam for local operator validation; respects existing RLS."""
    document_id=_uuid(document_id)
    row=conn.execute('''SELECT id,domain,project_scope,status,rag_document_version(id) evidence_version,
        encode(sha256(convert_to(jsonb_build_array(title,body)::text,'UTF8')),'hex') content_sha256,
        (status='active' AND assertion_eligible(id,now(),false)) eligible FROM documents WHERE id=%s''',(document_id,)).fetchone()
    if row is None:
        raise FeedbackError()
    sources=conn.execute(f'''SELECT DISTINCT s.source_key,{SOURCE_VERSION_SQL} version
        FROM knowledge_sources s JOIN claim_evidence e USING(source_key) LEFT JOIN source_revisions sr USING(source_key)
        WHERE e.document_id=%s ORDER BY s.source_key LIMIT 17''',(document_id,)).fetchall()
    if len(sources)>16:
        raise FeedbackError('feedback_snapshot_limit',413)
    return dict(document_id=document_id,version='fb1:'+_digest([row['evidence_version'],row['content_sha256']]),
                evidence_version=row['evidence_version'],domain=row['domain'],project_scope=row['project_scope'],
                sources=sources,eligible=row['eligible'],status=row['status'])


def _event(conn,event_id):
    row=conn.execute('SELECT * FROM retrieval_feedback_events WHERE id=%s AND namespace=%s',
                     (_uuid(event_id),identity()['namespace'])).fetchone()
    if row is None:
        raise FeedbackError()
    # Every retained reference is still authorized. Changed evidence is labeled.
    stale=False
    for snapshot in row['results']:
        current=document_snapshot(conn,snapshot['document_id'])
        stale |= current['version']!=snapshot['version'] or not current['eligible']
    return {**row,'stale':bool(stale)}


def _signal(conn,feedback_id):
    row=conn.execute('SELECT * FROM retrieval_feedback WHERE id=%s AND namespace=%s',
                     (_uuid(feedback_id),identity()['namespace'])).fetchone()
    if row is None:
        raise FeedbackError()
    event=_event(conn,row['event_id'])
    stale=event['stale']
    for field in ('result','expected'):
        if row[field+'_id']:
            current=document_snapshot(conn,row[field+'_id'])
            stale |= current['version']!=row[field+'_version'] or not current['eligible']
    for entry in row['history']:
        for field in ('result_id','expected_id'):
            if entry.get(field):
                document_snapshot(conn,entry[field])
    return {**row,'stale':bool(stale)}


def _public(row):
    # Never expose a foreign identity or the private operator query.
    return json.loads(_json({k:v for k,v in row.items() if k not in {'namespace','actor','client','independence_id','request_digest','idempotency_key'}}))


@contextmanager
def _transaction(conn):
    # Use the same explicit-commit boundary as the canonical gateways. This also
    # participates in queued DeferredConnection transactions and lets revoked
    # ServiceConnection authority roll back before raising its bounded refusal.
    autocommit=conn.autocommit
    if autocommit:
        from psycopg.pq import TransactionStatus
        if conn.info.transaction_status != TransactionStatus.IDLE:
            raise FeedbackError('feedback_busy',409)
        conn.autocommit=False
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        if autocommit:
            conn.autocommit=True


def capture(conn,cfg,*,query,domain,project=None,scope=None,idempotency_key,k=8,
            strategy='lexical',rerank='off',context='off'):
    from .scope import write_scope
    from .search import search
    from importlib.metadata import version
    if not isinstance(query,str) or not query.strip() or len(query)>10000 or type(k) is not int or not 1<=k<=20:
        raise ValueError('invalid_feedback_search')
    if not isinstance(domain,str) or not domain or len(domain)>200 or (not project and scope!='global') or scope not in (None,'project','global'):
        raise ValueError('feedback_requires_explicit_scope')
    selected=write_scope(project,scope)
    _write(cfg,domain,selected)
    request_key=_uuid(idempotency_key)
    settings=dict(domain=domain,project=project,scope=scope or 'project',k=k,strategy=strategy,rerank=rerank,context=context)
    query_hash=hashlib.sha256(query.encode()).hexdigest()
    digest=_digest([query_hash,settings])
    with _transaction(conn):
        owner=_lock(conn)
        replay=conn.execute('SELECT id,request_digest FROM retrieval_feedback_events WHERE namespace=%s AND idempotency_key=%s',
                            (owner['namespace'],request_key)).fetchone()
        if replay and replay['request_digest']!=digest:
            raise FeedbackError('feedback_conflict',409)
        if replay:
            event=_event(conn,replay['id'])
            return dict(event=_public(event),results=[],warnings=['feedback_replay_metadata_only'])
        _budget(conn,owner,event=True)
        hits,warnings=search(conn,cfg,query,domain=domain,project=project,scope=scope,k=k,strategy=strategy,
                            rerank_mode=rerank,context_mode=context)
        snapshots=[document_snapshot(conn,h.document_id) for h in hits]
        runtime=dict(version=version("agentic-rag"),config_sha256=_digest([cfg.embed_model,cfg.embed_dim,cfg.rerank_model,cfg.rerank_revision,
                                                              cfg.rerank_policy,cfg.retrieval_planned_vectors]),
                     embedding=dict(state='unused' if strategy=='lexical' else 'configured_only',
                                    configured_alias_sha256=_digest([cfg.embed_model,cfg.embed_dim]),actual_model_digest=None),
                     reranker=dict(state='unused' if rerank=='off' or strategy!='auto' else 'configured_only',
                                   configured_revision=cfg.rerank_revision),
                     retrieval=dict(requested_strategy=strategy,lexical_fallback=any('full-text search only' in w for w in warnings),
                                    warnings_sha256=[_digest(w) for w in warnings]))
        if len(_json([owner,domain,selected,settings,snapshots,runtime]).encode())>60000:
            raise FeedbackError('feedback_snapshot_limit',413)
        _reserve(conn,owner,event=True,incoming=2*len(_json([owner,settings,snapshots,runtime]).encode())+4096)
        from .service.tracing import CURRENT_TRACE
        trace=CURRENT_TRACE.get()
        origin_request=getattr(trace,'request_id',None)
        origin_correlation=getattr(trace,'correlation_id',None)
        from .service.queued_transaction import EXECUTION
        execution=EXECUTION.get()
        if execution is not None:
            origin_request=execution.row.get('origin_request_id')
            origin_correlation=execution.row.get('origin_correlation_id')
        row=conn.execute('''INSERT INTO retrieval_feedback_events(namespace,actor,client,independence_id,domain,project_scope,
            idempotency_key,request_digest,query_sha256,settings,runtime,results,origin_request_id,origin_correlation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
            (*owner.values(),domain,selected,request_key,digest,query_hash,Jsonb(settings),Jsonb(runtime),Jsonb(snapshots),origin_request,origin_correlation)).fetchone()
        _audit(conn,owner,'capture',row['id'])
    return dict(event=_public({**row,'stale':False}),results=json.loads(_json([dataclasses.asdict(h) for h in hits])),warnings=warnings)


def _fields(conn,event,kind,result_id,expected_id,comment):
    if kind not in KINDS or not isinstance(comment,str) or len(comment)>1000:
        raise ValueError('invalid_feedback_signal')
    clean=strip_secrets(comment)[0]
    result_id=_uuid(result_id) if result_id else None
    expected_id=_uuid(expected_id) if expected_id else None
    if result_id and result_id not in {r['document_id'] for r in event['results']}:
        raise FeedbackError()
    result=document_snapshot(conn,result_id) if result_id else None
    expected=document_snapshot(conn,expected_id) if expected_id else None
    return dict(kind=kind,result_id=result_id,result_version=result['version'] if result else None,
                expected_id=expected_id,expected_version=expected['version'] if expected else None,comment=clean)


def _history(fields,state,revision):
    return json.loads(_json({**fields,'state':state,'revision':revision,'at':datetime.now(timezone.utc).isoformat()}))


def submit(conn,cfg,*,event_id,kind,idempotency_key,result_id=None,expected_id=None,comment=''):
    _write(cfg)
    request_key=_uuid(idempotency_key)
    with _transaction(conn):
        owner=_lock(conn)
        event=_event(conn,event_id)
        _write(cfg,event['domain'],event['project_scope'])
        fields=_fields(conn,event,kind,result_id,expected_id,comment)
        digest=_digest([str(event['id']),{k:v for k,v in fields.items() if k not in {'result_version','expected_version'}}])
        replay=conn.execute('SELECT id,request_digest FROM retrieval_feedback WHERE namespace=%s AND idempotency_key=%s',
                            (owner['namespace'],request_key)).fetchone()
        if replay:
            if replay['request_digest']!=digest:raise FeedbackError('feedback_conflict',409)
            return _public(_signal(conn,replay['id']))
        history=[_history(fields,'active',1)]
        _reserve(conn,owner,signal=True,incoming=2*len(_json([owner,event['domain'],event['project_scope'],fields,history]).encode())+2048)
        row=conn.execute('''INSERT INTO retrieval_feedback(event_id,namespace,actor,client,independence_id,domain,project_scope,
            idempotency_key,request_digest,kind,result_id,result_version,expected_id,expected_version,comment,history)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
            (event['id'],*owner.values(),event['domain'],event['project_scope'],request_key,digest,*fields.values(),Jsonb(history))).fetchone()
        _audit(conn,owner,'submit',row['id'])
        result=_public(_signal(conn,row['id']))
    return result


def _change(conn,cfg,feedback_id,expected_revision,*,fields=None):
    _write(cfg)
    if type(expected_revision) is not int or expected_revision<1:raise ValueError('invalid_revision')
    with _transaction(conn):
        owner=_lock(conn)
        row=_signal(conn,feedback_id)
        _write(cfg,row['domain'],row['project_scope'])
        if row['revision']!=expected_revision:raise FeedbackError('feedback_conflict',409)
        if row['revision']>=MAX_REVISIONS:raise FeedbackError('feedback_revision_limit',429)
        event=_event(conn,row['event_id'])
        state='active' if fields is not None else 'retracted'
        if fields is None:fields={k:row[k] for k in ('kind','result_id','result_version','expected_id','expected_version','comment')}
        else:fields=_fields(conn,event,**fields)
        history=row['history']+[_history(fields,state,row['revision']+1)]
        _reserve(conn,owner,incoming=2*len(_json([fields,history[-1]]).encode())+2048)
        changed=conn.execute('''UPDATE retrieval_feedback SET kind=%s,result_id=%s,result_version=%s,expected_id=%s,expected_version=%s,
            comment=%s,state=%s,revision=revision+1,history=%s,updated_at=now() WHERE id=%s AND revision=%s RETURNING *''',
            (*fields.values(),state,Jsonb(history),row['id'],expected_revision)).fetchone()
        if changed is None:raise FeedbackError('feedback_conflict',409)
        _audit(conn,owner,'update' if state=='active' else 'retract',row['id'])
        result=_public(_signal(conn,changed['id']))
    return result


def update(conn,cfg,*,feedback_id,expected_revision,kind,result_id=None,expected_id=None,comment=''):
    return _change(conn,cfg,feedback_id,expected_revision,fields=dict(kind=kind,result_id=result_id,expected_id=expected_id,comment=comment))


def retract(conn,cfg,*,feedback_id,expected_revision):
    return _change(conn,cfg,feedback_id,expected_revision)


def get(conn,cfg,*,feedback_id=None,event_id=None):
    if (feedback_id is None)==(event_id is None):raise ValueError('select_one_feedback_or_event')
    return _public(_signal(conn,feedback_id) if feedback_id else _event(conn,event_id))


def list_feedback(conn,cfg,*,limit=20):
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('invalid_limit')
    rows=conn.execute('SELECT id FROM retrieval_feedback WHERE namespace=%s ORDER BY created_at DESC,id DESC LIMIT %s',
                      (identity()['namespace'],limit)).fetchall()
    result=[]
    for row in rows:
        try:result.append(_public(_signal(conn,row['id'])))
        except FeedbackError:pass  # Revoked referenced sources are withheld uniformly.
    return {'feedback':result}
