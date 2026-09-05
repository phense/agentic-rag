"""Bounded claim evidence, current source trust and explicit review."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from .secrets import strip_secrets_json,strip_secrets
from .validity import parse_time

KINDS={'stated','proposal','hypothetical','inference'}

def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

@dataclass(frozen=True)
class ClaimResult:
    doc_id: str
    slug: str
    created: bool


def attach(conn,doc_id,items,actor):
    if not isinstance(items,list) or len(items)>8:
        raise ValueError('claim evidence requires at most eight source spans')
    conn.execute("SELECT document_id FROM claim_records WHERE document_id=%s FOR UPDATE",(doc_id,))
    prepared=[]
    for item in items:
        clean,_=strip_secrets_json(item)
        if not isinstance(clean,dict) or not all(isinstance(clean.get(k),str) and clean[k].strip() for k in ('namespace','source_id','role','quote')):
            raise ValueError('evidence requires namespace, source_id, role and quote')
        if clean['role'] not in ('user','assistant','unknown') or len(clean['quote'])>4000 or len(clean['namespace'])>1000 or len(clean['source_id'])>1000:
            raise ValueError('invalid or unbounded evidence')
        key=_hash(json.dumps([clean['namespace'],clean['source_id']],ensure_ascii=False))
        prepared.append((key,clean))
    # Deterministic order for shared source locks; attachment never resets trust.
    for key,item in sorted(prepared,key=lambda p:p[0]):
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(int.from_bytes(bytes.fromhex(key[:16]),signed=True),))
        at=parse_time(item.get('timestamp'))
        conn.execute('INSERT INTO knowledge_sources(source_key,namespace,source_id,role,source_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                     (key,item['namespace'],item['source_id'],item['role'],at))
        source=conn.execute('SELECT role,source_at FROM knowledge_sources WHERE source_key=%s FOR UPDATE',(key,)).fetchone()
        if source['role']!=item['role'] or source['source_at']!=at:
            raise ValueError('source identity has conflicting metadata')
        span=_hash(item['quote'])
        row=conn.execute('INSERT INTO claim_evidence(document_id,source_key,span_hash,quote,complete) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING source_key',
                         (doc_id,key,span,item['quote'],item.get('complete') is True)).fetchone()
        if row:_audit(conn,actor,'claim_source',doc_id,f'attached source {key}, span {span}')


def _audit(conn,actor,op,doc_id,text):
    conn.execute('INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,%s,%s,%s)',(actor,op,doc_id,strip_secrets(text)[0]))


def save(conn,cfg,*,title,body,domain,dtype,claim_kind,evidence,project=None,scope=None,
         provenance=None,meta=None,edges=None,actor='cli',commit=True):
    from .store import save_document
    from .scope import write_scope
    try:
        if claim_kind not in KINDS:raise ValueError('invalid claim kind')
        clean,_=strip_secrets_json({'body':body,'project':project})
        digest=_hash(clean['body'])
        selected=write_scope(project=clean['project'],scope=scope,provenance=provenance) or 'unknown'
        key=_hash(json.dumps([selected,domain,dtype,claim_kind,digest]))
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(int.from_bytes(bytes.fromhex(key[:16]),signed=True),))
        existing=None
        if selected!='unknown':
            existing=conn.execute('SELECT d.id,d.slug FROM claim_records c JOIN documents d ON d.id=c.document_id WHERE c.content_hash=%s AND c.kind=%s AND d.project_scope=%s AND d.domain=%s AND d.dtype=%s AND d.status=\'active\' AND NOT EXISTS(SELECT 1 FROM fact_assertions a WHERE a.document_id=d.id) ORDER BY d.id LIMIT 1',
                                  (digest,claim_kind,selected,domain,dtype)).fetchone()
        if existing:
            doc_id,slug=str(existing['id']),existing['slug']
        else:
            result=save_document(conn,cfg,title=title,body=body,domain=domain,dtype=dtype,project=project,scope=scope,provenance=provenance,meta=meta,edges=edges,actor=actor,commit=False)
            doc_id,slug=result.doc_id,result.slug
            conn.execute('INSERT INTO claim_records(document_id,kind,content_hash) VALUES (%s,%s,%s)',(doc_id,claim_kind,digest))
        attach(conn,doc_id,evidence,actor)
        _audit(conn,actor,'save_claim',doc_id,f'{claim_kind}; '+('reused exact claim' if existing else 'created immutable claim'))
        if commit:conn.commit()
        return ClaimResult(doc_id,slug,existing is None)
    except BaseException:
        if commit:conn.rollback()
        raise


def source_state(conn,key,*,state,reason,actor='cli',commit=True):
    if state not in ('active','refuted','removed') or not isinstance(reason,str) or not reason.strip():
        raise ValueError('source state change requires valid state and reason')
    try:
        row=conn.execute('UPDATE knowledge_sources SET state=%s,reason=%s,changed_at=now() WHERE source_key=%s RETURNING source_key',
                         (state,strip_secrets(reason)[0],key)).fetchone()
        if not row:raise ValueError('source not found')
        _audit(conn,actor,'source_state',None,f'{key}: {state}; {reason}')
        if commit:conn.commit()
    except BaseException:
        if commit:conn.rollback()
        raise


def review(conn,doc_id,*,state,reason,actor='cli',commit=True):
    if state not in ('confirmed','unreviewed','refuted') or not isinstance(reason,str) or not reason.strip():
        raise ValueError('claim review requires valid state and reason')
    try:
        row=conn.execute('SELECT document_id FROM claim_records WHERE document_id=%s FOR UPDATE',(doc_id,)).fetchone()
        if not row:raise ValueError('managed claim not found')
        if state=='confirmed' and not conn.execute("SELECT 1 FROM claim_evidence e JOIN knowledge_sources s USING(source_key) WHERE e.document_id=%s AND s.state='active' LIMIT 1",(doc_id,)).fetchone():
            raise ValueError('confirmation requires active source evidence')
        if state=='confirmed':
            conn.execute("UPDATE claim_evidence e SET reviewed=true FROM knowledge_sources s WHERE e.source_key=s.source_key AND e.document_id=%s AND s.state='active'",(doc_id,))
        elif state=='unreviewed':
            conn.execute('UPDATE claim_evidence SET reviewed=false WHERE document_id=%s',(doc_id,))
        conn.execute('UPDATE claim_records SET review_state=%s,reason=%s WHERE document_id=%s',(state,strip_secrets(reason)[0],doc_id))
        _audit(conn,actor,'claim_review',doc_id,f'{state}; {reason}')
        if commit:conn.commit()
    except BaseException:
        if commit:conn.rollback()
        raise


def summary(conn,doc_id):
    row=conn.execute("SELECT c.kind,c.review_state,count(DISTINCT e.source_key) FILTER (WHERE s.state='active' AND s.role='user') AS independent_source_count,count(e.source_key) AS spans,bool_and(e.complete) AS complete FROM claim_records c LEFT JOIN claim_evidence e ON e.document_id=c.document_id LEFT JOIN knowledge_sources s USING(source_key) WHERE c.document_id=%s GROUP BY c.document_id",(doc_id,)).fetchone()
    if not row:return {'kind':'legacy','review_state':'unreviewed','provenance_status':'incomplete','independent_source_count':0}
    return {'kind':row['kind'],'review_state':row['review_state'],'provenance_status':'complete' if row['spans'] and row['complete'] else 'incomplete','independent_source_count':row['independent_source_count']}


def sources(conn,doc_id):
    return [dict(r) for r in conn.execute('SELECT s.*,e.quote,e.complete,e.reviewed FROM claim_evidence e JOIN knowledge_sources s USING(source_key) WHERE e.document_id=%s ORDER BY s.source_key,e.span_hash',(doc_id,)).fetchall()]
