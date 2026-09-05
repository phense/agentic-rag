"""Thin wrappers over the SQL graph functions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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


def neighbors(conn, doc_id: str, depth: int = 1,
              predicates: list[str] | None = None, *,
              project: str | None = None, scope: str | None = None) -> list[EdgeHop]:
    from .scope import selection
    scopes = selection(project, scope)
    rows = conn.execute(
        "SELECT * FROM graph_neighbors_scoped(%s, %s, %s, %s)",
        (doc_id, depth, predicates, scopes),
    ).fetchall()
    return [
        EdgeHop(str(r["edge_id"]), str(r["src_id"]), str(r["dst_id"]),
                r["predicate"], r["evidence"], r["confidence"], r["depth"])
        for r in rows
    ]


def path(conn, from_id: str, to_id: str, max_depth: int = 4, *,
         project: str | None = None, scope: str | None = None) -> list[PathStep]:
    from .scope import selection
    scopes = selection(project, scope)
    rows = conn.execute(
        "SELECT p.step, p.doc_id, p.via_predicate, d.slug, d.title"
        " FROM graph_path_scoped(%s, %s, %s, %s) p JOIN documents d ON d.id = p.doc_id"
        " ORDER BY p.step",
        (from_id, to_id, max_depth, scopes),
    ).fetchall()
    return [
        PathStep(r["step"], str(r["doc_id"]), r["slug"], r["title"],
                 r["via_predicate"])
        for r in rows
    ]


def timeline(conn, doc_id: str) -> list[TimelineEdge]:
    rows = conn.execute(
        "SELECT * FROM graph_timeline(%s)", (doc_id,)
    ).fetchall()
    return [
        TimelineEdge(str(r["edge_id"]), r["src_slug"], r["dst_slug"],
                     r["predicate"], r["valid_from"], r["valid_to"])
        for r in rows
    ]
