"""Valid-time selection and evidence-backed atomic assertion gateway internals."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .secrets import strip_secrets_json


def parse_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('time must be ISO-8601 with an explicit timezone') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('time must have an explicit timezone')
    return value.astimezone(timezone.utc)


def selection(as_of=None, history=False):
    if history and as_of is not None:
        raise ValueError('history and as_of are mutually exclusive')
    return parse_time(as_of) or datetime.now(timezone.utc), bool(history)


@dataclass(frozen=True)
class AssertionResult:
    doc_id: str
    slug: str
    disposition: str
    reason: str | None = None
    duplicate: bool = False


def save(conn, cfg, *, entity, attribute, value, event_at, evidence,
         domain, project=None, scope=None, relation='assertion', expires_at=None,
         actor='cli', commit=True):
    from .scope import write_scope
    from .store import save_document, EdgeSpec
    try:
        clean, _ = strip_secrets_json(dict(entity=entity, attribute=attribute, value=value,
                                         evidence=evidence, project=project))
        entity, attribute, value = (clean[k] for k in ('entity','attribute','value'))
        if not all(isinstance(x,str) and 0 < len(x.strip()) <= 2000 for x in (entity,attribute,value)):
            raise ValueError('entity, attribute and value require bounded nonempty strings')
        entity, attribute, value = entity.strip(), attribute.strip(), value.strip()
        evidence = clean['evidence']
        if not isinstance(evidence,dict) or not all(isinstance(evidence.get(k),str) and evidence[k].strip() for k in ('source_id','role','quote')):
            raise ValueError('evidence requires source_id, role and quote')
        if len(json.dumps(evidence)) > 16000:
            raise ValueError('evidence exceeds 16000 characters')
        if relation not in ('assertion','extension','replacement'):
            raise ValueError('unsupported assertion relation')
        when, expiry = parse_time(event_at), parse_time(expires_at)
        if expiry and (when is None or expiry <= when):
            raise ValueError('expiry must be after event time')
        project_scope = write_scope(project=clean['project'],scope=scope) or 'unknown'
        key = json.dumps([project_scope,entity,attribute],ensure_ascii=False)
        lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],signed=True)
        conn.execute('SELECT pg_advisory_xact_lock(%s)',(lock,))
        candidates = conn.execute(
            'SELECT a.*,d.slug FROM fact_assertions a JOIN documents d ON d.id=a.document_id'
            ' WHERE d.project_scope=%s AND a.entity=%s AND a.attribute=%s ORDER BY a.event_at NULLS LAST,a.document_id LIMIT 51',
            (project_scope,entity,attribute)).fetchall()
        reason = None
        if project_scope == 'unknown': reason = 'unknown project applicability'
        elif when is None: reason = 'missing explicit event time'
        elif evidence['role'] != 'user': reason = 'source is not a user assertion'
        elif value not in evidence['quote']: reason = 'value is not quoted in source evidence'
        elif actor == 'mining' and evidence.get('grounding') != 'explicit_statement': reason = 'source does not explicitly affirm this change at the stated time'
        elif len(candidates) > 50: reason = 'candidate history exceeds safe comparison bound'
        if reason is None:
            for c in candidates:
                if c['disposition'] != 'accepted': continue
                if c['event_at'] == when and c['value'] == value and c['relation'] == relation and c['expires_at'] == expiry:
                    retain_source(conn,str(c["document_id"]),evidence,actor)
                    if commit: conn.commit()
                    return AssertionResult(str(c['document_id']),c['slug'],'accepted',duplicate=True)
                if c['event_at'] == when and c['value'] != value and relation != 'extension':
                    reason = 'conflicting values at the same event time'; break
                if c['value'] != value and relation == 'assertion' and c['relation'] != 'extension' and not (c['relation']=='replacement' and c['event_at'] > when):
                    reason = 'different existing value without explicit replacement'; break
        disposition = 'review' if reason else 'accepted'
        edges = []
        if not reason:
            for c in candidates:
                if c['disposition'] != 'accepted' or c['event_at'] is None: continue
                if relation == 'replacement' and c['event_at'] < when:
                    edges.append(EdgeSpec('supersedes',c['slug'],evidence['quote'],'high'))
                elif relation == 'extension':
                    edges.append(EdgeSpec('extends',c['slug'],evidence['quote'],'high'))
        result = save_document(conn,cfg,title=f'{entity}: {attribute}',body=value,
            domain=domain,dtype='memory',project=clean['project'],scope=scope,
            provenance={'origin':'atomic-assertion','evidence':evidence},edges=edges,
            actor=actor,commit=False)
        conn.execute('INSERT INTO fact_assertions(document_id,entity,attribute,value,event_at,expires_at,relation,disposition,review_reason,evidence)'
                     ' VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (result.doc_id,entity,attribute,value,when,expiry,relation,disposition,reason,json.dumps(evidence)))
        retain_source(conn,result.doc_id,evidence,actor)
        if not reason:
            for c in candidates:
                if c['disposition']=='accepted' and c['relation']=='replacement' and c['event_at'] > when:
                    # Late import: the already-known newer event still supersedes this one.
                    conn.execute("INSERT INTO edges(src_id,dst_id,dst_slug,predicate,evidence,confidence,created_by,valid_from)"
                                 " VALUES (%s,%s,%s,'supersedes',%s,'high',%s,%s) ON CONFLICT DO NOTHING",
                                 (c['document_id'],result.doc_id,result.slug,c['evidence']['quote'],'mining' if actor=='mining' else 'manual',c['event_at']))
            conn.execute("UPDATE edges SET valid_from=%s WHERE src_id=%s AND predicate IN ('supersedes','extends')",(when,result.doc_id))
        conn.execute("INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,'save_assertion',%s,%s)",
                     (actor,result.doc_id,f'{disposition}: {reason or relation}; source {evidence["source_id"]}'))
        if commit: conn.commit()
        return AssertionResult(result.doc_id,result.slug,disposition,reason)
    except BaseException:
        if commit: conn.rollback()
        raise


def retain_source(conn, doc_id, evidence, actor):
    encoded=json.dumps(evidence,sort_keys=True,ensure_ascii=False)
    digest=hashlib.sha256(encoded.encode()).hexdigest()
    row=conn.execute('INSERT INTO assertion_sources(document_id,source_hash,evidence) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING source_hash',
                     (doc_id,digest,encoded)).fetchone()
    if row:
        conn.execute("INSERT INTO audit_log(actor,op,document_id,summary) VALUES (%s,'assertion_source',%s,%s)",
                     (actor,doc_id,f'retained source {evidence["source_id"]}; digest {digest}'))
