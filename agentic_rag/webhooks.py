"""Scoped management through narrow SQL RPCs on the current transaction."""
from __future__ import annotations

import json
import os
import uuid

import psycopg
from psycopg.types.json import Jsonb

KNOWLEDGE_KINDS=('memory.created','memory.changed','memory.archived','claim.reviewed','source.changed',
                 'lifecycle.applied','lifecycle.recorded','lifecycle.corrected','edge.supersedes','edge.duplicate')
JOB_KINDS=('job.applied','job.error','job.cancelled')
TABLES=('webhook_control','webhook_subscriptions','webhook_events','webhook_deliveries')


class WebhookError(ValueError):
    def __init__(self,code,status=400):
        super().__init__(code)
        self.code,self.status=code,status


def schema_valid(conn):
    from .service.schema import owner_only_tables_valid
    if not owner_only_tables_valid(conn,list(TABLES)):return False
    sequences=conn.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind='S'""",
        (['webhook_resource_order','webhook_events_capture_order_seq'],)).fetchall()
    if len(sequences)!=2:return False
    if conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('s',c.relowner))) a
        WHERE n.nspname='public' AND c.relname IN ('webhook_resource_order','webhook_events_capture_order_seq') AND a.grantee<>c.relowner) bad""").fetchone()['bad']:return False
    columns=conn.execute("""SELECT a.attname,a.atttypid::regtype::text typ,a.attnotnull,a.attidentity
        FROM pg_attribute a WHERE a.attrelid='public.webhook_events'::regclass
        AND a.attname IN ('capture_xid','capture_order') AND NOT a.attisdropped""").fetchall()
    if {r['attname']: (r['typ'],r['attnotnull'],r['attidentity']) for r in columns}!={
        'capture_xid':('xid8',True,''),'capture_order':('bigint',True,'a')}:return False
    checks=conn.execute("""SELECT c.relname,x.conname,pg_get_expr(x.conbin,x.conrelid) expression
        FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid
        WHERE x.conrelid IN ('public.webhook_events'::regclass,'public.webhook_deliveries'::regclass)
        AND x.convalidated AND x.contype='c' AND x.conname=ANY(%s)""",
        (['webhook_event_staging_version','webhook_cancel_origin','webhook_cancel_marker'],)).fetchall()
    if {(r['relname'],r['conname']):r['expression'] for r in checks}!={
        ('webhook_events','webhook_event_staging_version'):'(resource_version >= 0)',
        ('webhook_deliveries','webhook_cancel_origin'):"(cancelled_from = ANY (ARRAY['dead'::text, 'revoked'::text, 'disabled'::text]))",
        ('webhook_deliveries','webhook_cancel_marker'):"((state = 'cancelled'::text) = (cancelled_from IS NOT NULL))"}:return False
    deferred=conn.execute("""SELECT c.relname,t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        WHERE t.tgenabled IN ('O','A') AND t.tgdeferrable AND t.tginitdeferred
        AND t.tgfoid='public.rag_webhook_finalize()'::regprocedure""").fetchall()
    if {(r['relname'],r['tgname']) for r in deferred}!={('webhook_events','webhook_event_admission'),
        ('webhook_subscriptions','webhook_subscription_admission'),('webhook_deliveries','webhook_delivery_admission')}:return False
    required={'rag_webhook_emit','rag_webhook_capture','rag_webhook_manage','rag_webhook_status','rag_webhook_finalize'}
    rows=conn.execute("""SELECT p.proname,p.prosecdef,p.proconfig,
        EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
         WHERE a.grantee<>p.proowner AND (a.privilege_type<>'EXECUTE' OR a.is_grantable OR
         a.grantee NOT IN (SELECT oid FROM pg_roles WHERE
          (p.proname='rag_webhook_manage' AND rolname='rag_writer') OR
          (p.proname='rag_webhook_status' AND rolname IN ('rag_reader','rag_writer'))))) bad
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=ANY(%s)""",(list(required),)).fetchall()
    if len(rows)!=5 or {r['proname'] for r in rows}!=required or any(not r['prosecdef'] or r['bad'] or
            'search_path=pg_catalog, public, pg_temp' not in (r['proconfig'] or []) for r in rows):return False
    triggers=conn.execute("""SELECT c.relname,t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND t.tgenabled IN ('O','A')
        AND t.tgfoid='public.rag_webhook_capture()'::regprocedure""").fetchall()
    return {(r['relname'],r['tgname']) for r in triggers}=={
        ('documents','webhook_documents'),('claim_history','webhook_claim_history'),('source_history','webhook_source_history'),
        ('lifecycle_events','webhook_lifecycle'),('edges','webhook_edges'),('service_windows','webhook_windows')}


def _reference():
    from .service.context import CURRENT
    request=CURRENT.get()
    if request is None:return {'local_uid':os.getuid()}
    from .service.ingest import credential_reference
    try:return credential_reference(request.principal,None)
    except Exception:raise WebhookError('webhook_unavailable',403) from None


def _rpc(conn,operation,args):
    from .service.context import CURRENT
    if operation!='status':
        request=CURRENT.get()
        if (request is not None and (request.read_only or request.principal.readonly)) or os.environ.get('RAG_READONLY')=='1':
            raise WebhookError('webhook_unavailable',403)
    if not schema_valid(conn):raise WebhookError('incompatible_service_schema',503)
    try:
        # Savepoint protects the caller's queued transaction after a denied RPC.
        with conn.transaction():
            if operation=='status':
                return conn.execute('SELECT public.rag_webhook_status(%s) result',(Jsonb(args),)).fetchone()['result']
            return conn.execute('SELECT public.rag_webhook_manage(%s,%s,%s) result',
                                (operation,Jsonb(args),Jsonb(_reference()))).fetchone()['result']
    except psycopg.Error as error:
        code=error.diag.message_primary
        allowed={'webhook_conflict':409,'webhook_unavailable':404,'webhook_capacity':429,
                 'webhook_off':409,'webhook_disabled':409,'webhook_invalid':400}
        raise WebhookError(code if code in allowed else 'webhook_invalid',allowed.get(code,400)) from None


def subscribe(conn,cfg,*,endpoint,domain,project,kinds,idempotency_key):
    from .webhook_delivery import normalize_endpoint
    endpoint=normalize_endpoint(endpoint,allow_http=True)  # HTTP still requires operator-only sender policy.
    uuid.UUID(idempotency_key)
    if not isinstance(kinds,list) or not kinds or len(kinds)>16 or len(set(kinds))!=len(kinds):raise WebhookError('webhook_invalid')
    if any(k not in (JOB_KINDS if domain is None else KNOWLEDGE_KINDS) for k in kinds):raise WebhookError('webhook_invalid')
    if not isinstance(project,str) or project in ('','*','unknown') or (project!='global' and not project.startswith('/')):raise WebhookError('webhook_invalid')
    return _rpc(conn,'subscribe',dict(endpoint=endpoint,domain=domain,project=project,kinds=sorted(kinds),idempotency_key=idempotency_key))


def status(conn,cfg,*,subscription_id):
    uuid.UUID(subscription_id)
    return _rpc(conn,'status',dict(subscription_id=subscription_id))


def _mutate(conn,operation,subscription_id,expected_revision,**kwargs):
    uuid.UUID(subscription_id)
    if type(expected_revision) is not int or not 1<=expected_revision<=1024:raise WebhookError('webhook_invalid')
    return _rpc(conn,operation,dict(subscription_id=subscription_id,expected_revision=expected_revision,**kwargs))


def update(conn,cfg,*,subscription_id,expected_revision,endpoint):
    from .webhook_delivery import normalize_endpoint
    return _mutate(conn,'update',subscription_id,expected_revision,endpoint=normalize_endpoint(endpoint,allow_http=True))


def disable(conn,cfg,*,subscription_id,expected_revision):return _mutate(conn,'disable',subscription_id,expected_revision)
def rotate(conn,cfg,*,subscription_id,expected_revision):return _mutate(conn,'rotate',subscription_id,expected_revision)
def test(conn,cfg,*,subscription_id,expected_revision):return _mutate(conn,'test',subscription_id,expected_revision)
def replay(conn,cfg,*,subscription_id,expected_revision,delivery_id):
    uuid.UUID(delivery_id)
    return _mutate(conn,'replay',subscription_id,expected_revision,delivery_id=delivery_id)
