"""Bounded, typed, request-local metadata. No authority or truth is cached here."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import math
import re
from hashlib import sha256
from psycopg.types.json import Jsonb
import psycopg

TYPES={'string','number','boolean','date','timestamp','string[]','number[]','boolean[]'}
CANONICAL={'dtype':'string','status':'string','slug':'string','created_at':'timestamp',
           'updated_at':'timestamp','verified_at':'timestamp','review_state':'string'}
LIMITS=dict(bytes=16384,depth=6,leaves=32,nodes=64,list=32,string_bytes=1024,pattern_bytes=256,documents=50000,sql_ms=5000)
NAME=re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}\Z',re.ASCII)

class MetadataError(ValueError):
    def __init__(self,code='invalid_filter'):
        self.code=code
        super().__init__(code)

class NormalizedFilter(dict):
    """Internal only: normalized leaves carry a validated type for the pure matcher."""


def registry(value):
    if not isinstance(value,dict) or len(value)>32:raise MetadataError('invalid_metadata_registry')
    if any(not isinstance(k,str) or not NAME.fullmatch(k) or not isinstance(v,str) or v not in TYPES for k,v in value.items()):
        raise MetadataError('invalid_metadata_registry')
    return dict(value)


def _pairs(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise MetadataError()
        out[key]=value
    return out


def parse(value):
    try:
        if isinstance(value,str):
            if len(value.encode())>16384:raise MetadataError()
            value=json.loads(value,object_pairs_hook=_pairs,parse_constant=lambda _: (_ for _ in ()).throw(MetadataError()))
        if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>16384:raise MetadataError()
        return value
    except (ValueError,TypeError,RecursionError,UnicodeError):raise MetadataError() from None


def _value(value,kind):
    if value is None:return None
    if kind.endswith('[]'):
        if not isinstance(value,list) or len(value)>32:raise MetadataError()
        if any(v is None for v in value):raise MetadataError()
        return [_value(v,kind[:-2]) for v in value]
    if kind=='string':
        if not isinstance(value,str) or '\x00' in value or len(value.encode())>1024:raise MetadataError()
    elif kind=='boolean':
        if type(value) is not bool:raise MetadataError()
    elif kind=='number':
        if type(value) not in (int,float) or (isinstance(value,float) and not math.isfinite(value)):raise MetadataError()
    elif kind=='date':
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise MetadataError()
        try:date.fromisoformat(value)
        except ValueError:raise MetadataError() from None
    elif kind=='timestamp':
        try:
            if not isinstance(value,str) or 'T' not in value:raise ValueError()
            stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError()
            value=stamp.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        except (ValueError,OverflowError):raise MetadataError() from None
    return value


def values(value,fields):
    fields=registry(fields);value=parse(value)
    if not isinstance(value,dict) or len(value)>32 or any(k not in fields for k in value):raise MetadataError('invalid_metadata')
    try:return {key:_value(v,fields[key]) for key,v in value.items()}
    except MetadataError:raise MetadataError('invalid_metadata') from None


def normalize(value,fields=None):
    if value is None:return None
    if isinstance(value,NormalizedFilter):return value
    fields=registry(fields or {});value=parse(value)
    if not isinstance(value,dict) or set(value)!={'version','where'} or type(value['version']) is not int or value['version']!=1:raise MetadataError()
    counts=[0,0]
    def node(item,depth):
        counts[0]+=1
        if depth>6 or counts[0]>64 or not isinstance(item,dict):raise MetadataError()
        if set(item) in ({'and'},{'or'}):
            key=next(iter(item));items=item[key]
            if not isinstance(items,list) or not items or len(items)>32:raise MetadataError()
            return {key:[node(n,depth+1) for n in items]}
        if set(item)=={'not'}:return {'not':node(item['not'],depth+1)}
        if set(item)!={'field','op','value'}:raise MetadataError()
        counts[1]+=1
        if counts[1]>32:raise MetadataError()
        field,op,raw=item['field'],item['op'],item['value']
        if not isinstance(field,str) or not isinstance(op,str):raise MetadataError()
        kind=CANONICAL.get(field) if not field.startswith('app.') else fields.get(field[4:])
        if kind is None:raise MetadataError()
        allowed={'exists','is_null','eq','ne'}
        if not kind.endswith('[]'):allowed|={'in','nin'}
        if kind in ('number','date','timestamp'):allowed|={'gt','gte','lt','lte'}
        if kind=='string':allowed|={'prefix','contains'}
        if kind.endswith('[]'):allowed|={'has_any','has_all'}
        if op not in allowed:raise MetadataError()
        if op in ('exists','is_null'):
            if type(raw) is not bool:raise MetadataError()
            result=raw
        elif op in ('in','nin','has_any','has_all'):
            if not isinstance(raw,list) or not 1<=len(raw)<=32 or any(v is None for v in raw):raise MetadataError()
            result=[_value(v,kind[:-2] if kind.endswith('[]') else kind) for v in raw]
        else:
            if raw is None:raise MetadataError()
            result=_value(raw,kind)
            if op in ('prefix','contains') and len(result.encode())>256:raise MetadataError()
        return {'field':field,'op':op,'value':result,'type':kind}
    result=NormalizedFilter(version=1,where=node(value['where'],1))
    parse(result)
    return result


def schema(cfg):
    return dict(version=1,capability='typed_metadata1',canonical_fields=CANONICAL,
                application_fields=dict(cfg.metadata_fields),limits=LIMITS,
                operators=['eq','ne','in','nin','gt','gte','lt','lte','prefix','contains','has_any','has_all','exists','is_null'])


def wire(value):
    if value is None:return None
    def clean(node):
        if isinstance(node,dict):return {k:clean(v) for k,v in node.items() if k!='type'}
        if isinstance(node,list):return [clean(v) for v in node]
        return node
    return clean(value)


def argument(value):return Jsonb(value) if value is not None else None


def identity(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@contextmanager
def filtered(conn,cfg,value,*,domain=None,scopes=None):
    selected=normalize(value,cfg.metadata_fields)
    if selected is None:
        yield None
        return
    try:
        with conn.transaction():
            prior=conn.execute("SELECT setting::int value FROM pg_settings WHERE name='statement_timeout'").fetchone()['value']
            conn.execute("SELECT set_config('statement_timeout',%s,true)",(str(min(prior or 5000,5000)),))
            if not conn.execute("SELECT to_regprocedure('public.rag_metadata_document(uuid,jsonb)') IS NOT NULL present").fetchone()['present']:
                raise MetadataError('unsupported_filter')
            # A limit+1 scan, never an unbounded COUNT, applies the caller's RLS
            # and existing explicit boundary before evaluating any metadata leaf.
            rows=conn.execute('SELECT id FROM documents WHERE (%s::text IS NULL OR domain=%s) AND (%s::text[] IS NULL OR project_scope=ANY(%s)) LIMIT 50001',
                              (domain,domain,scopes,scopes)).fetchall()
            if len(rows)>50000:raise MetadataError('filter_budget')
            yield selected
            conn.execute("SELECT set_config('statement_timeout',%s,true)",(str(prior),))
    except (psycopg.errors.QueryCanceled,psycopg.errors.LockNotAvailable):
        raise MetadataError('filter_budget') from None


def read_boundary(function):
    """Explicit filter arguments; no request-global SQL policy or ambient filter."""
    from functools import wraps
    from inspect import signature
    parameters=signature(function)
    @wraps(function)
    def bounded(*args,**kwargs):
        value=kwargs.get('filter')
        if value is None or isinstance(value,NormalizedFilter):return function(*args,**kwargs)
        bound=parameters.bind(*args,**kwargs);bound.apply_defaults()
        from .config import load_config
        from .scope import selection
        cfg=bound.arguments.get('cfg') or load_config()
        scopes=selection(bound.arguments.get('project'),bound.arguments.get('scope'))
        with filtered(args[0],cfg,value,domain=bound.arguments.get('domain'),scopes=scopes) as selected:
            kwargs['filter']=selected
            return function(*args,**kwargs)
    return bounded


def originals(conn,selected,*,scopes,domain=None,query=None,history=False,limit=24):
    """Uncached source-only projection. Eligibility remains independent of labels."""
    return conn.execute('''SELECT d.id document_id,c.id chunk_id,d.title,d.slug,d.domain,d.dtype,
        d.project_scope,d.verified_at,d.provenance,left(c.content,1200) text,
        r.review_state,r.kind source_kind,d.xmin::text source_version
        FROM documents d JOIN LATERAL (SELECT id,content FROM chunks WHERE document_id=d.id
          AND (%s::text IS NULL OR tsv_en @@ websearch_to_tsquery('english',%s)
            OR tsv_de @@ websearch_to_tsquery('german',%s)) ORDER BY idx,id LIMIT 1) c ON true
        LEFT JOIN claim_records r ON r.document_id=d.id
        WHERE d.status='active' AND assertion_eligible(d.id,statement_timestamp(),%s)
          AND (%s::text[] IS NULL OR d.project_scope=ANY(%s)) AND (%s::text IS NULL OR d.domain=%s)
          AND public.rag_metadata_document(d.id,%s)
        ORDER BY d.updated_at DESC,d.id LIMIT %s''',
        (query,query,query,history,scopes,scopes,domain,domain,argument(selected),limit)).fetchall()


def validate_transport(raw):
    """Preserve duplicate-key evidence before an HTTP/MCP decoder discards it.

    Unfiltered legacy envelopes retain their old decoder behavior. With typed
    arguments present, duplicates anywhere in that envelope are rejected.
    """
    found=[False,False]
    def pairs(items):
        result={}
        for key,value in items:
            if key in ('filter','metadata'):found[0]=True
            if key in result:found[1]=True
            result[key]=value
        return result
    try:json.loads(raw,object_pairs_hook=pairs)
    except (ValueError,UnicodeError,RecursionError):return  # Existing transport owns malformed JSON.
    if found[0] and found[1]:raise MetadataError()
