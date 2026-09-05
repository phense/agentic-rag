"""Hybrid search wrapper: embed the query (fail-open), call hybrid_search()."""
from __future__ import annotations

from dataclasses import dataclass, field
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


def search(
    conn, cfg: Config, query: str, domain: str | None = None, k: int = 8,
    *, project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool = False
) -> tuple[list[SearchHit], list[str]]:
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
    rows = conn.execute(
        "SELECT * FROM hybrid_search_temporal(%s, %s::halfvec, %s, %s, %s, %s, %s)",
        (query, qvec, domain, k, scopes, at, history),
    ).fetchall()
    from .evidence import summary
    hits = [
        SearchHit(str(r["document_id"]), str(r["chunk_id"]), r["title"],
                  r["slug"], r["domain"], r["dtype"], r["snippet"],
                  float(r["score"]), r["verified_at"], r["provenance"],summary(conn,str(r["document_id"])))
        for r in rows
    ]
    return hits, warnings
