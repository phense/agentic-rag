"""Hybrid search wrapper: embed the query (fail-open), call hybrid_search()."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .config import Config
from .embed import try_embed_texts, vec_literal


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    chunk_id: str
    title: str
    slug: str
    domain: str
    dtype: str
    snippet: str
    score: float
    verified_at: datetime | None
    provenance: dict
    evidence: dict = field(default_factory=dict)
    snippet_start: int = 0
    snippet_end: int = 0
    citation: str = ""
    graph_depth: int = 0


def search(
    conn, cfg: Config, query: str, domain: str | None = None, k: int = 8,
    *, project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool = False, graph_depth: int = 0, reranker=None, baseline: bool = False
) -> tuple[list[SearchHit], list[str]]:
    if type(k) is not int or not 1<=k<=100:raise ValueError("k must be between 1 and 100")
    if type(graph_depth) is not int or not 0<=graph_depth<=2:raise ValueError("graph_depth must be 0, 1 or 2")
    if baseline and (graph_depth or reranker is not None):
        raise ValueError("baseline cannot combine with optional retrieval stages")
    from .scope import selection
    scopes = selection(project, scope)
    from .validity import selection as time_selection
    at, history = time_selection(as_of, history)
    warnings: list[str] = []
    vecs = try_embed_texts([query], cfg)
    if vecs is None:
        warnings.append("embedding unavailable — full-text search only")
        qvec = None
    else:
        qvec = vec_literal(vecs[0])
    function="hybrid_search_temporal" if baseline else "hybrid_search_candidates"
    rows = conn.execute(
        f"SELECT * FROM {function}(%s, %s::halfvec, %s, %s, %s, %s, %s)",
        (query, qvec, domain, k if baseline else 150, scopes, at, history),
    ).fetchall()
    from .evidence import summary
    hits = [
        SearchHit(str(r["document_id"]), str(r["chunk_id"]), r["title"],
                  r["slug"], r["domain"], r["dtype"], r["snippet"],
                  float(r["score"]), r["verified_at"], r["provenance"])
        for r in rows
    ]
    def with_evidence(selected):
        summaries={identity:summary(conn,identity) for identity in {h.document_id for h in selected}}
        return [replace(h,evidence=summaries[h.document_id]) for h in selected]
    if baseline:return with_evidence(hits),warnings
    from .retrieval import diverse,present,rerank,strong_symbols,exact_symbol_match
    symbols=strong_symbols(query)
    hits=[h for h in hits if exact_symbol_match(h.snippet,symbols)]
    hits=rerank(hits,reranker,warnings)
    hits=diverse(hits,query,k)
    if graph_depth:
        hits=_expand(conn,hits,query,k,graph_depth,project,scope,as_of,history,domain)
    return with_evidence([present(h,query) for h in hits]), warnings


def _expand(conn,hits,query,k,depth,project,scope,as_of,history,domain):
    """At most three seeds, twenty discovered nodes, eight edges per frontier."""
    from .scope import selection
    from .validity import selection as time_selection
    from .retrieval import strong_symbols,exact_symbol_match
    scopes=selection(project,scope);at,history=time_selection(as_of,history)
    seeds=hits[:min(3,max(1,k//2))]
    visited={h.document_id for h in seeds};expanded=[]
    initial={h.document_id:h for h in reversed(hits)}
    frontier=[(h.document_id,0,h.score) for h in seeds]
    predicates=['references','depends_on','extends','derived_from']
    discovered=0
    while frontier and discovered<20:
        current,level,score=frontier.pop(0)
        if level>=depth:continue
        rows=conn.execute("""
            SELECT DISTINCT d.id,d.slug,d.title,d.domain,d.dtype,d.verified_at,d.provenance
            FROM edges e JOIN documents src ON src.id=e.src_id JOIN documents dst ON dst.id=e.dst_id
            JOIN documents d ON d.id=CASE WHEN e.src_id=%s::uuid THEN e.dst_id ELSE e.src_id END
            WHERE (e.src_id=%s::uuid OR e.dst_id=%s::uuid) AND e.predicate=ANY(%s)
              AND nullif(btrim(e.evidence),'') IS NOT NULL
              AND src.status='active' AND dst.status='active'
              AND assertion_eligible(src.id,%s,%s) AND assertion_eligible(dst.id,%s,%s)
              AND (%s::boolean OR (e.valid_from<=%s AND (e.valid_to IS NULL OR e.valid_to>%s)))
              AND (%s::text[] IS NULL OR (src.project_scope=ANY(%s) AND dst.project_scope=ANY(%s)))
              AND (%s::text IS NULL OR d.domain=%s)
            ORDER BY d.slug,d.id LIMIT 8
            """,(current,current,current,predicates,at,history,at,history,history,at,at,scopes,scopes,scopes,domain,domain)).fetchall()
        for r in rows:
            identity=str(r['id'])
            if identity in visited:continue
            visited.add(identity);discovered+=1
            chunk=conn.execute('SELECT id,content FROM chunks WHERE document_id=%s ORDER BY idx,id LIMIT 1',(identity,)).fetchone()
            if identity in initial:
                expanded.append(initial[identity])
            elif chunk and exact_symbol_match(chunk['content'],strong_symbols(query)):
                expanded.append(SearchHit(identity,str(chunk['id']),r['title'],r['slug'],r['domain'],r['dtype'],
                    chunk['content'][:4000],score/(level+2),r['verified_at'],r['provenance'],graph_depth=level+1))
            frontier.append((identity,level+1,score))
            if discovered>=20:break
    promoted={h.document_id for h in seeds+expanded}
    return (seeds+expanded+[h for h in hits if h.document_id not in promoted])[:k]
