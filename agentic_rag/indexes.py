"""Opt-in, source-bound embedding generations beside the untouched legacy index.

Operations use savepoints, never commit a caller's pending work. Callers own the
transaction boundary. Inference is finite and happens before canonical row locks.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass,replace
import json
import re

import psycopg

from . import providers
from .embed import vec_literal

SOURCE_HASH='public.embedding_source_hash(d.title,d.project_scope,c.content)'
_UNSET=object()


@dataclass(frozen=True)
class Selection:
    id: str
    name: str
    profile_name: str
    identity: str
    descriptor: dict
    dimensions: int


@dataclass(frozen=True)
class BoundQuery:
    selection: Selection
    vector: str | None
    warnings: tuple[str,...] = ()


def _selection(row):
    return Selection(str(row['id']),row['name'],row['profile_name'],row['identity'],row['descriptor'],row['dimensions'])


def _name(name):
    if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',name):
        raise ValueError('generation name requires 1–48 lowercase ASCII letters, digits or hyphens, starting with a letter')
    return name


def _get(conn,name):
    row=conn.execute('SELECT * FROM public.embedding_generations WHERE name=%s',(_name(name),)).fetchone()
    if row is None:raise ValueError('unknown generation')
    return _selection(row)


def _operator(conn,cfg):
    from .service.context import CURRENT
    if cfg.service_mode=='client' or CURRENT.get() is not None:
        raise PermissionError('local database owner required for global lifecycle')
    allowed=conn.execute("SELECT current_user=pg_get_userbyid(relowner) AND NOT public.rag_service_active() ok FROM pg_class WHERE oid='public.embedding_generations'::regclass").fetchone()
    if not allowed or not allowed['ok']:raise PermissionError('local database owner required for global lifecycle')


@contextmanager
def _bounded(conn,*,vectors=False,ddl=False):
    # Savepoint rollback restores settings on failure; RELEASE requires explicit restoration.
    with conn.transaction():
        settings={'statement_timeout':'10000','lock_timeout':'2000'}
        if ddl:
            settings.update({'maintenance_work_mem':'65536','max_parallel_maintenance_workers':'0'})
        if vectors:
            from .vector_plan import _planned_settings
            conn.execute("SELECT '[1]'::public.halfvec")
            version=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
            names=['statement_timeout','hnsw.ef_search','hnsw.iterative_scan','hnsw.max_scan_tuples','hnsw.scan_mem_multiplier']
            original={r['name']:r['setting'] for r in conn.execute('SELECT name,setting FROM pg_settings WHERE name=ANY(%s)',(names,))}
            settings.update(_planned_settings(version,original))
        original={name:conn.execute('SELECT current_setting(%s) value',(name,)).fetchone()['value'] for name in settings}
        for name,value in settings.items():
            # Never raise an existing stricter caller timeout.
            if name in ('statement_timeout','lock_timeout','maintenance_work_mem'):
                milliseconds=conn.execute('SELECT setting FROM pg_settings WHERE name=%s',(name,)).fetchone()['setting']
                if int(milliseconds):value=str(min(int(milliseconds),int(value)))
            conn.execute('SELECT set_config(%s,%s,true)',(name,value))
        yield
        for name,value in reversed(list(original.items())):conn.execute('SELECT set_config(%s,%s,true)',(name,value))


def _profile(selection,cfg):
    profile=providers.resolve_profile(cfg,selection.profile_name)
    if profile.identity!=selection.identity or profile.descriptor!=selection.descriptor:
        raise providers.ProviderError('identity_mismatch',False,'Configured profile differs from the selected generation; restore it or build another generation.')
    return profile


def _infer(cfg,texts,profile,*,background=False):
    from .service.context import CURRENT
    from .service.fence import LEASE
    server=cfg.service_mode=='server' or (CURRENT.get() is not None and cfg.service_auth_file is not None)
    if not server:return providers.embed_profile(texts,profile)
    from .service.priority import model_slot,check_background
    background=background or LEASE.get() is not None
    if background:
        check_background(cfg)
        profile=replace(profile,timeout=min(profile.timeout,10.0))
    with model_slot(cfg,background=background):return providers.embed_profile(texts,profile)


def create(conn,cfg,name,profile_name):
    _name(name)
    with _bounded(conn,ddl=True):
        _operator(conn,cfg)
        profile=providers.resolve_profile(cfg,profile_name)
        providers.verify_identity(profile)  # metadata only; never corpus inference
        conn.execute('SELECT public.create_embedding_generation(%s,%s,%s,%s::jsonb)',
            (name,profile_name,profile.identity,json.dumps(profile.descriptor)))
        return _get(conn,name)


def _coverage(conn,generation):
    row=conn.execute(f'''SELECT count(*)::int total,
        count(*) FILTER(WHERE v.source_hash={SOURCE_HASH})::int indexed
        FROM public.chunks c JOIN public.documents d ON d.id=c.document_id
        LEFT JOIN public.embedding_vectors v ON v.chunk_id=c.id AND v.generation_id=%s''',(generation.id,)).fetchone()
    return {**row,'remaining':row['total']-row['indexed']}


def status(conn,cfg,name=None):
    with _bounded(conn):
        _operator(conn,cfg)
        generations=[_get(conn,name)] if name is not None else [_selection(r) for r in conn.execute('SELECT * FROM public.embedding_generations ORDER BY created_at,id')]
        selected=active(conn,cfg)
        result=[{'id':g.id,'name':g.name,'identity':g.identity,'descriptor':g.descriptor,
            'profile_name':g.profile_name,'dimensions':g.dimensions,'active':selected is not None and selected.id==g.id,
            **_coverage(conn,g)} for g in generations]
        return result[0] if name is not None else result


def build(conn,cfg,name,*,limit=8,allow_corpus=False):
    if allow_corpus is not True:raise ValueError('explicit allow_corpus=True required for corpus processing')
    if type(limit) is not int or not 1<=limit<=32:raise ValueError('build limit must be 1 through 32')
    with _bounded(conn):
        _operator(conn,cfg)
        generation=_get(conn,name);profile=_profile(generation,cfg)
        rows=conn.execute(f'''SELECT c.id,c.content,{SOURCE_HASH} source_hash
            FROM public.chunks c JOIN public.documents d ON d.id=c.document_id
            LEFT JOIN public.embedding_vectors v ON v.chunk_id=c.id AND v.generation_id=%s
            WHERE v.source_hash IS DISTINCT FROM {SOURCE_HASH}
            ORDER BY c.document_id,c.idx,c.id LIMIT %s''',(generation.id,min(limit,profile.max_batch))).fetchall()
        written=0
        if rows:
            # Never truncate sources silently. Providers enforce each input's finite bounds.
            vectors=_infer(cfg,[r['content'] for r in rows],profile,background=True)
            vectors=providers.validate_vectors(vectors,len(rows),profile.dimensions,profile.normalization)
            written=conn.execute('SELECT public.put_embedding_vectors(%s,%s::uuid[],%s,%s,%s) n',
                (generation.id,[r['id'] for r in rows],[r['source_hash'] for r in rows],
                 [vec_literal(v) for v in vectors],'cli')).fetchone()['n']
        return {'name':generation.name,'written':written,**_coverage(conn,generation)}


def available(conn):
    return conn.execute("SELECT to_regclass('public.embedding_selection') IS NOT NULL present").fetchone()['present']


def active(conn,cfg):
    if not available(conn):return None
    row=conn.execute('''SELECT g.* FROM public.embedding_selection s
        JOIN public.embedding_generations g ON g.id=s.generation_id WHERE s.singleton''').fetchone()
    return _selection(row) if row is not None else None


def _select(conn,cfg,name,expected_active,operation):
    with _bounded(conn):
        _operator(conn,cfg)
        generation=_get(conn,name)
        profile=_profile(generation,cfg)
        providers.verify_identity(profile)
        # Coverage is vacuously complete on an empty store. A fixed synthetic
        # inference must still prove the selected capability and dimensions.
        probe='Synthetic connectivity probe; no stored knowledge.'[:profile.max_input_chars]
        providers.validate_vectors(_infer(cfg,[probe],profile),1,profile.dimensions,profile.normalization)
        if expected_active is _UNSET:
            before=active(conn,cfg);expected_active=before.id if before else None
        elif isinstance(expected_active,Selection):expected_active=expected_active.id
        try:
            conn.execute('SELECT public.select_embedding_generation(%s,%s,%s)',(generation.id,expected_active,operation))
        except psycopg.errors.RaiseException as error:
            if 'coverage incomplete' in str(error):raise ValueError('generation coverage incomplete; build before selection') from None
            if 'selection changed' in str(error):raise ValueError('active selection changed; retry') from None
            raise
        return generation


def activate(conn,cfg,name,*,expected_active=_UNSET):
    return _select(conn,cfg,name,expected_active,'activate')


def rollback(conn,cfg,name,*,expected_active=_UNSET):
    return _select(conn,cfg,name,expected_active,'rollback')


def query_vector(selection,cfg,text):
    profile=_profile(selection,cfg)
    vectors=_infer(cfg,[text],profile)
    vectors=providers.validate_vectors(vectors,1,profile.dimensions,profile.normalization)
    return BoundQuery(selection,vec_literal(vectors[0]))


def _neighbors(conn,bound,*,domain,scopes,at,history):
    if bound.vector is None:return []
    g=bound.selection
    if type(g.dimensions) is not int or not 1<=g.dimensions<=4000:raise ValueError('invalid bound dimension')
    # An immutable descriptor is checked against the DB, even for internally constructed queries.
    valid=conn.execute('SELECT identity,dimensions FROM public.embedding_generations WHERE id=%s',(g.id,)).fetchone()
    if valid is None or valid['identity']!=g.identity or valid['dimensions']!=g.dimensions:raise ValueError('bound generation mismatch')
    common=f'''FROM public.embedding_vectors v JOIN public.chunks c ON c.id=v.chunk_id
       JOIN public.documents d ON d.id=c.document_id
       WHERE v.generation_id=%s AND v.source_hash={SOURCE_HASH}
       AND d.status='active' AND public.assertion_eligible(d.id,COALESCE(%s::timestamptz,now()),%s)
       AND (%s::text IS NULL OR d.domain=%s) AND (%s::text[] IS NULL OR d.project_scope=ANY(%s))'''
    args=(g.id,at,history,domain,domain,scopes,scopes)
    # The partial index predicate is a safely adapted UUID literal. A parameterized
    # generic plan cannot prove this predicate and would lose the bounded ANN path.
    from psycopg import sql
    predicate=sql.Literal(g.id).as_string(conn)+'::uuid'
    ann=common.replace('v.generation_id=%s','v.generation_id='+predicate,1)
    dim=g.dimensions
    return conn.execute(f'''WITH eligible AS MATERIALIZED (
        SELECT c.id,d.id doc_id,d.slug,c.idx,v.source_hash,v.embedding {common} LIMIT 4097
      ), exact_pool AS (
        SELECT id,doc_id,slug,idx,source_hash,embedding <=> %s::public.halfvec distance FROM eligible
        WHERE (SELECT count(*) FROM eligible)<=4096
      ), ann_pool AS MATERIALIZED (
        SELECT c.id,d.id doc_id,d.slug,c.idx,v.source_hash,(v.embedding::public.halfvec({dim})) <=> %s::public.halfvec({dim}) distance
        {ann} AND (SELECT count(*) FROM eligible)>4096
        ORDER BY (v.embedding::public.halfvec({dim})) <=> %s::public.halfvec({dim}) LIMIT 4096
      ), combined AS (SELECT * FROM exact_pool UNION ALL SELECT * FROM ann_pool),
      diverse AS (SELECT *,row_number() OVER(PARTITION BY doc_id ORDER BY distance,idx,id) within_document FROM combined)
      SELECT *,row_number() OVER(ORDER BY distance,slug,idx,id) rank FROM diverse
      WHERE within_document<=2 ORDER BY distance,slug,idx,id LIMIT 50''',
      (*args,bound.vector,bound.vector,*args[1:],bound.vector)).fetchall()


def candidates(conn,bound_query,querytext,*,domain=None,scopes=None,at=None,history=False,k=8,warnings=None,include_context=False):
    if type(k) is not int or not 1<=k<=150:raise ValueError('candidate k must be 1 through 150')
    try:
        with _bounded(conn,vectors=True):
            neighbors=_neighbors(conn,bound_query,domain=domain,scopes=scopes,at=at,history=history)
    except (psycopg.errors.QueryCanceled,psycopg.errors.LockNotAvailable):
        if warnings is not None:warnings.append('managed vector search exceeded its SQL budget; full-text search only')
        neighbors=[]  # bounded semantic stage fails safely into lexical evidence
    with _bounded(conn):
        lexical=conn.execute(f'''SELECT h.*,{SOURCE_HASH} source_hash FROM public.hybrid_search_candidates(%s,NULL,%s,150,%s,COALESCE(%s::timestamptz,now()),%s) h
            JOIN public.chunks c ON c.id=h.chunk_id JOIN public.documents d ON d.id=c.document_id''',
            (querytext,domain,scopes,at,history)).fetchall()
        scored=[(str(r['chunk_id']),r['source_hash'],float(r['score']),None) for r in lexical]
        scored.extend((str(r['id']),r['source_hash'],1.0/(60+r['rank']),None) for r in neighbors)
        if include_context:
            context=conn.execute(f'''SELECT h.*,{SOURCE_HASH} source_hash,
                public.chunk_context_source_hash(d.title,d.body,d.project_scope,c.content) context_hash
                FROM public.contextual_search_candidates(%s,NULL,%s,150,%s,COALESCE(%s::timestamptz,now()),%s,NULL) h
                JOIN public.chunks c ON c.id=h.chunk_id JOIN public.documents d ON d.id=c.document_id''',
                (querytext,domain,scopes,at,history)).fetchall()
            scored.extend((str(r['chunk_id']),r['source_hash'],float(r['score']),r['context_hash']) for r in context)
        if not scored:return []
        # Every stage has its own READ COMMITTED snapshot. Keep scores bound to
        # their observed source, and recheck explicit filters at final projection.
        rows=conn.execute(f'''SELECT d.id document_id,c.id chunk_id,d.title,d.slug,d.domain,d.dtype,
            left(c.content,4000) snippet,d.verified_at,d.provenance,c.idx,sum(s.score)::double precision score
            FROM unnest(%s::uuid[],%s::text[],%s::double precision[],%s::text[]) s(id,hash,score,context_hash)
            JOIN public.chunks c ON c.id=s.id JOIN public.documents d ON d.id=c.document_id
            WHERE s.hash={SOURCE_HASH} AND d.status='active'
            AND (s.context_hash IS NULL OR s.context_hash=public.chunk_context_source_hash(d.title,d.body,d.project_scope,c.content))
            AND public.assertion_eligible(d.id,COALESCE(%s::timestamptz,now()),%s)
            AND (%s::text IS NULL OR d.domain=%s) AND (%s::text[] IS NULL OR d.project_scope=ANY(%s))
            GROUP BY d.id,c.id''',
            ([r[0] for r in scored],[r[1] for r in scored],[r[2] for r in scored],[r[3] for r in scored],at,history,domain,domain,scopes,scopes)).fetchall()
        rows.sort(key=lambda r:(-r['score'],r['slug'],r['idx'],str(r['chunk_id'])))
        return rows[:k]


def near_duplicate(conn,cfg,text,*,domain,scope,threshold,selection=_UNSET):
    if selection is _UNSET:selection=active(conn,cfg)
    if selection is None:return None
    bound=query_vector(selection,cfg,text)
    with _bounded(conn,vectors=True):
        rows=_neighbors(conn,bound,domain=domain,scopes=[scope],at=None,history=False)
    return rows[0]['slug'] if rows and 1-float(rows[0]['distance'])>=threshold else None
