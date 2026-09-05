"""The write gateway: every content write passes through save_document.

Guarantees: secret stripping, slug uniqueness, chunk regeneration, dangling-edge
resolution, audit row, single transaction. Fail-open on embeddings only.
"""
from __future__ import annotations

import json
import uuid as uuidlib
from dataclasses import dataclass, field

from .chunker import chunk_markdown, slugify
from .config import Config
from .embed import embed_texts, try_embed_texts, vec_literal
from .secrets import strip_secrets, strip_secrets_json


@dataclass(frozen=True)
class EdgeSpec:
    predicate: str
    dst_slug: str
    evidence: str | None = None
    confidence: str | None = None


# spec §4 vocabulary for edges.created_by: migration | mining | manual | claude
_CREATED_BY = {"cli": "manual"}


@dataclass(frozen=True)
class SaveResult:
    doc_id: str
    slug: str
    created: bool
    n_chunks: int
    n_edges: int
    edges_resolved: int
    redactions: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeInfo:
    predicate: str
    peer_slug: str      # the OTHER endpoint: destination for "out", source for "in"
    peer_id: str | None
    direction: str  # "out" | "in"
    evidence: str | None
    confidence: str | None


def _unique_slug(conn, base: str) -> str:
    slug, n = base, 1
    while conn.execute(
        "SELECT 1 FROM documents WHERE slug = %s", (slug,)
    ).fetchone():
        n += 1
        slug = f"{base}-{n}"
    return slug


def save_document(
    conn,
    cfg: Config,
    *,
    title: str,
    body: str,
    domain: str,
    dtype: str,
    slug: str | None = None,
    meta: dict | None = None,
    provenance: dict | None = None,
    edges: list[EdgeSpec] | None = None,
    doc_id: str | None = None,
    actor: str = "cli",
    mark_verified: bool = False,
    status: str | None = None,
    commit: bool = True,
) -> SaveResult:
    # commit=False lets a bounded mining batch own the outer transaction;
    # the caller must commit or roll back all its effects together.
    # status=None means: 'active' on create, keep current status on update
    if status not in (None, "active", "archived"):
        raise ValueError(f"status must be 'active' or 'archived', not {status!r}"
                         " (refutation goes through curation)")
    warnings: list[str] = []
    title, r1 = strip_secrets(title)
    body, r2 = strip_secrets(body)
    # HARD gate (Plan 1 final review): meta/provenance carry transcript text
    # once mining exists — they must pass the secret gateway like title/body
    meta, r3 = strip_secrets_json(meta or {})
    provenance, r4 = strip_secrets_json(provenance or {})
    redactions = r1 + r2 + r3 + r4
    try:
        return _save_txn(conn, cfg, title=title, body=body, domain=domain,
                         dtype=dtype, slug=slug, meta=meta,
                         provenance=provenance, edges=edges, doc_id=doc_id,
                         actor=actor, redactions=redactions,
                         warnings=warnings, mark_verified=mark_verified,
                         status=status, commit=commit)
    except Exception:
        # never leave a long-lived connection (MCP session) in an aborted txn
        if commit:
            conn.rollback()
        raise


def _save_txn(
    conn, cfg, *, title, body, domain, dtype, slug, meta, provenance,
    edges, doc_id, actor, redactions, warnings, mark_verified, status, commit=True,
) -> SaveResult:
    if not conn.execute(
        "SELECT 1 FROM domains WHERE name = %s", (domain,)
    ).fetchone():
        raise ValueError(f"unknown domain: {domain} — create it first with"
                         f" 'rag domain add {domain}'")

    created = doc_id is None
    if created:
        the_slug = slug or _unique_slug(conn, slugify(title))
        row = conn.execute(
            "INSERT INTO documents(slug, domain, dtype, title, body, meta, provenance, status)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (the_slug, domain, dtype, title, body,
             json.dumps(meta or {}), json.dumps(provenance or {}),
             status or "active"),
        ).fetchone()
        doc_id = str(row["id"])
    else:
        row = conn.execute(
            "UPDATE documents SET title=%s, body=%s, domain=%s, dtype=%s,"
            " status = COALESCE(%s::text, status),"
            " meta = meta || %s::jsonb, provenance = provenance || %s::jsonb"
            " WHERE id = %s RETURNING slug",
            (title, body, domain, dtype, status, json.dumps(meta or {}),
             json.dumps(provenance or {}), doc_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"no such document: {doc_id}")
        the_slug = row["slug"]

    if mark_verified:
        # spec §5.3: after user corrections Claude updates the document and
        # stamps verified_at — through the gateway, never a raw UPDATE
        conn.execute(
            "UPDATE documents SET verified_at = now() WHERE id = %s",
            (doc_id,),
        )

    # chunks: swapped atomically via SECURITY DEFINER fn (writer has no DELETE)
    chunks = chunk_markdown(f"# {title}\n\n{body}")
    vecs = try_embed_texts(chunks, cfg) if chunks else []
    if chunks and vecs is None:
        warnings.append("embedding unavailable — stored without vectors, queued retry")
        conn.execute(
            "INSERT INTO mining_queue(kind, payload) VALUES ('embed', %s)",
            (json.dumps({"document_id": doc_id}),),
        )
        vecs = [None] * len(chunks)
    literals = [vec_literal(v) if v else None for v in vecs]
    conn.execute(
        "SELECT replace_chunks(%s, %s, %s)", (doc_id, chunks, literals)
    )

    # edges out of this document (upsert on src+dst_slug+predicate).
    # COALESCE: a re-save without evidence must never clobber stored evidence —
    # the writer role cannot DELETE edges, so this UPDATE is the only path by
    # which edge metadata could be destroyed. Evidence text passes through the
    # secret gateway like title/body (mining quotes come from transcripts).
    n_edges = 0
    for e in edges or []:
        evidence = e.evidence
        if evidence:
            evidence, r3 = strip_secrets(evidence)
            redactions += r3
        dst = conn.execute(
            "SELECT id FROM documents WHERE slug = %s", (e.dst_slug,)
        ).fetchone()
        conn.execute(
            "INSERT INTO edges(src_id, dst_id, dst_slug, predicate, evidence,"
            " confidence, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (src_id, dst_slug, predicate) DO UPDATE"
            " SET evidence = COALESCE(EXCLUDED.evidence, edges.evidence),"
            " confidence = COALESCE(EXCLUDED.confidence, edges.confidence)",
            (doc_id, dst["id"] if dst else None, e.dst_slug, e.predicate,
             evidence, e.confidence, _CREATED_BY.get(actor, actor)),
        )
        n_edges += 1

    # resolve edges elsewhere that dangled on this slug
    resolved = conn.execute(
        "UPDATE edges SET dst_id = %s WHERE dst_slug = %s AND dst_id IS NULL"
        " AND src_id <> %s",
        (doc_id, the_slug, doc_id),
    ).rowcount

    conn.execute(
        "INSERT INTO audit_log(actor, op, document_id, summary) VALUES (%s,%s,%s,%s)",
        (actor, "save_document", doc_id,
         f"{'created' if created else 'updated'} '{the_slug}' ({domain}/{dtype}), "
         f"{len(chunks)} chunks, {n_edges} edges, {redactions} redactions"),
    )
    if commit:
        conn.commit()
    return SaveResult(doc_id, the_slug, created, len(chunks), n_edges,
                      resolved, redactions, warnings)


def set_domain(conn, doc_id: str, domain: str, actor: str = "cli") -> None:
    """Move a document to another domain. The one gateway write that must
    not re-chunk/re-embed: domain lives on documents, not chunks."""
    try:
        if not conn.execute("SELECT 1 FROM domains WHERE name = %s",
                            (domain,)).fetchone():
            raise ValueError(f"unknown domain: {domain} — create it first with"
                             f" 'rag domain add {domain}'")
        row = conn.execute(
            "UPDATE documents SET domain = %s WHERE id = %s RETURNING slug",
            (domain, doc_id)).fetchone()
        if row is None:
            raise ValueError(f"no such document: {doc_id}")
        conn.execute(
            "INSERT INTO audit_log(actor, op, document_id, summary)"
            " VALUES (%s, %s, %s, %s)",
            (actor, "set_domain", doc_id, f"{row['slug']} → {domain}"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_document(conn, id_or_slug: str) -> dict | None:
    try:
        uuidlib.UUID(id_or_slug)
        cond, val = "id = %s", id_or_slug
    except ValueError:
        cond, val = "slug = %s", id_or_slug
    doc = conn.execute(
        f"SELECT * FROM documents WHERE {cond}", (val,)
    ).fetchone()
    if doc is None:
        return None
    out = [
        EdgeInfo(r["predicate"], r["dst_slug"], _s(r["dst_id"]), "out",
                 r["evidence"], r["confidence"])
        for r in conn.execute(
            "SELECT * FROM edges WHERE src_id = %s ORDER BY predicate, dst_slug",
            (doc["id"],)).fetchall()
    ]
    incoming = [
        # peer of an in-edge is its SOURCE document
        EdgeInfo(r["predicate"], r["slug"], _s(r["src_id"]), "in",
                 r["evidence"], r["confidence"])
        for r in conn.execute(
            "SELECT e.*, d.slug FROM edges e JOIN documents d ON d.id = e.src_id"
            " WHERE e.dst_id = %s ORDER BY e.predicate, d.slug",
            (doc["id"],)).fetchall()
    ]
    d = dict(doc)
    d["edges_out"], d["edges_in"] = out, incoming
    return d


def _s(v) -> str | None:
    return str(v) if v is not None else None


def reembed_document(conn, cfg: Config, doc_id: str) -> int:
    """Re-chunk and re-embed ONE document (the queued-embed retry path).
    Raises EmbedError when Ollama is unavailable — the caller (worker queue)
    owns retry/backoff; this function must not swallow the failure."""
    doc = conn.execute(
        "SELECT title, body FROM documents WHERE id = %s", (doc_id,)
    ).fetchone()
    if doc is None:
        raise ValueError(f"no such document: {doc_id}")
    chunks = chunk_markdown(f"# {doc['title']}\n\n{doc['body']}")
    vecs = embed_texts(chunks, cfg) if chunks else []
    literals = [vec_literal(v) for v in vecs]
    conn.execute("SELECT replace_chunks(%s, %s, %s)",
                 (doc_id, chunks, literals))
    conn.execute(
        "INSERT INTO audit_log(actor, op, document_id, summary)"
        " VALUES ('mining', 'reembed', %s, %s)",
        (doc_id, f"re-embedded {len(chunks)} chunks"))
    conn.commit()
    return len(chunks)
