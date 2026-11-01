"""Apply durable windows with fresh authority and the existing mining replay gate."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import subprocess

from .. import db, extraction_policy, mining
from ..llm import LLMJobError, LLMUnavailableError
from .auth import AuthenticationError, resolve_reference
from .context import request_scope
from .ingest import mining_window
from .engine import JobBlocked, ResourcePressure
from .fence import WorkerAuthorityLost, assert_authority


def _principal(cfg,reference):
    if cfg.service_auth_file is None: raise JobBlocked('missing_service_policy')
    try:
        return resolve_reference(cfg,reference)
    except (AuthenticationError,KeyError,TypeError):
        raise JobBlocked('authorization_changed') from None


def _state(conn,receipt,state,code):
    conn.execute("UPDATE service_windows SET state=%s,result=%s WHERE id=%s AND state NOT IN ('cancelled','applied')",(state,json.dumps({'code':code}),receipt))
    conn.commit()


def process_embed(cfg,payload):
    from ..store import reembed_document
    principal=_principal(cfg,payload['_principal'])
    def check():
        from .resources import check_worker
        check_worker(cfg)
        if _principal(cfg,payload['_principal'])!=principal:raise JobBlocked('authorization_changed')
    with request_scope(principal,cfg),db.connect(cfg,role='writer') as scoped:
        document=scoped.execute('SELECT domain,project_scope FROM documents WHERE id=%s',(payload['document_id'],)).fetchone()
        if document is None or not principal.can_write(document['domain'],document['project_scope']):raise JobBlocked('scope_denied')
        check()
        reembed_document(scoped,cfg,payload['document_id'],before_commit=check)
    return None


def process_source(conn,cfg,job,*,runner=subprocess.run):
    receipt=str(job['payload']['receipt'])
    row=conn.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone()
    conn.commit()
    if row is None: raise ValueError('missing_source_window')
    if row['state']=='cancelled': return None
    if row['state']=='applied': return replace(mining.MineResult(**row['result']),has_more=False)
    try:
        principal=_principal(cfg,row['payload']['_principal'])
        if not principal.write_domains or ('*' not in principal.write_projects and row['project'] not in principal.write_projects):
            raise JobBlocked('authorization_changed')
        if principal.namespace!=row['owner_namespace']: raise JobBlocked('owner_changed')
        with request_scope(principal,cfg),db.connect(cfg,role='writer') as scoped:
            locked=scoped.execute("SELECT pg_try_advisory_lock(hashtext('service_window'),hashtext(%s)) ok",(receipt,)).fetchone()['ok']
            scoped.commit()
            if not locked: raise JobBlocked('already_processing')
            current=scoped.execute('SELECT * FROM service_windows WHERE id=%s',(receipt,)).fetchone()
            scoped.commit()
            if current is None: raise JobBlocked('scope_denied')
            if current['state']=='cancelled': return None
            if current['state']=='applied': return replace(mining.MineResult(**current['result']),has_more=False)
            predecessor=scoped.execute("SELECT state FROM service_windows WHERE session_id=%s AND output_cursor=%s",(row['session_id'],row['input_cursor'])).fetchone()
            scoped.commit()
            if predecessor and predecessor['state'] not in {'applied','cancelled'}: raise JobBlocked('predecessor_pending')
            def before_apply():
                assert_authority()
                from .resources import check_worker
                check_worker(cfg)
                if _principal(cfg,row['payload']['_principal'])!=principal: raise JobBlocked('authorization_changed')
                accepted=scoped.execute('SELECT extraction FROM mining_batches WHERE session_id=%s AND input_cursor=%s',(row['session_id'],row['input_cursor'])).fetchone()
                if accepted:
                    for kind in ('memories','lessons','signals','assertions','contradictions'):
                        for item in accepted['extraction'].get(kind,[]):
                            if not principal.can_write(item['domain'],row['project']): raise JobBlocked('accepted_output_scope_changed')
            result=mining.mine_session(scoped,cfg,session_id=row['session_id'],transcript_path='',last_uuid=row['input_cursor'] or None,
                project=row['project'],provided_window=mining_window(row['payload']),before_apply=before_apply,runner=runner,
                # Windows admitted without metadata keep builtin rules, never today's file.
                policy=row['payload'].get('_extraction_policy',extraction_policy.LEGACY),policy_origin='window')
            if result.skipped and result.new_last_uuid!=row['output_cursor']: raise JobBlocked('no_writable_domains')
            # Recheck immediately before the receipt transition, too.
            if _principal(cfg,row['payload']['_principal'])!=principal: raise JobBlocked('authorization_changed')
            scoped.execute("UPDATE service_windows SET state='applied',result=%s,applied_at=now() WHERE id=%s",(json.dumps(asdict(result)),receipt))
            scoped.commit()
            return replace(result,has_more=False)
    except WorkerAuthorityLost:
        raise
    except ResourcePressure as exc:
        _state(conn,receipt,'blocked',exc.code)
        raise
    except JobBlocked:
        _state(conn,receipt,'blocked','authorization_or_predecessor_blocked')
        raise
    except LLMUnavailableError as error:
        from .provider_status import failure_code
        terminal = cfg.llm_provider == 'openai-compatible' and job['attempts'] >= cfg.worker_max_attempts
        _state(conn,receipt,'error' if terminal else 'blocked',failure_code(error,'provider_unavailable'))
        raise
    except LLMJobError as error:
        from .provider_status import failure_code
        _state(conn,receipt,'error',failure_code(error,'processing_failed'))
        raise
    except Exception:
        _state(conn,receipt,'error','processing_failed')
        raise
