"""The per-session MCP server (spec §5): FastMCP over stdio, SQL + one
Ollama HTTP call (search) only — never a model in-process. Each tool call
opens a short-lived role-scoped connection (writer; rag_reader when
RAG_READONLY=1, which also unregisters every write tool — the subagent
configuration). Run: python -m agentic_rag.mcp_server"""
from __future__ import annotations

import dataclasses
import json
import os
import uuid as uuidlib

from mcp.server.fastmcp import FastMCP

from . import db, graph
from .config import load_config
from .domains import list_domains
from .pins import add_pin, unpin
from .search import search as run_search
from .store import EdgeSpec, get_document, save_document


def _readonly() -> bool:
    return os.environ.get("RAG_READONLY", "").strip() == "1"


def _connect():
    cfg = load_config()
    role = "reader" if _readonly() else "writer"
    return cfg, db.connect(cfg, role=role)


def _plain(obj):
    """Dataclasses (at ANY nesting depth — the tools return LISTS of
    dataclasses)/UUID/datetime → JSON-safe structures. The conversion must
    live in the json default hook: a top-level-only asdict would leave list
    elements to default=str, turning every hit into its repr string."""
    def _default(o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return str(o)  # UUID, datetime
    return json.loads(json.dumps(obj, default=_default))


def _resolve_id(conn, id_or_slug: str) -> str | None:
    """Resolve slug OR uuid to an EXISTING document id. The uuid branch
    must also hit the table: a well-formed-but-nonexistent uuid otherwise
    yields empty edges/steps — indistinguishable from 'no relations' —
    instead of the not-found error the tool contract promises."""
    try:
        uuidlib.UUID(id_or_slug)
        cond = "id = %s"
    except ValueError:
        cond = "slug = %s"
    row = conn.execute(f"SELECT id FROM documents WHERE {cond}",
                       (id_or_slug,)).fetchone()
    return str(row["id"]) if row else None


# ---------------------------------------------------------------- read tools

def memory_domains() -> dict:
    """The knowledge map: every domain with its description and document
    count — check this first to know where to search."""
    cfg, conn = _connect()
    with conn:
        return {"domains": _plain(list_domains(conn))}


def memory_search(query: str, domain: str | None = None, k: int = 8,
                  project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool = False) -> dict:
    """Hybrid search (vector + full-text EN/DE, deterministic RRF fusion)
    over stored knowledge. Returns snippets with slug/score/verified_at —
    use memory_get(slug) for the full document. project selects that project plus
    global context; scope=global is global-only, scope=all explicitly searches all.
    Omitting both retains manual cross-project search."""
    cfg, conn = _connect()
    with conn:
        hits, warnings = run_search(conn, cfg, query, domain=domain, k=k, project=project, scope=scope, as_of=as_of, history=history)
        return {"results": _plain(hits), "warnings": warnings}


def memory_get(id_or_slug: str) -> dict:
    """Full document (title, body, meta, provenance, status) plus its
    incoming and outgoing typed edges."""
    cfg, conn = _connect()
    with conn:
        doc = get_document(conn, id_or_slug)
        if doc is None:
            return {"error": f"not found: {id_or_slug}"}
        doc = dict(doc)
        edges_out = doc.pop("edges_out")
        edges_in = doc.pop("edges_in")
        return {"document": _plain(doc), "edges_out": _plain(edges_out),
                "edges_in": _plain(edges_in)}


def memory_neighbors(id_or_slug: str, depth: int = 1,
                     predicates: list[str] | None = None, project: str | None = None,
                     scope: str | None = None, as_of: str | None = None, history: bool | None = None) -> dict:
    """Graph traversal: every edge within `depth` hops of the document
    (undirected), optionally filtered to specific predicates."""
    cfg, conn = _connect()
    with conn:
        doc_id = _resolve_id(conn, id_or_slug)
        if doc_id is None:
            return {"error": f"not found: {id_or_slug}"}
        return {"edges": _plain(graph.neighbors(conn, doc_id,
                                                depth=min(depth, 3),
                                                predicates=predicates, project=project, scope=scope, as_of=as_of, history=history))}


def memory_path(from_id_or_slug: str, to_id_or_slug: str,
                max_depth: int = 4, project: str | None = None,
                scope: str | None = None, as_of: str | None = None, history: bool | None = None) -> dict:
    """How do X and Y relate? The shortest edge path between two documents
    (empty steps = no connection within max_depth)."""
    cfg, conn = _connect()
    with conn:
        a = _resolve_id(conn, from_id_or_slug)
        b = _resolve_id(conn, to_id_or_slug)
        if a is None or b is None:
            missing = from_id_or_slug if a is None else to_id_or_slug
            return {"error": f"not found: {missing}"}
        return {"steps": _plain(graph.path(conn, a, b, max_depth=max_depth, project=project, scope=scope, as_of=as_of, history=history))}


def memory_timeline(id_or_slug: str) -> dict:
    """Every edge touching the document ordered by validity interval
    (valid_from/valid_to) — what held when."""
    cfg, conn = _connect()
    with conn:
        doc_id = _resolve_id(conn, id_or_slug)
        if doc_id is None:
            return {"error": f"not found: {id_or_slug}"}
        return {"edges": _plain(graph.timeline(conn, doc_id))}


# --------------------------------------------------------------- write tools

def memory_save(title: str, body: str, domain: str, dtype: str = "memory",
                slug: str | None = None, doc_id: str | None = None,
                edges: list[dict] | None = None,
                mark_verified: bool = False, project: str | None = None,
                scope: str | None = None) -> dict:
    """Save knowledge through the write gateway (secret-strip, chunk, embed,
    edge resolution, audit). Pass doc_id to UPDATE an existing document.
    IMPORTANT: when the user corrects or confirms stored knowledge, update
    the document and set mark_verified=true so verified_at is stamped.
    edges: [{predicate, dst_slug, evidence?, confidence?}] with predicate in
    the fixed vocabulary (references, extends, depends_on, complements,
    contrasts_with, informs, part_of, derived_from, supersedes, contradicts,
    duplicate_of)."""
    cfg, conn = _connect()
    with conn:
        specs = [
            EdgeSpec(
                str(e["predicate"]), str(e["dst_slug"]),
                # "" must become None (evidence COALESCE guard)
                evidence=(str(e["evidence"]).strip() or None)
                if e.get("evidence") else None,
                confidence=e.get("confidence") or None)
            for e in (edges or []) if e.get("predicate") and e.get("dst_slug")
        ]
        res = save_document(
            conn, cfg, title=title, body=body, domain=domain, dtype=dtype,
            slug=slug, doc_id=doc_id, edges=specs,
            provenance={"origin": "manual", "via": "mcp"},
            actor="claude", mark_verified=mark_verified, project=project, scope=scope)
        return _plain(res)


def memory_assert(entity: str, attribute: str, value: str, domain: str,
                  evidence: dict, event_at: str | None = None, expires_at: str | None = None,
                  relation: str = 'assertion', project: str | None = None,
                  scope: str | None = None) -> dict:
    """Save one immutable fact with source_id/role/quote evidence and timezone-aware
    event time. replacement explicitly supersedes older values of the same scoped
    entity/attribute; extension coexists. Unsupported evidence is retained for review.
    Manual evidence is an operator attestation; never invent user quotes."""
    from .store import save_assertion
    cfg, conn = _connect()
    with conn:
        return _plain(save_assertion(conn,cfg,entity=entity,attribute=attribute,value=value,
            domain=domain,evidence=evidence,event_at=event_at,expires_at=expires_at,
            relation=relation,project=project,scope=scope,actor='claude'))


def memory_source_state(source_key: str, state: str, reason: str) -> dict:
    """Explicit operator source trust change: active/refuted/removed, with reason.
    Retains all evidence; dependent current claims use surviving active support."""
    from .store import set_source_state
    cfg,conn=_connect()
    with conn:set_source_state(conn,source_key,state=state,reason=reason,actor='claude')
    return {'source_key':source_key,'state':state}


def memory_review_claim(id_or_slug: str, state: str, reason: str) -> dict:
    """Explicit operator review: confirmed/unreviewed/refuted, with reason.
    Confirm only after checking meaning and source support; this preserves inference kind."""
    from .store import review_claim
    cfg,conn=_connect()
    with conn:
        doc_id=_resolve_id(conn,id_or_slug)
        if doc_id is None:return {'error':'document not found'}
        review_claim(conn,doc_id,state=state,reason=reason,actor='claude')
    return {'document_id':doc_id,'review_state':state}


def memory_pin(body: str | None = None, document_id: str | None = None,
               scope: str = "global", priority: int = 100) -> dict:
    """Pin a standing rule (or a document) so it is injected into EVERY
    session start. Pins are user-owned: call this ONLY on the user's
    explicit instruction, never on your own initiative. scope: 'global',
    a domain name, or an absolute project path."""
    cfg, conn = _connect()
    with conn:
        return {"pin_id": add_pin(conn, body=body, document_id=document_id,
                                  scope=scope, priority=priority,
                                  actor="claude")}


def memory_unpin(pin_id: str) -> dict:
    """Deactivate a pin. Pins are user-owned: call this ONLY on the user's
    explicit instruction."""
    cfg, conn = _connect()
    with conn:
        return {"unpinned": unpin(conn, pin_id, actor="claude")}


READ_TOOLS = (memory_domains, memory_search, memory_get, memory_neighbors,
              memory_path, memory_timeline)
WRITE_TOOLS = (memory_save, memory_assert, memory_source_state, memory_review_claim, memory_pin, memory_unpin)


def tool_names(readonly: bool) -> list[str]:
    fns = list(READ_TOOLS) + ([] if readonly else list(WRITE_TOOLS))
    return [f.__name__ for f in fns]


def build_server(readonly: bool) -> FastMCP:
    server = FastMCP("agentic-rag")
    for fn in READ_TOOLS:
        server.add_tool(fn)
    if not readonly:
        for fn in WRITE_TOOLS:
            server.add_tool(fn)
    return server


def main() -> None:
    build_server(_readonly()).run()


if __name__ == "__main__":
    main()
