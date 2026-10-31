"""Bounded projections and setup checks; no browser-owned database credentials."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
from importlib.metadata import version
import json
import re

from psycopg.types.json import Jsonb

from .. import db
from .auth import Policy,resolve_reference
from .context import request_scope
from .engine import ServiceError
from .ingest import credential_reference
from .dashboard_policy import identity,policy_view,revision

MODES={'new-local','existing-local','central','client'}
CHECKS={'database','permissions','embedding','provider','compatibility'}


def _admin(principal):
    if not principal.admin:raise ServiceError('administrator_required',403)


def _fresh(cfg,principal):
    fresh=resolve_reference(cfg,credential_reference(principal,None))
    if fresh!=principal or not fresh.admin:raise ServiceError('authorization_changed',403)


def fingerprint(cfg,path):
    from .auth import protected_file
    try:credential=revision(protected_file(cfg.service_token_file,max_bytes=4096)) if cfg.service_token_file else 'missing'
    except (OSError,ValueError):credential='unavailable'
    from ..providers import ProviderError, _token, resolve_profile
    def reference(env,file):
        try:value=hashlib.sha256(_token(env,file).encode()).hexdigest()
        except ProviderError:value='unavailable'
        return [env,file,value]
    extraction=[cfg.llm_url,cfg.llm_revision,cfg.llm_timeout,cfg.llm_max_input_chars,
        cfg.llm_max_output_tokens,reference(cfg.llm_credential_env,cfg.llm_credential_file)]
    profiles=[]
    for name in sorted(cfg.embedding_profiles):
        profile=resolve_profile(cfg,name)
        profiles.append([name,profile.descriptor,profile.max_batch,profile.max_input_chars,
            profile.timeout,reference(profile.credential_env,profile.credential_file)])
    return hashlib.sha256(json.dumps([revision(protected_file(path)),cfg.db_name,cfg.db_host,cfg.embed_model,cfg.embed_dim,cfg.ollama_url,cfg.llm_provider,cfg.llm_model,cfg.llm_bin,cfg.service_url,credential,extraction,profiles],sort_keys=True).encode()).hexdigest()


def browse(cfg,principal,query):
    limit=int(query.get('limit','25'));offset=int(query.get('offset','0'))
    if not 1<=limit<=50 or not 0<=offset<=10000:raise ServiceError('invalid_pagination')
    clauses=['true'];params=[]
    for key,column in [('domain','d.domain'),('project','d.project_scope')]:
        value=query.get(key)
        if value:
            if len(value)>4096:raise ServiceError('invalid_filter')
            clauses.append(column+'=%s');params.append(value)
    if query.get('pending')=='1':clauses.append("c.review_state='unreviewed'")
    where=' AND '.join(clauses)
    with request_scope(principal,cfg,read_only=True),db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='5s'")
        total=conn.execute('SELECT count(*) n FROM documents d LEFT JOIN claim_records c ON c.document_id=d.id WHERE '+where,params).fetchone()['n']
        # Project bounded strings IN SQL, never pull huge legacy fields first.
        rows=conn.execute('SELECT d.id,left(d.slug,200) slug,left(d.title,240) title,left(d.body,480) preview,left(d.domain,120) domain,left(d.project_scope,256) project,d.status,d.updated_at,c.review_state,c.kind FROM documents d LEFT JOIN claim_records c ON c.document_id=d.id WHERE '+where+' ORDER BY d.updated_at DESC,d.id LIMIT %s OFFSET %s',(*params,limit,offset)).fetchall()
    return {'documents':rows,'total':total,'offset':offset,'limit':limit,'next_offset':offset+limit if offset+limit<total else None}


def overview(cfg,principal):
    with request_scope(principal,cfg,read_only=True),db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION READ ONLY');conn.execute("SET LOCAL statement_timeout='5s'")
        row=conn.execute("SELECT count(*) memories,count(*) FILTER(WHERE c.review_state='unreviewed') pending_reviews FROM documents d LEFT JOIN claim_records c ON c.document_id=d.id").fetchone()
        domains=conn.execute('SELECT left(domain,120) name,count(*) memories FROM documents GROUP BY domain ORDER BY domain LIMIT 64').fetchall()
    return {**row,'domains':domains,'scope':'current-permissions','version':version('agentic-rag')}


def admin_overview(cfg,path,principal):
    _admin(principal)
    policy=policy_view(path)
    authority=Policy.load(path)
    pid=identity(path)
    with db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        presence={r['principal_id']:r for r in conn.execute('SELECT principal_id,seen_at,version,capabilities FROM dashboard_presence WHERE policy_id=%s LIMIT 512',(pid,))}
        queue=[dict(r) for r in conn.execute('SELECT status,count(*) count FROM mining_queue GROUP BY status')]
        foreground=[dict(r) for r in conn.execute('SELECT state,count(*) count FROM service_requests GROUP BY state')]
        audit=[dict(r) for r in conn.execute('SELECT operation_id,actor,kind,subject,state,created_at FROM dashboard_changes WHERE policy_id=%s ORDER BY created_at DESC LIMIT 25',(pid,))]
        setup=conn.execute('SELECT checks FROM dashboard_setup WHERE policy_id=%s',(pid,)).fetchone()
    now=datetime.now(timezone.utc)
    for kind in ('users','machines'):
        for row in policy[kind]:
            record=presence.get(('machine:' if kind=='machines' else 'human:')+row['id'])
            row['access_state']='disabled' if not row['enabled'] else 'revoked' if kind=='machines' and not row['keys'] else 'enabled'
            if kind=='machines' and not authority.users[row['user']].get('enabled',True):row['access_state']='owner-disabled'
            row['connection']={'freshness':'never-seen' if not record else 'online' if (now-record['seen_at']).total_seconds()<300 else 'stale',
                'last_seen':record['seen_at'] if record else None,'reported_version':record['version'] if record else '',
                'reported_capabilities':record['capabilities'] if record else '', 'metadata_trust':'client-reported'}
            if kind=='machines':
                effective=authority.principal(row['user'],machine_id=row['id']) if row['access_state']=='enabled' else None
                row['effective_permissions']={f:sorted(getattr(effective,f)) for f in ('read_domains','write_domains','read_projects','write_projects','session_teams')} if effective else {}
    return {**policy,'source_queue':queue,'foreground_queue':foreground,'administrative_changes':audit,
            'provider_health':setup_status(cfg,path)['checks'].get('provider',{'state':'not-checked','code':'explicit_check_required'}),
            'settings':{'ownership':'file-owned-read-only','provider':str(cfg.llm_provider)[:80],'model':str(cfg.llm_model)[:120],'embedding':str(cfg.embed_model)[:120],'dimension':cfg.embed_dim},
            'offline_is_revoked':False}


def setup_status(cfg,path):
    pid=identity(path)
    with db.connect(cfg) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        state=conn.execute('SELECT mode,checks,completed,updated_at FROM dashboard_setup WHERE policy_id=%s',(pid,)).fetchone()
        exists=conn.execute('SELECT EXISTS(SELECT 1 FROM documents) present').fetchone()['present']
        migrations=[r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')]
    fp=fingerprint(cfg,path)
    result=dict(state or {'mode':None,'checks':{},'completed':False})
    # Old green checks never authorize completion under changed configuration.
    result['checks']={k:v if v.get('fingerprint')==fp else {'state':'stale','code':'configuration_changed'} for k,v in result['checks'].items()}
    result['completed']=bool(result['completed']) and all(result['checks'].get(k,{}).get('state')=='verified' for k in CHECKS)
    result['discovery']={'existing_data':exists,'schema':migrations[-1] if migrations else None,'migration_owner':'operator-cli','database_initialized':True}
    result['modes']=[{'id':mode,'allowed':not(exists and mode=='new-local'),'prerequisite':{'new-local':'Initialize an empty store with rag init first.','existing-local':'Use verified CLI upgrade; retain data and backups.','central':'Deploy current schema/API privately; enroll each client explicitly.','client':'Keep this server canonical; install a client without a local database.'}[mode]} for mode in ('new-local','existing-local','central','client')]
    result['settings_ownership']='file-owned-read-only'
    return result


def _probe(cfg,kind):
    """One explicit synthetic probe globally, low-priority and finite."""
    from .priority import check_background,model_slot
    with db.connect(cfg) as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(684096859) ok').fetchone()['ok']:raise ServiceError('setup_probe_busy',429)
        check_background(cfg)
        if kind=='embedding':
            from .. import embed,query_cache
            digest=query_cache.model_digest(cfg)
            if not digest:return 'unavailable','embedding_identity_unverified'
            with model_slot(cfg,background=True):
                values=embed._embed_texts(['Synthetic connectivity probe; no stored knowledge.'],cfg,timeout=10)
            if len(values)!=1 or len(values[0])!=cfg.embed_dim:return 'unavailable','embedding_dimension_mismatch'
            return 'verified','embedding_access_verified'
        from ..llm import run_structured
        result=run_structured('Synthetic connectivity check. Return {"ok": true}. No tools or data needed.',{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},replace(cfg,llm_timeout=min(cfg.llm_timeout,20)),timeout=20)
        if result.get('ok') is not True:return 'unavailable','provider_response_invalid'
        return 'verified','provider_access_verified'


def _compatibility(cfg):
    """Probe only the operator-owned URL/token; never accept browser targets."""
    from .client import RemoteConnection,RemoteError
    if not cfg.service_url or cfg.service_token_file is None:
        return 'configured','compatibility_target_required',{}
    try:
        with RemoteConnection(cfg) as client:
            capabilities=client.negotiate(seconds=2)
            if not client.queued_tools:return 'unavailable','queued_tools_required',{}
            reported=capabilities.get('server_version','')
            details={'target_id':hashlib.sha256(client.url.encode()).hexdigest(),
                     'protocol':1,'queued_tools':1,
                     'server_version':reported if isinstance(reported,str) and re.fullmatch(r'[0-9A-Za-z.+_-]{1,40}',reported) else ''}
            return 'verified','protocol1_queue1_verified',details
    except RemoteError as exc:
        code='compatibility_authentication_failed' if exc.status in {401,403} else 'unsupported_protocol' if exc.status==426 else 'compatibility_target_unavailable'
        return 'unavailable',code,{}
    except (OSError,ValueError,UnicodeError):
        return 'unavailable','compatibility_configuration_invalid',{}


def setup_action(cfg,path,principal,endpoint,method,data):
    _admin(principal);_fresh(cfg,principal)
    state=setup_status(cfg,path);pid=identity(path)
    if endpoint=='/api/setup/export' and method=='GET':
        if not state['mode']:raise ServiceError('setup_mode_required',409)
        return {'mode':state['mode'],'runtime_settings':'file-owned-read-only','destructive_actions':False,
            'protocol':1,'required_server_capability':'queued_tools=1','schema':state['discovery']['schema'],
            'configuration_template':{'service':{'mode':'client' if state['mode']=='client' else 'server','url':'<your-private-https-origin>' if state['mode']=='client' else '<not-applicable>','token_file':'<private-token-file>'}},
            'operator_steps':['Take and verify a current backup before an existing-store upgrade.','Use rag service preflight/upgrade with an explicit source version and stopped writers.','Review file-owned server/client configuration; apply it explicitly as its owner.','Confirm protocol1, scopes and RO/RW behavior before cutover.']}
    if endpoint=='/api/setup' and method=='GET':return state
    if endpoint=='/api/setup' and method=='POST':
        if set(data)!={'mode'} or data['mode'] not in MODES:raise ServiceError('invalid_setup_mode')
        if data['mode']=='new-local' and state['discovery']['existing_data']:raise ServiceError('existing_store_requires_upgrade',409)
        with db.connect(cfg) as conn:
            _fresh(cfg,principal)
            conn.execute("INSERT INTO dashboard_setup(policy_id,mode) VALUES (%s,%s) ON CONFLICT(policy_id) DO UPDATE SET mode=EXCLUDED.mode,completed=CASE WHEN dashboard_setup.mode=EXCLUDED.mode THEN dashboard_setup.completed ELSE false END,updated_at=now()",(pid,data['mode']))
        return setup_status(cfg,path)
    if not state['mode']:raise ServiceError('setup_mode_required',409)
    if endpoint=='/api/setup/check' and method=='POST':
        if set(data)!={'check'} or data['check'] not in CHECKS:raise ServiceError('invalid_setup_check')
        kind=data['check'];fp=fingerprint(cfg,path);details={}
        if kind in {'embedding','provider'}:
            try:status,code=_probe(cfg,kind)
            except ServiceError:raise
            except Exception:status,code='unavailable',kind+'_access_unavailable'
        elif kind=='database':
            from .schema import validate_schema
            with db.connect(cfg) as conn:validate_schema(conn)
            status,code='verified','database_schema_verified'
        elif kind=='permissions':
            from .schema import validate_schema
            with db.connect(cfg) as conn:validate_schema(conn)
            status,code='verified','administrator_and_scoped_roles_verified'
        else:status,code,details=_compatibility(cfg)
        _fresh(cfg,principal)
        if fp!=fingerprint(cfg,path):raise ServiceError('setup_configuration_changed',409)
        check={'state':status,'code':code,'fingerprint':fp,'checked_at':datetime.now(timezone.utc).isoformat(),**({'details':details} if details else {})}
        with db.connect(cfg) as conn:
            conn.execute('UPDATE dashboard_setup SET checks=checks||%s,completed=false,updated_at=now() WHERE policy_id=%s',(Jsonb({kind:check}),pid))
        return setup_status(cfg,path)
    if endpoint=='/api/setup/complete' and method=='POST':
        if data:raise ServiceError('invalid_request')
        if not all(state['checks'].get(k,{}).get('state')=='verified' for k in CHECKS):raise ServiceError('setup_checks_incomplete',409)
        with db.connect(cfg) as conn:
            _fresh(cfg,principal)
            conn.execute('UPDATE dashboard_setup SET completed=true,updated_at=CASE WHEN completed THEN updated_at ELSE now() END WHERE policy_id=%s AND NOT completed',(pid,))
        return setup_status(cfg,path)
    raise ServiceError('not_found',404)


DASHBOARD_TOOLS={'memory_get','memory_search','memory_evidence','memory_evidence_history','memory_review_claim','memory_source_state'}
STRICT_TOOLS={'memory_review_claim','memory_source_state'}


async def dispatch(cfg,path,principal,endpoint,method,data,query):
    if endpoint=='/api/settings' and method=='GET':
        from .dashboard_settings import settings
        return await asyncio.to_thread(settings,cfg,path,principal)
    if endpoint in {'/api/settings/preview','/api/settings/apply'} and method=='POST':
        from .dashboard_settings import change
        return await asyncio.to_thread(change,cfg,path,principal,data,apply=endpoint.endswith('/apply'))
    if endpoint=='/api/memories' and method=='GET':return await asyncio.to_thread(browse,cfg,principal,query)
    if endpoint=='/api/overview' and method=='GET':return await asyncio.to_thread(overview,cfg,principal)
    if endpoint=='/api/admin' and method=='GET':return await asyncio.to_thread(admin_overview,cfg,path,principal)
    if endpoint.startswith('/api/setup'):
        return await asyncio.to_thread(setup_action,cfg,path,principal,endpoint,method,data)
    if endpoint=='/api/tools' and method=='POST':
        if not isinstance(data,dict) or data.get('tool') not in DASHBOARD_TOOLS:raise ServiceError('dashboard_tool_not_allowed',403)
        if set(data)-{'tool','arguments','idempotency_key','created_at'}:raise ServiceError('invalid_request')
        # The dashboard is a strict client: every decision cites the evidence
        # version the person inspected. Read-only users keep the scope denial.
        arguments=data.get('arguments')
        if data['tool'] in STRICT_TOOLS and not principal.readonly and (not isinstance(arguments,dict)
                or not isinstance(arguments.get('expected_version'),str)
                or (data['tool']=='memory_source_state' and not isinstance(arguments.get('id_or_slug'),str))):
            raise ServiceError('expected_version_required')
        from .requests import submit
        return await asyncio.to_thread(submit,cfg,principal,data)
    if endpoint.startswith('/api/requests/'):
        from .requests import status
        parts=endpoint.split('/')
        if len(parts)==4 and method=='GET':return await asyncio.to_thread(status,cfg,principal,parts[3])
        if len(parts)==5 and parts[4]=='cancel' and method=='POST':return await asyncio.to_thread(status,cfg,principal,parts[3],cancel=True)
    raise ServiceError('not_found',404)
