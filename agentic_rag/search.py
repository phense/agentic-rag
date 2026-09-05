"""Hybrid search wrapper: embed the query (fail-open), call hybrid_search()."""
from __future__ import annotations

from dataclasses import dataclass
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


def search(
    conn, cfg: Config, query: str, domain: str | None = None, k: int = 8,
    *, project: str | None = None, scope: str | None = None
) -> tuple[list[SearchHit], list[str]]:
    from .scope import selection
    scopes = selection(project, scope)
    warnings: list[str] = []
    vecs = try_embed_texts([query], cfg)
    if vecs is None:
        warnings.append("embedding unavailable — full-text search only")
        qvec = None
    else:
        qvec = vec_literal(vecs[0])
    rows = conn.execute(
        "SELECT * FROM hybrid_search_scoped(%s, %s::halfvec, %s, %s, %s)",
        (query, qvec, domain, k, scopes),
    ).fetchall()
    hits = [
        SearchHit(str(r["document_id"]), str(r["chunk_id"]), r["title"],
                  r["slug"], r["domain"], r["dtype"], r["snippet"],
                  float(r["score"]), r["verified_at"], r["provenance"])
        for r in rows
    ]
    return hits, warnings
