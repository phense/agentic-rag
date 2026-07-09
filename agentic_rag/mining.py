"""Session mining (spec §6): ONE structured Haiku call per queue job, then
write-through the gateway. Grounded-or-dropped parsing: the schema constrains
domains to the live list; incomplete items are dropped in code, never
repaired. Contradictions are materialized as lesson documents carrying a
`contradicts` edge — that edge is curation's deterministic refute worklist.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from .config import Config
from .domains import list_domains
from .embed import try_embed_texts, vec_literal
from .llm import run_structured
from .pins import matching_pins
from .store import EdgeSpec, save_document
from .transcript import build_digest

MAX_ITEMS_PER_KIND = 8
MAX_EDGES_PER_ITEM = 5

# The literal header of a mining prompt. It is ALSO the fingerprint of a
# synthetic transcript: one of our own `claude -p` mining subprocesses, whose
# first user message is exactly this prompt. If such a transcript is ever
# enqueued (a pre-fix backlog row, or any future path), mining it yields only
# nested headers. Kept as one constant so the prompt and the skip guard in
# mine_session can never drift apart.
DIGEST_HEADER = ("SESSION DIGEST (user/assistant prose + tool names; "
                 "tool outputs omitted):")

_PREDICATES = ["references", "extends", "depends_on", "complements",
               "contrasts_with", "informs", "part_of", "derived_from",
               "supersedes", "contradicts", "duplicate_of"]

SYSTEM = (
    "You mine ONE Claude Code session digest for DURABLE knowledge. "
    "Only facts, lessons, and error signals worth remembering across "
    "sessions — never transient task narration or one-off chatter. "
    "Each item is third-person and self-contained. "
    "signals are recognizable error signatures: `signal` holds the LITERAL "
    "observable text a future occurrence would contain. "
    "edges link items to EXISTING knowledge by slug when the digest names "
    "one (memory-tool lines in the digest show slugs); omit edges you "
    "cannot ground in the digest. "
    "contradictions: stored DOCUMENTS this session's evidence contradicts — "
    "identified by a slug that literally appears in the digest, with the "
    "quote; never invent a slug. "
    "contradictions_with_pins: stored PINS (the STORED PINS list in the "
    "prompt) this session's evidence contradicts — identify the pin by its "
    "literal text, with the quote. "
    "pin_suggestions: only rules the USER stated as standing instructions. "
    "domain_proposals: only when content clearly fits no existing domain. "
    "Empty lists are the correct answer for an unremarkable session."
)


def _item_schema(domains: list[str], with_signal: bool) -> dict:
    props = {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "domain": {"type": "string", "enum": list(domains)},
        "edges": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "predicate": {"type": "string", "enum": _PREDICATES},
                "dst_slug": {"type": "string"},
                "evidence": {"type": ["string", "null"]},
                "confidence": {"type": ["string", "null"],
                               "enum": ["high", "medium", "low", None]},
            },
            "required": ["predicate", "dst_slug", "evidence", "confidence"],
            "additionalProperties": False,
        }},
    }
    required = ["title", "body", "domain", "edges"]
    if with_signal:
        props["signal"] = {"type": "string"}
        required.append("signal")
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def build_schema(domain_names: list[str]) -> dict:
    item = _item_schema(domain_names, with_signal=False)
    sig_item = _item_schema(domain_names, with_signal=True)
    props = {
        "memories": {"type": "array", "items": item},
        "lessons": {"type": "array", "items": item},
        "signals": {"type": "array", "items": sig_item},
        "pin_suggestions": {"type": "array", "items": {
            "type": "object",
            "properties": {"body": {"type": "string"},
                           "scope": {"type": "string"},
                           "reason": {"type": "string"}},
            "required": ["body", "scope", "reason"],
            "additionalProperties": False}},
        "contradictions": {"type": "array", "items": {
            "type": "object",
            "properties": {"slug": {"type": "string"},
                           "statement": {"type": "string"},
                           "quote": {"type": "string"},
                           "domain": {"type": "string",
                                      "enum": list(domain_names)}},
            "required": ["slug", "statement", "quote", "domain"],
            "additionalProperties": False}},
        "contradictions_with_pins": {"type": "array", "items": {
            "type": "object",
            "properties": {"pin": {"type": "string"},
                           "statement": {"type": "string"},
                           "quote": {"type": "string"}},
            "required": ["pin", "statement", "quote"],
            "additionalProperties": False}},
        "domain_proposals": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"},
                           "description": {"type": "string"},
                           "reason": {"type": "string"}},
            "required": ["name", "description", "reason"],
            "additionalProperties": False}},
    }
    return {"type": "object", "properties": props,
            "required": list(props.keys()), "additionalProperties": False}


def build_prompt(digest_text: str, domain_names: list[str],
                 pin_bodies: list[str]) -> str:
    pins_block = "\n".join(f"- {b}" for b in pin_bodies) or "(none)"
    return (
        f"{DIGEST_HEADER}\n"
        f"{digest_text}\n\n"
        f"EXISTING DOMAINS: {', '.join(domain_names)}\n\n"
        "STORED PINS (standing rules — does anything in this session "
        "contradict one?):\n"
        f"{pins_block}\n\n"
        "Extract durable knowledge per the schema. Does anything in this "
        "session contradict a stored document (slug in the digest) or a "
        "stored pin (list above)? Documents go under contradictions, pins "
        "under contradictions_with_pins — always with the literal quote."
    )


@dataclass(frozen=True)
class MinedItem:
    title: str
    body: str
    domain: str
    signal: str | None = None
    edges: list[EdgeSpec] = field(default_factory=list)


@dataclass(frozen=True)
class Extraction:
    memories: list[MinedItem]
    lessons: list[MinedItem]
    signals: list[MinedItem]
    pin_suggestions: list[dict]
    contradictions: list[dict]
    contradictions_with_pins: list[dict]
    domain_proposals: list[dict]


def _parse_edges(raw) -> list[EdgeSpec]:
    out = []
    for e in (raw or [])[:MAX_EDGES_PER_ITEM]:
        if not isinstance(e, dict):
            continue
        pred = str(e.get("predicate", "")).strip()
        dst = str(e.get("dst_slug", "")).strip()
        if pred not in _PREDICATES or not dst:
            continue
        conf = e.get("confidence")
        out.append(EdgeSpec(
            pred, dst,
            # BACKLOG gate: absent evidence must be None, never "" — the
            # store's COALESCE guard only protects NULL from clobbering
            evidence=(str(e["evidence"]).strip() or None)
            if e.get("evidence") else None,
            confidence=conf if conf in ("high", "medium", "low") else None))
    return out


def _parse_items(raw, domain_names: set[str],
                 need_signal: bool) -> list[MinedItem]:
    out: list[MinedItem] = []
    for it in (raw or []):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title", "")).strip()
        body = str(it.get("body", "")).strip()
        domain = str(it.get("domain", "")).strip()
        signal = str(it.get("signal", "")).strip() or None
        if not title or not body or domain not in domain_names:
            continue
        if need_signal and not signal:
            continue
        out.append(MinedItem(title, body, domain, signal,
                             _parse_edges(it.get("edges"))))
        if len(out) >= MAX_ITEMS_PER_KIND:
            break
    return out


def _parse_dicts(raw, keys: tuple[str, ...], cap: int = 5) -> list[dict]:
    out = []
    for d in (raw or []):
        if isinstance(d, dict) and all(str(d.get(k, "")).strip()
                                       for k in keys):
            out.append({k: str(d[k]).strip() for k in keys})
            if len(out) >= cap:
                break
    return out


def parse_extraction(data: dict, domain_names: set[str]) -> Extraction:
    return Extraction(
        memories=_parse_items(data.get("memories"), domain_names, False),
        lessons=_parse_items(data.get("lessons"), domain_names, False),
        signals=_parse_items(data.get("signals"), domain_names, True),
        pin_suggestions=_parse_dicts(
            data.get("pin_suggestions"), ("body", "scope", "reason"), cap=3),
        # grounded-or-dropped applies HERE too: the schema enum constrains
        # domain at the CLI layer, but parse is the in-code guarantee — an
        # unvalidated domain would abort the whole mining job at save time
        # (unknown-domain ValueError) after earlier saves already committed
        contradictions=[
            c for c in _parse_dicts(
                data.get("contradictions"),
                ("slug", "statement", "quote", "domain"), cap=5)
            if c["domain"] in domain_names
        ],
        contradictions_with_pins=_parse_dicts(
            data.get("contradictions_with_pins"),
            ("pin", "statement", "quote"), cap=5),
        domain_proposals=_parse_dicts(
            data.get("domain_proposals"),
            ("name", "description", "reason"), cap=3),
    )


@dataclass(frozen=True)
class MineResult:
    saved: int = 0
    duplicates: int = 0
    contradictions: int = 0
    pin_suggestions: int = 0
    pin_contradictions: int = 0
    domain_proposals: int = 0
    new_last_uuid: str | None = None
    skipped: str | None = None


def _near_duplicate(conn, cfg: Config, title: str, body: str,
                    domain: str) -> str | None:
    """Slug of the most similar active doc in the domain, if similarity
    reaches cfg.dedup_threshold. None when Ollama is down (dedup is
    best-effort; the save itself is never blocked)."""
    vecs = try_embed_texts([f"{title}\n{body}"], cfg)
    if vecs is None:
        return None
    lit = vec_literal(vecs[0])
    row = conn.execute(
        "SELECT d.slug, 1 - (c.embedding <=> %s::halfvec) AS sim"
        " FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE d.domain = %s AND d.status = 'active'"
        " AND c.embedding IS NOT NULL"
        " ORDER BY c.embedding <=> %s::halfvec LIMIT 1",
        (lit, domain, lit)).fetchone()
    if row and float(row["sim"]) >= cfg.dedup_threshold:
        return row["slug"]
    return None


def _audit(conn, op: str, summary: str) -> None:
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES ('mining', %s, %s)",
        (op, summary))
    conn.commit()


def mine_session(conn, cfg: Config, *, session_id: str, transcript_path: str,
                 last_uuid: str | None, project: str | None,
                 runner=subprocess.run) -> MineResult:
    digest = build_digest(transcript_path, after_uuid=last_uuid,
                          max_chars=cfg.mine_max_digest_chars,
                          per_block=cfg.mine_per_block_chars)
    if not digest.text.strip():
        return MineResult(new_last_uuid=digest.last_uuid or last_uuid,
                          skipped="empty digest")
    # Defense-in-depth for the mining cascade (root cause fixed in llm.py):
    # skip a transcript that is itself one of our `claude -p` mining calls.
    # build_digest prefixes the first user turn as "[user] " + its content, so
    # a synthetic transcript's digest opens with the mining header. Matching
    # the FIRST line only keeps real sessions that merely discuss mining.
    first_line = digest.text.lstrip().split("\n", 1)[0]
    if first_line.removeprefix("[user] ").startswith(DIGEST_HEADER):
        return MineResult(new_last_uuid=digest.last_uuid or last_uuid,
                          skipped="synthetic mining transcript")
    domain_names = [d.name for d in list_domains(conn)]
    if not domain_names:
        return MineResult(new_last_uuid=last_uuid,
                          skipped="no domains defined (run 'rag domain add')")
    pin_bodies = [p.body for p in matching_pins(conn, project)]
    data = run_structured(
        build_prompt(digest.text, domain_names, pin_bodies),
        build_schema(domain_names), cfg, system=SYSTEM, runner=runner)
    ext = parse_extraction(data, set(domain_names))

    provenance = {"origin": "session-mining", "session_id": session_id,
                  "project": project}
    saved = duplicates = 0
    for dtype, items in (("memory", ext.memories), ("lesson", ext.lessons),
                         ("signal", ext.signals)):
        for item in items:
            edges = list(item.edges)
            dup_slug = _near_duplicate(conn, cfg, item.title, item.body,
                                       item.domain)
            if dup_slug:
                edges.append(EdgeSpec(
                    "duplicate_of", dup_slug,
                    evidence=f"embedding similarity >= "
                             f"{cfg.dedup_threshold} at mining time",
                    confidence="medium"))
                duplicates += 1
            body = item.body
            meta = {}
            if item.signal:
                meta["signal"] = item.signal
                if item.signal not in body:
                    body = f"{body}\n\n## Signal\n\n{item.signal}"
            save_document(
                conn, cfg, title=item.title, body=body, domain=item.domain,
                dtype=dtype, meta=meta, provenance=provenance, edges=edges,
                actor="mining")
            saved += 1

    for c in ext.contradictions:
        target = conn.execute(
            "SELECT slug FROM documents WHERE slug = %s",
            (c["slug"],)).fetchone()
        save_document(
            conn, cfg,
            title=f"Contradiction: {c['slug']}",
            body=(f"{c['statement']}\n\n> {c['quote']}\n\n"
                  f"Contradicts [[{c['slug']}]]"
                  + ("" if target else " (slug not found at mining time)")),
            domain=c["domain"], dtype="lesson", provenance=provenance,
            edges=[EdgeSpec("contradicts", c["slug"], evidence=c["quote"],
                            confidence="medium")],
            actor="mining")

    for s in ext.pin_suggestions:
        _audit(conn, "pin_suggestion",
               f"[{s['scope']}] {s['body']} — {s['reason']}"
               f" (session {session_id})")
    for c in ext.contradictions_with_pins:
        # pins are automation-exempt: no document, no edge, no pin change —
        # the audit row IS the deliverable, surfaced by rag review
        _audit(conn, "pin_contradiction",
               f"pin: {c['pin']} — {c['statement']} > {c['quote']}"
               f" (session {session_id})")
    for d in ext.domain_proposals:
        _audit(conn, "domain_proposal",
               f"{d['name']}: {d['description']} — {d['reason']}"
               f" (session {session_id})")

    return MineResult(
        saved=saved + len(ext.contradictions), duplicates=duplicates,
        contradictions=len(ext.contradictions),
        pin_suggestions=len(ext.pin_suggestions),
        pin_contradictions=len(ext.contradictions_with_pins),
        domain_proposals=len(ext.domain_proposals),
        new_last_uuid=digest.last_uuid or last_uuid)
