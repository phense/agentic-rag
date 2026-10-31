"""The per-session MCP server (spec §5): FastMCP over stdio, SQL and local
Ollama query inference with bounded transport/vector reuse. Each tool call
opens a short-lived role-scoped connection (writer; rag_reader when
RAG_READONLY=1, which also unregisters every write tool — the subagent
configuration). Run: python -m agentic_rag.mcp_server"""
from __future__ import annotations

import dataclasses
import json
import os
import uuid as uuidlib

from mcp.server.fastmcp import FastMCP
from pydantic import StrictBool, StrictFloat, StrictInt

from . import db, graph
from .config import load_config
from .domains import list_domains
from .pins import add_pin, unpin
from .search import search as run_search
from .store import EdgeSpec, get_document, save_document
from .query_cache import QueryCache

_QUERY_CACHE = QueryCache()


def _actor() -> str:
    from .service.context import actor
    return actor('claude')


def _readonly() -> bool:
    from .service.context import CURRENT
    request = CURRENT.get()
    if request is not None:
        return request.read_only or request.principal.readonly
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


def _readable_id(conn, id_or_slug: str) -> str | None:
    """Graph anchors: a withheld derived pattern is reported as not found."""
    doc_id = _resolve_id(conn, id_or_slug)
    if doc_id is not None:
        from .synthesis import withheld
        dtype = conn.execute("SELECT dtype FROM documents WHERE id=%s", (doc_id,)).fetchone()["dtype"]
        if withheld(conn, doc_id, dtype):
            return None
    return doc_id


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
                  project: str | None = None, scope: str | None = None, as_of: str | None = None, history: bool = False, graph_depth: int = 0, strategy: str = "auto", rerank: str = "auto", context: str = "auto",
                  temporal: str | None = None, reference: str | None = None, timezone: str | None = None,
                  view: str | None = None) -> dict:
    """Hybrid search (vector + full-text EN/DE, deterministic RRF fusion)
    over stored knowledge. Returns snippets with slug/score/verified_at —
    use memory_get(slug) for the full document. project selects that project plus
    global context; scope=global is global-only, scope=all explicitly searches all.
    Omitting both retains manual cross-project search. strategy=auto avoids
    embeddings for eligible exact selectors; hybrid retains the previous path;
    lexical explicitly uses bilingual full-text only. A verified available local
    model may reorder ambiguous auto searches; rerank=off keeps deterministic
    candidate ordering. context=off retains original representations; auto also
    uses current source-grounded contextual indices when migration015 is present.
    temporal (auto by default) interprets yesterday/gestern, last week/letzte Woche,
    next month/nächsten Monat, ISO or German full dates and explicit ranges: auto
    follows the server [temporal] configuration (off by default), prefer orders
    hits whose known event time is in the period first, filter keeps only those
    and fails on missing or ambiguous periods, off disables. reference (ISO
    timestamp with offset) and timezone (IANA name) affect interpretation only,
    never as_of/history. Applied interpretation is returned under "temporal".
    view (optional): current (= latest) hides members of applied lifecycle
    decisions; include_merged also returns duplicate/extension members (never
    replaced ones); historical returns qualified accepted past records. Each hit
    then carries evidence.lifecycle. Omitted keeps the existing default."""
    from .search import validate_strategy, validate_rerank_mode
    validate_strategy(strategy)
    validate_rerank_mode(rerank)
    if context not in ("auto", "off"):
        raise ValueError("context must be auto or off")
    cfg, conn = _connect()
    with conn:
        diagnostics = {}
        hits, warnings = run_search(conn, cfg, query, domain=domain, k=k, project=project, scope=scope, as_of=as_of, history=history, graph_depth=graph_depth, strategy=strategy, query_cache=_QUERY_CACHE, rerank_mode=rerank, context_mode=context,
                                    temporal=temporal or "auto", reference=reference, timezone=timezone, diagnostics=diagnostics,
                                    view=view)
        result = {"results": _plain(hits), "warnings": warnings}
        if "temporal" in diagnostics:
            result["temporal"] = diagnostics["temporal"]
        return result


async def memory_research(question: str, domain: str | None = None,
                          project: str | None = None, scope: str | None = None,
                          as_of: str | None = None, history: StrictBool = False,
                          provider: StrictBool = False, strategy: str = "auto",
                          steps: StrictInt = 4, calls: StrictInt = 16, seconds: StrictFloat = 30,
                          context_chars: StrictInt = 12000, min_sources: StrictInt = 2,
                          view: str | None = None) -> dict:
    """Bounded read-only multi-step evidence research. Defaults stay local and
    abstain from semantic answers. provider=true explicitly sends the redacted
    question and selected evidence to the configured Codex/Claude CLI. Returns
    exact source-backed statements, disagreements, missing evidence and resource
    usage. A dedicated rag_reader worker enforces time/cancellation boundaries
    even in authorized main sessions. Existing search remains independent.
    """
    from .research import ResearchBudget, research_async
    return await research_async(load_config(),question,domain=domain,project=project,scope=scope,
        as_of=as_of,history=history,provider=provider,strategy=strategy,min_sources=min_sources,
        budget=ResearchBudget(steps,calls,seconds,context_chars),view=view)


def memory_get(id_or_slug: str, view: str | None = None) -> dict:
    """Full document (title, body, meta, provenance, status) plus its
    incoming and outgoing typed edges. Without view this is original inspection.
    view=current resolves one hop to the canonical original (requested_id,
    canonical_id, resolution); include_merged/historical return the original with
    a lifecycle block. A canonical you cannot read is reported as unavailable."""
    from . import lifecycle
    view = lifecycle.normalize_view(view)
    cfg, conn = _connect()
    with conn:
        from .service.context import CURRENT
        if CURRENT.get() is not None:
            # Budget preflight and materialization must see the same records;
            # concurrent source-trust updates cannot enlarge a checked result.
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with lifecycle.view_scope(conn, view):
            doc = get_document(conn, id_or_slug)
            if doc is None:
                return {"error": f"not found: {id_or_slug}"}
            resolved = {"document": doc} if view is None else lifecycle.resolve_get(conn, doc, view)
        doc = resolved["document"]
        if doc is None:
            return {"document": None, "edges_out": [], "edges_in": [], "lifecycle": _plain(resolved["lifecycle"])}
        doc = dict(doc)
        edges_out = doc.pop("edges_out")
        edges_in = doc.pop("edges_in")
        out = {"document": _plain(doc), "edges_out": _plain(edges_out),
               "edges_in": _plain(edges_in)}
        if view is not None:
            out["lifecycle"] = _plain(resolved["lifecycle"])
        return out


def memory_neighbors(id_or_slug: str, depth: int = 1,
                     predicates: list[str] | None = None, project: str | None = None,
                     scope: str | None = None, as_of: str | None = None, history: bool | None = None,
                     view: str | None = None) -> dict:
    """Graph traversal: every edge within `depth` hops of the document
    (undirected), optionally filtered to specific predicates. An explicit view
    (current, latest, include_merged, historical) replaces the legacy default."""
    cfg, conn = _connect()
    with conn:
        doc_id = _readable_id(conn, id_or_slug)
        if doc_id is None:
            return {"error": f"not found: {id_or_slug}"}
        return {"edges": _plain(graph.neighbors(conn, doc_id,
                                                depth=min(depth, 3),
                                                predicates=predicates, project=project, scope=scope, as_of=as_of, history=history,
                                                view=view))}


def memory_path(from_id_or_slug: str, to_id_or_slug: str,
                max_depth: int = 4, project: str | None = None,
                scope: str | None = None, as_of: str | None = None, history: bool | None = None,
                view: str | None = None) -> dict:
    """How do X and Y relate? The shortest edge path between two documents
    (empty steps = no connection within max_depth). Optional view as in memory_neighbors."""
    cfg, conn = _connect()
    with conn:
        a = _readable_id(conn, from_id_or_slug)
        b = _readable_id(conn, to_id_or_slug)
        if a is None or b is None:
            missing = from_id_or_slug if a is None else to_id_or_slug
            return {"error": f"not found: {missing}"}
        return {"steps": _plain(graph.path(conn, a, b, max_depth=max_depth, project=project, scope=scope, as_of=as_of, history=history,
                                           view=view))}


def memory_timeline(id_or_slug: str) -> dict:
    """Every edge touching the document ordered by validity interval
    (valid_from/valid_to) — what held when."""
    cfg, conn = _connect()
    with conn:
        doc_id = _readable_id(conn, id_or_slug)
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
            actor=_actor(), mark_verified=mark_verified, project=project, scope=scope)
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
            relation=relation,project=project,scope=scope,actor=_actor()))


def memory_source_state(source_key: str, state: str, reason: str,
                        expected_version: str | None = None, id_or_slug: str | None = None) -> dict:
    """Explicit operator source trust change: active/refuted/removed, with reason.
    Retains all evidence; dependent current claims use surviving active support.
    Strict: pass the inspected source_version from memory_evidence as expected_version
    and that document as id_or_slug; a changed source is a conflict, never applied."""
    from .store import set_source_state
    cfg,conn=_connect()
    with conn:
        result=set_source_state(conn,source_key,state=state,reason=reason,actor=_actor(),
                                expected_version=expected_version,anchor=id_or_slug)
    return _plain(result)


def memory_review_claim(id_or_slug: str, state: str, reason: str, expected_version: str | None = None) -> dict:
    """Explicit operator review: confirmed/unreviewed/refuted, with reason.
    Confirm only after checking meaning and source support; this preserves inference kind.
    Strict: pass the inspected memory_evidence version as expected_version; any change
    to the claim, its spans or linked sources since then is a conflict."""
    from .store import review_claim
    from .evidence_contract import EvidenceUnavailable
    cfg,conn=_connect()
    with conn:
        doc_id=_resolve_id(conn,id_or_slug)
        if doc_id is None:
            if expected_version is not None:raise EvidenceUnavailable()
            return {'error':'document not found'}
        result=review_claim(conn,doc_id,state=state,reason=reason,actor=_actor(),expected_version=expected_version)
    return _plain(result)


def memory_evidence(id_or_slug: str, source_key: str | None = None, cursor: str | None = None,
                    limit: StrictInt = 20) -> dict:
    """Inspect a memory's evidence (contract v1): exact stored quotes, opaque source/span
    references, event time or unknown, role, completeness, source trust, claim review,
    fact lifecycle and exclusion reasons, plus the version a strict review must cite.
    Reviewed means an operator decision, never independent verification. Finite pages
    (limit<=20, next_cursor); source_key narrows to one source linked to this memory."""
    from .evidence_contract import inspect
    cfg,conn=_connect()
    with conn:
        # One snapshot: the version and the page describe the same evidence.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _plain(inspect(conn,id_or_slug,source_key=source_key,cursor=cursor,limit=limit))


def memory_evidence_history(id_or_slug: str, source_key: str | None = None, cursor: str | None = None,
                            limit: StrictInt = 20) -> dict:
    """Newest-first review/source decisions recorded since the evidence-history upgrade,
    for this memory or one source linked to it. Earlier changes remain in the audit log;
    an empty history does not mean never reviewed. Finite pages (limit<=20)."""
    from .evidence_contract import history
    cfg,conn=_connect()
    with conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _plain(history(conn,id_or_slug,source_key=source_key,cursor=cursor,limit=limit))


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
                                  actor=_actor())}


def memory_unpin(pin_id: str) -> dict:
    """Deactivate a pin. Pins are user-owned: call this ONLY on the user's
    explicit instruction."""
    cfg, conn = _connect()
    with conn:
        return {"unpinned": unpin(conn, pin_id, actor=_actor())}


def memory_context(project: str | None = None, prompt: str | None = None,
                   session_id: str | None = None) -> dict:
    """Bounded advisory context; no refresh/write. Omit prompt for startup context."""
    from .context import build
    cfg=load_config()
    with db.connect(cfg,role="reader") as conn:
        return _plain(build(conn,cfg,project=project,mode="prompt" if prompt is not None else "startup",
                            prompt=prompt,session_id=session_id,source="startup"))


def memory_summary(topic: str, project: str | None = None, domain: str | None = None,
                   history: StrictBool = False, context_chars: StrictInt = 4800) -> dict:
    """Read a local extractive thematic profile with versioned original citations.
    No refresh/write/provider call. Missing/stale summaries retain baseline search.
    history=true includes currently trusted superseded assertions with historical
    labels, but still excludes expired/future/withdrawn evidence. Project selects
    that project plus global; omission selects global only. Domains are topics,
    not user ACLs. Source/version drift withholds changed excerpts until refresh.
    """
    from .thematic import read
    cfg=load_config()
    with db.connect(cfg,role='reader') as conn:
        return _plain(read(conn,cfg,topic,project=project,domain=domain,
                           history=history,context_chars=context_chars))


def memory_entity(name: str, domain: str, project: str | None = None, scope: str | None = None,
                  attribute: str | None = None, as_of: str | None = None,
                  history: StrictBool = False, context_chars: StrictInt = 4800) -> dict:
    """Read exact scoped/domain entity facts and operator-confirmed direct aliases.
    Requires a project or explicit scope=global. No global/project mixing, provider
    call or write. Preserves original citations and stable IDs; ambiguous current
    values are withheld from context. history=true includes currently trusted
    accepted expired/superseded facts with labels; future facts stay out.
    Domains are topics, not user ACLs. Use memory_get to inspect original sources.
    """
    from .entities import read
    cfg=load_config()
    with db.connect(cfg,role='reader') as conn:
        return _plain(read(conn,name,domain=domain,project=project,scope=scope,
                           attribute=attribute,as_of=as_of,history=history,context_chars=context_chars))


def memory_entity_alias(alias: str, target: str, domain: str, evidence: dict,
                        effective_at: str, project: str | None = None, scope: str | None = None,
                        confirm: StrictBool = False) -> dict:
    """Save an evidence-backed directed alias suggestion. evidence requires
    namespace/source_id/role/quote/complete. confirm=true is explicit operator
    confirmation that both names identify the same entity; inspect original
    evidence first and never invent a user quote. Uncertain/competing links remain
    review-only. No embeddings or destructive identity union. Same known scope/domain.
    """
    from .store import save_entity_alias
    cfg,conn=_connect()
    with conn:
        return _plain(save_entity_alias(conn,cfg,alias=alias,target=target,domain=domain,evidence=evidence,
            effective_at=effective_at,project=project,scope=scope,confirm=confirm,actor=_actor()))


def memory_entity_alias_review(document_id: str, state: str, reason: str) -> dict:
    """Explicit reversible alias review: accepted or revoked with reason. Acceptance
    rechecks original confirmed span, current scope/domain and competing anchors.
    Revocation retains original facts, relation/source records and audit history.
    """
    from .store import review_entity_alias
    cfg,conn=_connect()
    with conn:
        return _plain(review_entity_alias(conn,document_id,state=state,reason=reason,actor=_actor()))


def _pattern_read(producer, **kwargs):
    cfg, conn = _connect()
    with conn:
        # One snapshot: guard, versions and citations describe the same state.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _plain(producer(conn, cfg, **kwargs))


def memory_pattern_preview(domain: str, project: str | None = None, scope: str | None = None,
                           start: str | None = None, end: str | None = None) -> dict:
    """Preview opt-in pattern synthesis for one concrete domain and project (or scope=global):
    eligible original memories, independent user events, exclusions and budgets. No provider
    call and no write. start/end bound document arrival time (ISO-8601 with timezone)."""
    from .synthesis import preview
    return _pattern_read(preview, domain=domain, project=project, scope=scope, start=start, end=end)


def memory_pattern_status(domain: str | None = None, project: str | None = None, scope: str | None = None,
                          limit: StrictInt = 20) -> dict:
    """Visible pattern policies, open backfills and newest runs (state, code, counts, provider
    calls). No prompts, quotes or raw provider errors."""
    from .synthesis import status
    return _pattern_read(status, domain=domain, project=project, scope=scope, limit=limit)


def memory_patterns(domain: str, project: str | None = None, scope: str | None = None,
                    limit: StrictInt = 20, cursor: str | None = None) -> dict:
    """List current pattern suggestions of one concrete scope. Patterns are reviewable
    inferences, not user statements; stale or inaccessible ones are omitted."""
    from .synthesis import patterns
    return _pattern_read(patterns, domain=domain, project=project, scope=scope, limit=limit, cursor=cursor)


def memory_pattern(id_or_slug: str) -> dict:
    """Inspect one current pattern: label, statement, model confidence, review state and
    exact original citations (reference, source_version, original id/version). Drill down
    with memory_evidence(original id, source_key). Withheld patterns are unavailable."""
    from .synthesis import inspect
    cfg, conn = _connect()
    with conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _plain(inspect(conn, id_or_slug))


def memory_pattern_policy(domain: str, enabled: StrictBool, reason: str, project: str | None = None,
                          scope: str | None = None, interval_seconds: StrictInt = 86400) -> dict:
    """Operator opt-in/opt-out of pattern synthesis for one concrete domain and project (or
    scope=global). Enabling records the server time as forward boundary; earlier memories
    need an explicit backfill. Disabling withholds existing patterns, never deletes."""
    from .store import set_synthesis_policy
    cfg, conn = _connect()
    with conn:
        return _plain(set_synthesis_policy(conn, cfg, domain=domain, enabled=enabled, reason=reason, project=project,
                                           scope=scope, interval_seconds=interval_seconds, actor=_actor()))


def memory_pattern_backfill(domain: str, start: str, end: str, reason: str, project: str | None = None,
                            scope: str | None = None, max_batches: StrictInt = 1) -> dict:
    """Request explicit bounded history analysis for an enabled policy: arrival window
    [start,end) before its forward boundary, at most 366 days and 1-10 batches."""
    from .store import request_synthesis_backfill
    cfg, conn = _connect()
    with conn:
        return _plain(request_synthesis_backfill(conn, cfg, domain=domain, start=start, end=end, reason=reason,
                                                 project=project, scope=scope, max_batches=max_batches, actor=_actor()))


def memory_pattern_recover(run_id: str, reason: str) -> dict:
    """Re-queue a parked accepted pattern run; reuses its stored output (no provider call)."""
    from .store import recover_synthesis_run
    cfg, conn = _connect()
    with conn:
        return _plain(recover_synthesis_run(conn, cfg, run_id, reason=reason, actor=_actor()))


def _lifecycle_read(producer, *args, **kwargs):
    cfg, conn = _connect()
    with conn:
        # One snapshot: versions, relationships and pages describe the same state.
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return _plain(producer(conn, *args, **kwargs))


def memory_lifecycle_preview(member: str, target: str, operation: str | None = None) -> dict:
    """Preview a lifecycle decision for two originals (id or slug): member is hidden,
    target is the canonical. Classifies exact_duplicate (structural proof: identical
    title, body, dtype), and for a requested semantic_duplicate, extension,
    replacement (proven event order only) or contradiction states what is proven
    versus operator judgement. Returns both lv1 versions to pass to apply. No write,
    no provider call. Missing and inaccessible documents both return not_found."""
    from .lifecycle import preview
    return _lifecycle_read(preview, member, target, operation=operation)


def memory_lifecycle(id_or_slug: str, history: StrictBool = False, cursor: str | None = None,
                     limit: StrictInt = 20) -> dict:
    """Explain one original: lifecycle decisions where it is member or canonical
    (relationship hiding/stale/target_unavailable/replaced/contested/corrected),
    legacy archived duplicates and immutable-assertion supersession. history=true
    adds the append-only event page (limit 1-100, opaque cursor)."""
    from .lifecycle import detail
    return _lifecycle_read(detail, id_or_slug, history=history, cursor=cursor, limit=limit)


def memory_lifecycle_apply(member: str, target: str, operation: str, expected_member_version: str,
                           expected_target_version: str, reason: str, reviewed: StrictBool = False,
                           request_key: str | None = None) -> dict:
    """Apply one previewed lifecycle decision through the audited gateway. Pass the
    lv1 versions from memory_lifecycle_preview; a changed document returns
    stale_version. semantic_duplicate, extension and replacement need reviewed=true
    (operator judgement). Originals, sources and evidence are never changed; the
    same request returns the existing decision, a reused request_key with another
    payload returns replay_mismatch."""
    from .store import apply_lifecycle
    cfg, conn = _connect()
    with conn:
        return _plain(apply_lifecycle(conn, cfg, member=member, target=target, operation=operation,
                                      expected_member_version=expected_member_version,
                                      expected_target_version=expected_target_version, reason=reason,
                                      reviewed=reviewed, request_key=request_key, actor=_actor()))


def memory_lifecycle_correct(decision_id: str, expected_revision: StrictInt, reason: str,
                             request_key: str | None = None) -> dict:
    """Correct (undo) one lifecycle decision. expected_revision is the decision's
    revision from memory_lifecycle. Only this decision changes state; refutation,
    expiry, withdrawal and other decisions stay as they are."""
    from .store import correct_lifecycle
    cfg, conn = _connect()
    with conn:
        return _plain(correct_lifecycle(conn, cfg, decision_id=decision_id, expected_revision=expected_revision,
                                        reason=reason, request_key=request_key, actor=_actor()))


READ_TOOLS = (memory_entity, memory_context, memory_summary, memory_domains, memory_search, memory_research, memory_get, memory_neighbors,
              memory_path, memory_timeline, memory_evidence, memory_evidence_history,
              memory_pattern_preview, memory_pattern_status, memory_patterns, memory_pattern,
              memory_lifecycle_preview, memory_lifecycle)
WRITE_TOOLS = (memory_entity_alias, memory_entity_alias_review, memory_save, memory_assert, memory_source_state, memory_review_claim, memory_pin, memory_unpin,
               memory_pattern_policy, memory_pattern_backfill, memory_pattern_recover,
               memory_lifecycle_apply, memory_lifecycle_correct)


# Optional arguments added after protocol1. A client omits them unless the caller
# set them, so services that predate them keep accepting otherwise valid calls.
ADDITIVE_ARGUMENTS = {"memory_search": ("temporal", "reference", "timezone", "view"),
                      "memory_research": ("view",), "memory_get": ("view",),
                      "memory_neighbors": ("view",), "memory_path": ("view",)}


def wire_arguments(name: str, arguments: dict) -> dict:
    optional = ADDITIVE_ARGUMENTS.get(name, ())
    return {key: value for key, value in arguments.items() if not (key in optional and value is None)}


def tool_names(readonly: bool) -> list[str]:
    fns = list(READ_TOOLS) + ([] if readonly else list(WRITE_TOOLS))
    return [f.__name__ for f in fns]


def build_server(readonly: bool) -> FastMCP:
    from .config import load_config as current_config
    cfg=current_config()
    def tool(fn):
        if cfg.service_mode!='client':return fn
        import asyncio
        from functools import wraps
        import inspect
        from typing import get_type_hints
        @wraps(fn)
        async def proxy(**arguments):
            from .service.client import RemoteClient,RemoteError
            def call():
                with RemoteClient(cfg) as client:return client.invoke(fn.__name__,wire_arguments(fn.__name__,arguments))
            try:return await asyncio.to_thread(call)
            except RemoteError as exc:raise ValueError(exc.code) from None
        hints=get_type_hints(fn)
        proxy.__signature__=inspect.signature(fn).replace(parameters=[p.replace(annotation=hints.get(p.name,p.annotation)) for p in inspect.signature(fn).parameters.values()],return_annotation=dict)
        return proxy
    server = FastMCP("agentic-rag")
    for fn in READ_TOOLS:
        server.add_tool(tool(fn))
    if not readonly:
        for fn in WRITE_TOOLS:
            server.add_tool(tool(fn))
    return server


def main() -> None:
    build_server(_readonly()).run()


if __name__ == "__main__":
    main()
