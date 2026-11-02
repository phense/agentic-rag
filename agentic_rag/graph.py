"""Thin wrappers over the SQL graph functions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from .service.read_limits import rows as bounded_rows


@dataclass(frozen=True)
class EdgeHop:
    edge_id: str
    src_id: str
    dst_id: str
    predicate: str
    evidence: str | None
    confidence: str | None
    depth: int


@dataclass(frozen=True)
class PathStep:
    step: int
    doc_id: str
    slug: str
    title: str
    via_predicate: str | None


@dataclass(frozen=True)
class TimelineEdge:
    edge_id: str
    src_slug: str
    dst_slug: str
    predicate: str
    valid_from: datetime
    valid_to: datetime | None


def _time(project, scope, as_of, history, view):
    """Omitted view keeps the graph default (legacy history when unscoped and
    untimed). An explicit view selects lifecycle membership instead."""
    from .lifecycle import normalize_view, time_selection
    view = normalize_view(view, history=history, as_of=as_of)
    if view is None and history is None:
        history = project is None and scope is None and as_of is None
    at, history = time_selection(view, as_of, bool(history))
    return at, history, view


def neighbors(conn, doc_id: str, depth: int = 1,
              predicates: list[str] | None = None, *,
              project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool | None = None,
              view: str | None = None) -> list[EdgeHop]:
    from .scope import selection
    scopes = selection(project, scope)
    at, history, view = _time(project, scope, as_of, history, view)
    from .lifecycle import view_scope
    with view_scope(conn, view):
        rows = bounded_rows(conn,
            "SELECT * FROM graph_neighbors_temporal(%s, %s, %s, %s, %s, %s)",
            (doc_id, depth, predicates, scopes, at, history),
        )
    return [
        EdgeHop(str(r["edge_id"]), str(r["src_id"]), str(r["dst_id"]),
                r["predicate"], r["evidence"], r["confidence"], r["depth"])
        for r in rows
    ]


def path(conn, from_id: str, to_id: str, max_depth: int = 4, *,
         project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool | None = None,
         view: str | None = None) -> list[PathStep]:
    from .scope import selection
    scopes = selection(project, scope)
    at, history, view = _time(project, scope, as_of, history, view)
    from .lifecycle import view_scope
    with view_scope(conn, view):
        rows = bounded_rows(conn,
            "SELECT p.step, p.doc_id, p.via_predicate, d.slug, d.title"
            " FROM graph_path_temporal(%s, %s, %s, %s, %s, %s) p JOIN documents d ON d.id = p.doc_id"
            " ORDER BY p.step",
            (from_id, to_id, max_depth, scopes, at, history),
        )
    return [
        PathStep(r["step"], str(r["doc_id"]), r["slug"], r["title"],
                 r["via_predicate"])
        for r in rows
    ]


def timeline(conn, doc_id: str) -> list[TimelineEdge]:
    rows = bounded_rows(conn,
        "SELECT * FROM graph_timeline(%s)", (doc_id,)
    )
    return [
        TimelineEdge(str(r["edge_id"]), r["src_slug"], r["dst_slug"],
                     r["predicate"], r["valid_from"], r["valid_to"])
        for r in rows
    ]


def research_neighbors(conn, doc_id, *, domain, scopes, at, history, limit=8):
    """Bounded one-hop originals for research, with BOTH endpoints gated before
    LIMIT. Unlike general recursive graph tools this also applies domain selection.
    Invoker-only: no new privilege or SQL function is introduced.
    """
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('research neighbor limit must be between 1 and 8')
    return conn.execute('''SELECT e.id edge_id,e.predicate,left(e.evidence,600) edge_evidence,e.confidence,
               d.id,d.title,d.slug,d.domain,d.dtype,d.verified_at,d.provenance,e.src_id,e.dst_id
               FROM edges e JOIN documents src ON src.id=e.src_id JOIN documents dst ON dst.id=e.dst_id
               JOIN documents d ON d.id=CASE WHEN e.src_id=%s::uuid THEN e.dst_id ELSE e.src_id END
               WHERE (e.src_id=%s::uuid OR e.dst_id=%s::uuid) AND src.id<>dst.id
               AND e.predicate=ANY(%s) AND nullif(btrim(e.evidence),'') IS NOT NULL
               AND src.status='active' AND dst.status='active'
               AND assertion_eligible(src.id,%s,%s) AND assertion_eligible(dst.id,%s,%s)
               AND (%s OR (e.valid_from<=%s AND (e.valid_to IS NULL OR e.valid_to>%s)))
               AND (%s::text IS NULL OR (src.domain=%s AND dst.domain=%s))
               AND (%s::text[] IS NULL OR (src.project_scope=ANY(%s) AND dst.project_scope=ANY(%s)))
               ORDER BY e.predicate,d.slug,d.id,e.id LIMIT %s''',
        (doc_id,doc_id,doc_id,['references','depends_on','extends','derived_from','contradicts','contrasts_with'],
         at,history,at,history,history,at,at,domain,domain,domain,scopes,scopes,scopes,limit+1)).fetchall()
