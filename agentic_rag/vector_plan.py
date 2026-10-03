"""Bounded vector planning without owning the caller's transaction or settings."""
from __future__ import annotations

import re


def available(conn):
    with conn.transaction():
        return conn.execute("SELECT to_regprocedure('public.hybrid_search_contextual_planned(text,halfvec,text,integer,text[],timestamp with time zone,boolean,text)') IS NOT NULL present").fetchone()['present']


def candidates(conn, params):
    # With an existing transaction this is a savepoint, never its commit/rollback.
    # With an idle autocommit connection it owns only its temporary read transaction.
    with conn.transaction():
        # Register the installed extension's GUCs before capability discovery.
        conn.execute("SELECT '[1]'::halfvec")
        version=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
        names=['statement_timeout','hnsw.ef_search','hnsw.iterative_scan',
               'hnsw.max_scan_tuples','hnsw.scan_mem_multiplier']
        original={r['name']:r['setting'] for r in conn.execute(
            'SELECT name,setting FROM pg_settings WHERE name=ANY(%s)',(names,))}
        settings=_planned_settings(version,original)
        for name,value in settings.items():
            conn.execute('SELECT set_config(%s,%s,true)',(name,value))
        rows=conn.execute('SELECT * FROM public.hybrid_search_contextual_planned(%s,%s::halfvec,%s,%s,%s,%s,%s,%s)',params).fetchall()
        # RELEASE SAVEPOINT keeps SET LOCAL changes: restore explicitly on success.
        # Any exception rolls back the savepoint, which restores settings itself.
        for name in reversed(settings):
            conn.execute('SELECT set_config(%s,%s,true)',(name,original[name]))
        return rows


def _planned_settings(version, original):
    """Conservative installed-capability policy; optional GUCs may be absent."""
    timeout=int(original['statement_timeout'])
    settings={'statement_timeout':str(min(timeout,2000) if timeout else 2000),
              'hnsw.ef_search':'256'}
    parsed=re.match(r'^(\d+)\.(\d+)\.(\d+)',version)
    supported=parsed and tuple(map(int,parsed.groups()))>=(0,8,0)
    if supported and all(n in original for n in ('hnsw.iterative_scan','hnsw.max_scan_tuples','hnsw.scan_mem_multiplier')):
        settings.update({'hnsw.iterative_scan':'strict_order',
            'hnsw.max_scan_tuples':str(min(int(original['hnsw.max_scan_tuples']),20000)),
            'hnsw.scan_mem_multiplier':str(min(float(original['hnsw.scan_mem_multiplier']),1.0))})
    return settings
