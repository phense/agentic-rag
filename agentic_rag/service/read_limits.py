"""Remote-only finite result materialization; standalone contracts stay intact."""
from psycopg import sql
from .context import CURRENT
from .engine import ServiceError

MAX_ROWS=1000
MAX_DOCUMENT_BYTES=512*1024


def document(conn,condition,value):
    if CURRENT.get() is None:return
    row=conn.execute(sql.SQL('SELECT id,octet_length(to_jsonb(d)::text) bytes FROM documents d WHERE '+condition),(value,)).fetchone()
    if row is None:return
    # Count the actual joined records, including repeated source spans and
    # both directions of a self-edge. Extra row/container overhead deliberately
    # errs on the side of rejecting before libpq/Python materialize the result.
    total=row['bytes']+4096
    for query in [
        'SELECT to_jsonb(e) v FROM public.edges e WHERE src_id=%s',
        'SELECT to_jsonb(e)||jsonb_build_object(\'slug\',d.slug) v FROM public.edges e JOIN public.documents d ON d.id=e.src_id WHERE e.dst_id=%s',
        'SELECT to_jsonb(s)||to_jsonb(e) v FROM public.claim_evidence e JOIN public.knowledge_sources s USING(source_key) WHERE e.document_id=%s',
        'SELECT to_jsonb(a) v FROM public.fact_assertions a WHERE document_id=%s',
        'SELECT to_jsonb(a) v FROM public.assertion_sources a WHERE document_id=%s']:
        result=conn.execute('SELECT count(*) n,COALESCE(sum(octet_length(v::text)+256),0) bytes FROM ('+query+') materialized_rows',(row['id'],)).fetchone()
        if result['n']>MAX_ROWS:raise ServiceError('result_too_large',413)
        total+=result['bytes']
    if total>MAX_DOCUMENT_BYTES:raise ServiceError('result_too_large',413)


def rows(conn,query,params=None):
    if CURRENT.get() is None:return conn.execute(query,params).fetchall()
    # Describe only; LIMIT0 transfers no legacy values. Preserve native column
    # types rather than converting UUIDs/timestamps into JSON strings.
    query=sql.SQL(query) if isinstance(query,str) else query
    description=conn.execute(sql.SQL('SELECT * FROM ({}) described LIMIT 0').format(query),params).description
    projection=sql.SQL(',').join(sql.SQL('CASE WHEN budget.ok THEN raw.{} ELSE NULL END AS {}').format(sql.Identifier(c.name),sql.Identifier(c.name)) for c in description)
    # Materialize the query ONCE inside PostgreSQL: size checks and conditional
    # projection share a statement snapshot even on read-committed writers.
    # Oversized values become NULL before libpq/Python receive any row. Limit
    # row count before aggregation; deployment temp/statement caps cover SQL.
    guarded=sql.SQL('''WITH raw AS MATERIALIZED (SELECT selected.*,row_number() OVER () AS __rag_order FROM ({}) selected LIMIT {}),
        budget AS (SELECT count(*)<={} AND
            COALESCE(sum(octet_length(to_jsonb(raw)::text)+256),0)<={} AS ok FROM raw)
        SELECT {},budget.ok AS __rag_size_ok FROM raw CROSS JOIN budget ORDER BY raw.__rag_order''').format(
            query,sql.Literal(MAX_ROWS+1),sql.Literal(MAX_ROWS),sql.Literal(MAX_DOCUMENT_BYTES),projection)
    import uuid
    result=[]
    with conn.cursor(name='rag_read_'+uuid.uuid4().hex) as cursor:
        cursor.execute(guarded,params)
        while batch:=cursor.fetchmany(32):
            for row in batch:
                if not row.pop('__rag_size_ok'):raise ServiceError('result_too_large',413)
                result.append(row)
    return result
