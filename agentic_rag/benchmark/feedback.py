"""Local operator labels and sealed, network-free retrieval feedback evaluation.

This separate format is never a truth correction, training set or ranking input.
Only an explicit safe query reconstruction can leave the owner-only approval
registry, and every use rechecks the current signal and original source versions.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from .. import db,feedback
from ..service.context import CURRENT
from ..service.fence import LEASE
from . import corrections as private

NEGATIVE=('not_useful','wrong_source','missing_evidence')
FB_VERSION=re.compile(r'fb1:[0-9a-f]{64}')
MAX_TOKENS=2048


def _operator(cfg):
    if CURRENT.get() is not None or LEASE.get() is not None or cfg.service_mode=='client' or os.environ.get('RAG_READONLY','').strip()=='1':
        raise ValueError('operator_local_configuration_required')


@contextmanager
def _connection(cfg,*,write=False):
    _operator(cfg)
    with db.connect(cfg,role='owner') as conn:
        if not write:conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        conn.execute("SET LOCAL statement_timeout='5s'")
        conn.execute("SET LOCAL lock_timeout='2s'")
        owner=conn.execute("""SELECT current_user=pg_get_userbyid(relowner) AND NOT rag_service_active() ok
            FROM pg_class WHERE oid=to_regclass('public.retrieval_feedback_approvals')""").fetchone()
        if not owner or not owner['ok']:raise ValueError('operator_local_database_owner_required')
        yield conn
        if write:conn.commit()
        else:conn.rollback()


def _load(conn,feedback_id):
    try:feedback_id=str(UUID(str(feedback_id)))
    except (ValueError,TypeError,AttributeError):raise ValueError('feedback_unavailable') from None
    row=conn.execute('SELECT * FROM retrieval_feedback WHERE id=%s',(feedback_id,)).fetchone()
    if row is None:raise ValueError('feedback_unavailable')
    return row


def _event(conn,row):
    event=conn.execute('SELECT * FROM retrieval_feedback_events WHERE id=%s',(row['event_id'],)).fetchone()
    if event is None or any(row[k]!=event[k] for k in ('namespace','actor','client','independence_id','domain','project_scope')):
        raise ValueError('feedback_unavailable')
    return event


def _tokens(conn,ids):
    tokens=set()
    for identity in sorted(set(map(str,ids))):
        spans=conn.execute('''SELECT source_key,span_hash FROM claim_evidence WHERE document_id=%s
            ORDER BY source_key,span_hash LIMIT 65''',(identity,)).fetchall()
        if len(spans)>64:raise ValueError('feedback_family_bound')
        if spans:
            for span in spans:
                tokens.update(('source:'+span['source_key'],'span:'+span['span_hash']))
        else:
            row=conn.execute("SELECT encode(sha256(convert_to(body,'UTF8')),'hex') hash FROM documents WHERE id=%s",(identity,)).fetchone()
            if row is None:raise ValueError('feedback_unavailable')
            tokens.add('legacy:'+row['hash'])
    if not tokens or len(tokens)>MAX_TOKENS:raise ValueError('feedback_family_unavailable')
    return sorted(tokens)


def _binding(conn,row,*,negative=True,lock=False):
    event=_event(conn,row)
    if row['state']!='active' or (negative and row['kind'] not in NEGATIVE):raise ValueError('feedback_stale')
    ids={str(r['document_id']) for r in event['results']}
    if row['result_id'] and str(row['result_id']) not in ids:raise ValueError('feedback_stale')
    expected_id=str(row['expected_id']) if row['expected_id'] else None
    if negative and not expected_id:raise ValueError('feedback_expected_source_required')
    anchors=ids|({expected_id} if expected_id else set())
    if lock and anchors:
        ordered=sorted(anchors)
        conn.execute('SELECT id FROM documents WHERE id=ANY(%s::uuid[]) ORDER BY id FOR SHARE',(ordered,)).fetchall()
        conn.execute('SELECT document_id FROM claim_records WHERE document_id=ANY(%s::uuid[]) ORDER BY document_id FOR SHARE',(ordered,)).fetchall()
        conn.execute('''SELECT s.source_key FROM knowledge_sources s WHERE EXISTS(
            SELECT 1 FROM claim_evidence e WHERE e.source_key=s.source_key AND e.document_id=ANY(%s::uuid[]))
            ORDER BY s.source_key FOR SHARE''',(ordered,)).fetchall()
        conn.execute('SELECT document_id FROM fact_assertions WHERE document_id=ANY(%s::uuid[]) ORDER BY document_id FOR SHARE',(ordered,)).fetchall()
    current={identity:feedback.document_snapshot(conn,identity) for identity in anchors}
    for captured in event['results']:
        snap=current[captured['document_id']]
        if not snap['eligible'] or snap['version']!=captured['version']:raise ValueError('feedback_stale')
    expected=current.get(expected_id)
    if expected is not None and (not expected['eligible'] or expected['version']!=row['expected_version']
        or expected['domain']!=event['domain'] or expected['project_scope'] not in
        ({'global'} if event['project_scope']=='global' else {event['project_scope'],'global'})):
        raise ValueError('feedback_stale')
    return event,expected,_tokens(conn,anchors)


def _query(query,event):
    if not isinstance(query,str) or not query.strip() or len(query)>512:raise ValueError('feedback_query_bound')
    private._safe(query)
    if sha256(query.encode()).hexdigest()!=event['query_sha256']:raise ValueError('feedback_query_digest_mismatch')


def approve(cfg,*,feedback_id,expected_revision,query):
    _operator(cfg)
    if not cfg.feedback_enabled:raise feedback.FeedbackError('feedback_disabled',409)
    if type(expected_revision) is not int or not 1<=expected_revision<=32:raise ValueError('invalid_revision')
    with _connection(cfg,write=True) as conn:
        row=_load(conn,feedback_id)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,71))',(row['namespace'],))
        row=_load(conn,feedback_id)
        if row['revision']!=expected_revision:raise ValueError('feedback_conflict')
        event,expected,tokens=_binding(conn,row,lock=True)
        _query(query,event)
        families={'tokens':tokens,'event_sha256':private._hash(event['results'])}
        prior=conn.execute('SELECT * FROM retrieval_feedback_approvals WHERE feedback_id=%s',(row['id'],)).fetchone()
        values=dict(feedback_id=str(row['id']),revision=row['revision'],expected_id=str(row['expected_id']),expected_version=row['expected_version'])
        if prior and all(str(prior[k])==str(v) for k,v in values.items()) and prior['query']==query and prior['families']==families:
            return values
        feedback._reserve(conn,{'namespace':row['namespace'],'actor':row['actor']},incoming=2*len(private._encoded([query,families,values]))+2048)
        conn.execute('''INSERT INTO retrieval_feedback_approvals(feedback_id,revision,query,expected_id,expected_version,families)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(feedback_id) DO UPDATE SET revision=excluded.revision,
            query=excluded.query,expected_id=excluded.expected_id,expected_version=excluded.expected_version,
            families=excluded.families,approved_at=now()''',
            (row['id'],row['revision'],query,row['expected_id'],row['expected_version'],Jsonb(families)))
        feedback._audit(conn,feedback.identity(),'approve',row['id'])
        return values


def _approved(conn,row):
    approval=conn.execute('SELECT * FROM retrieval_feedback_approvals WHERE feedback_id=%s',(row['id'],)).fetchone()
    if approval is None:raise ValueError('feedback_unapproved')
    if approval['revision']!=row['revision'] or approval['expected_id']!=row['expected_id'] or approval['expected_version']!=row['expected_version']:
        raise ValueError('feedback_stale')
    event,expected,tokens=_binding(conn,row)
    _query(approval['query'],event)
    if approval['families']!={'tokens':tokens,'event_sha256':private._hash(event['results'])}:raise ValueError('feedback_stale')
    return approval,event,expected,tokens


def _selected(conn,domain,selected,limit,*,negative=False):
    return conn.execute('''SELECT * FROM retrieval_feedback WHERE domain=%s AND project_scope=%s
        AND (%s::boolean=false OR kind=ANY(%s)) ORDER BY created_at,id LIMIT %s''',
        (domain,selected,negative,list(NEGATIVE),limit+1)).fetchall()


def summary(cfg,*,domain,project=None,scope=None,limit=32):
    _operator(cfg)
    selected=private._selector(domain,project,scope,limit)
    with _connection(cfg) as conn:
        rows=_selected(conn,domain,selected,limit)
        cases=[];withheld=0;active=0
        for row in rows[:limit]:
            if row['state']!='active':continue
            active+=1
            try:_,_,tokens=_binding(conn,row,negative=False)
            except ValueError:withheld+=1;continue
            cases.append(dict(family=str(row['id']),source_families=tokens,actor=row['independence_id'],kind=row['kind']))
        groups=private._split_groups(cases)
        independent={(c['actor'],groups[c['family']]) for c in cases}
        return dict(signals=active,independent_signals=len(independent),source_families=len(set(groups.values())),
            by_kind={kind:len({(c['actor'],groups[c['family']]) for c in cases if c['kind']==kind}) for kind in feedback.KINDS},
            withheld=withheld,records_seen=len(rows[:limit]),limited=len(rows)>limit,
            application_writes=0,provider_calls=0)


def _case_hash(case):
    return private._hash({k:v for k,v in case.items() if k not in ('case_sha256','split','split_family')})


def export_feedback(cfg,*,domain,project=None,scope=None,limit=32,output_path):
    _operator(cfg)
    selected=private._selector(domain,project,scope,limit)
    private._private_path(output_path)
    cases=[];stale=0;withheld=0
    with _connection(cfg) as conn:
        rows=_selected(conn,domain,selected,limit,negative=True)
        for row in rows[:limit]:
            try:approval,event,expected,tokens=_approved(conn,row)
            except ValueError as error:
                if str(error)=='feedback_stale':stale+=1
                else:withheld+=1
                continue
            case=dict(id=str(row['id']),event_id=str(row['event_id']),revision=row['revision'],kind=row['kind'],
                domain=row['domain'],project_scope=row['project_scope'],query=approval['query'],
                expected_id=str(row['expected_id']),expected_version=row['expected_version'],
                expected_evidence_version=expected['evidence_version'],baseline_hit=str(row['expected_id']) in {s['document_id'] for s in event['results']},
                family=private._hash(['feedback',str(row['id'])]),source_families=tokens)
            cases.append(case)
        groups=private._split_groups(cases)
        for case in cases:
            case['split_family']=groups[case['family']]
            case['split']=private._split(case['split_family'])
            case['case_sha256']=_case_hash(case)
        counts=dict(selected=len(rows[:limit]),exported=len(cases),stale=stale,withheld=withheld,limited=len(rows)>limit)
        payload=dict(kind='private-retrieval-feedback',version=1,synthetic=False,domain=domain,project_scope=selected,
            as_of=conn.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat(),source_revision=private._revision(),
            source_schema=[r['filename'] for r in conn.execute('SELECT filename FROM schema_migrations ORDER BY filename')],
            source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),cases=cases,counts=counts)
    payload['artifact_sha256']=private._hash(payload)
    private._write_private(output_path,payload)
    return {**counts,'provider_calls':0,'application_writes':0}


def _validate(data):
    keys={'kind','version','synthetic','domain','project_scope','as_of','source_revision','source_schema','source_sha256','cases','counts','artifact_sha256'}
    if not isinstance(data,dict) or set(data)!=keys or data['kind']!='private-retrieval-feedback' or type(data['version']) is not int or data['version']!=1 or data['synthetic'] is not False:
        raise ValueError('distinct private retrieval feedback format is required')
    private._safe(data)
    if data['artifact_sha256']!=private._hash({k:v for k,v in data.items() if k!='artifact_sha256'}):raise ValueError('private export hash mismatch')
    if not isinstance(data['cases'],list) or len(data['cases'])>32:raise ValueError('feedback_case_bound')
    schema=data['source_schema']
    known=[p.name for p in sorted(db.SQL_DIR.glob('*.sql'))]
    if (not isinstance(schema,list) or not 37<=len(schema)<=len(known) or schema!=known[:len(schema)]
        or not isinstance(data['source_revision'],str) or not re.fullmatch(r'[0-9a-f]{40}',data['source_revision'])
        or not isinstance(data['source_sha256'],str) or not private.HEX.fullmatch(data['source_sha256'])
        or private.parse_time(data['as_of']) is None):
        raise ValueError('invalid feedback provenance')

    if not isinstance(data['domain'],str) or not data['domain'] or not isinstance(data['project_scope'],str) or not (data['project_scope']=='global' or data['project_scope'].startswith('/')):
        raise ValueError('invalid feedback selectors')
    counts=data['counts']
    if not isinstance(counts,dict) or set(counts)!={'selected','exported','stale','withheld','limited'} or any(type(counts[k]) is not int or not 0<=counts[k]<=32 for k in ('selected','exported','stale','withheld')) or type(counts['limited']) is not bool:
        raise ValueError('invalid feedback denominators')
    if counts['exported']!=len(data['cases']) or counts['selected']!=counts['exported']+counts['stale']+counts['withheld']:raise ValueError('invalid feedback denominators')
    seen=set()
    for case in data['cases']:
        required={'id','event_id','revision','kind','domain','project_scope','query','expected_id','expected_version','expected_evidence_version','baseline_hit','family','source_families','split_family','split','case_sha256'}
        if not isinstance(case,dict) or set(case)!=required:raise ValueError('invalid feedback case')
        for field in ('id','event_id','expected_id'):
            try:UUID(case[field])
            except (TypeError,ValueError,AttributeError):raise ValueError('invalid feedback identity') from None
        if case['id'] in seen or case['kind'] not in NEGATIVE or type(case['revision']) is not int or not 1<=case['revision']<=32 or type(case['baseline_hit']) is not bool:
            raise ValueError('invalid feedback case')
        if case['domain']!=data['domain'] or case['project_scope']!=data['project_scope'] or not isinstance(case['query'],str) or not 1<=len(case['query'])<=512:
            raise ValueError('invalid feedback case selectors')
        if not isinstance(case['expected_version'],str) or not FB_VERSION.fullmatch(case['expected_version']) or not re.fullmatch(r'ev1:[0-9a-f]{64}',case['expected_evidence_version']):raise ValueError('invalid feedback version')
        tokens=case['source_families']
        if not isinstance(tokens,list) or not 1<=len(tokens)<=MAX_TOKENS or any(not isinstance(t,str) or not re.fullmatch(r'(source|span|legacy):[0-9a-f]{64}',t) for t in tokens) or tokens!=sorted(set(tokens)):
            raise ValueError('invalid feedback source families')
        if case['family']!=private._hash(['feedback',case['id']]) or case['case_sha256']!=_case_hash(case):raise ValueError('feedback case hash mismatch')
        seen.add(case['id'])
    groups=private._split_groups(data['cases'])
    if any(c['split_family']!=groups[c['family']] or c['split']!=private._split(groups[c['family']]) for c in data['cases']):raise ValueError('feedback source family split leakage')
    return data


def _metrics(details):
    evaluated=[r for r in details if r['state']=='evaluated']
    return dict(selected=len(details),evaluated=len(evaluated),baseline_observed=len(details),
        source_families=len({r['split_family'] for r in details}),
        baseline_hits=sum(r['baseline_hit'] for r in details),baseline_misses=sum(not r['baseline_hit'] for r in details),
        current_hits=sum(r['current_hit'] is True for r in evaluated),current_misses=sum(r['current_hit'] is False for r in evaluated),
        reproduced_failures=sum(not r['baseline_hit'] and r['current_hit'] is False for r in evaluated),
        stale=sum(r['state']=='stale' for r in details),withheld=sum(r['state']=='withheld' for r in details))


def evaluate_export(cfg,*,export_path,output_path):
    _operator(cfg)
    source=private._private_path(export_path,existing=True)
    private._private_path(output_path)
    try:payload=_validate(json.loads(source.read_bytes()))
    except (json.JSONDecodeError,UnicodeError,TypeError,KeyError):raise ValueError('invalid private feedback artifact') from None
    private._verify_private_candidate(source,payload)
    revision=private._revision();source_hash=sha256(Path(__file__).read_bytes()).hexdigest()
    details=[]
    with _connection(cfg) as conn:
        for case in payload['cases']:
            detail=dict(id=case['id'],split=case['split'],split_family=case['split_family'],baseline_hit=case['baseline_hit'],
                        state='stale',current_hit=None,error=None)
            try:
                row=_load(conn,case['id'])
                approval,event,expected,tokens=_approved(conn,row)
                if (row['revision']!=case['revision'] or str(row['event_id'])!=case['event_id'] or row['kind']!=case['kind']
                    or row['domain']!=case['domain'] or row['project_scope']!=case['project_scope']
                    or str(row['expected_id'])!=case['expected_id'] or row['expected_version']!=case['expected_version']
                    or approval['query']!=case['query'] or tokens!=case['source_families']
                    or (str(row['expected_id']) in {s['document_id'] for s in event['results']})!=case['baseline_hit']):
                    raise ValueError('feedback_stale')
                scopes=['global'] if case['project_scope']=='global' else ['global',case['project_scope']]
                # Existing lexical SQL, NULL vector, fixed original k: no model,
                # candidate selection, write, public corpus or held-out tuning.
                with conn.transaction():
                    hits=conn.execute('SELECT document_id FROM hybrid_search_temporal(%s,NULL,%s,%s,%s,now(),false)',
                        (case['query'],case['domain'],event['settings']['k'],scopes)).fetchall()
                detail.update(state='evaluated',current_hit=case['expected_id'] in {str(r['document_id']) for r in hits})
            except ValueError as error:
                detail['state']='withheld' if str(error) in ('feedback_unavailable','feedback_unapproved') else 'stale'
            except psycopg.Error:
                detail.update(state='withheld',error='retrieval_unavailable')
            details.append(detail)
        at=conn.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat()
    metrics=_metrics(details)
    metrics['selected']=payload['counts']['selected']
    metrics['stale']+=payload['counts']['stale'];metrics['withheld']+=payload['counts']['withheld']
    metrics['by_split']={split:_metrics([r for r in details if r['split']==split]) for split in ('dev','test')}
    metrics['by_split']['unassigned']=dict(selected=payload['counts']['stale']+payload['counts']['withheld'],
        evaluated=0,stale=payload['counts']['stale'],withheld=payload['counts']['withheld'])
    metrics.update(provider_calls=0,application_writes=0,limited=payload['counts']['limited'])
    report=dict(kind='private-retrieval-feedback-evaluation',version=1,synthetic=False,as_of=at,profile='fixed-lexical-sql',
        export_sha256=payload['artifact_sha256'],source_revision=revision,source_sha256=source_hash,summary=metrics,cases=details)
    report['artifact_sha256']=private._hash(report)
    private._verify_private_candidate(source,payload)
    if private._revision()!=revision or sha256(Path(__file__).read_bytes()).hexdigest()!=source_hash:raise ValueError('private evaluation source changed')
    private._write_private(output_path,report)
    return metrics
