"""Session mining (spec §6): ONE structured Haiku call per queue job, then
write-through the gateway. Grounded-or-dropped parsing: the schema constrains
domains to the live list; incomplete items are dropped in code, never
repaired. Contradictions are materialized as lesson documents carrying a
`contradicts` edge — that edge is curation's deterministic refute worklist.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field, replace

from .config import Config
from .domains import list_domains
from .embed import try_embed_texts, vec_literal
from .llm import run_structured
from .pins import matching_pins
from .secrets import strip_secrets, strip_secrets_json
from .store import EdgeSpec, save_document
from .mining_window import read_window

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
    "assertions: mutable atomic entity/attribute/value facts supported by a SOURCE EVENTS quote. "
    "Use replacement only for an explicit changed value, extension for additive information, "
    "and assertion otherwise. Never duplicate an assertion in memories/lessons. "
    "Automatic acceptance recognizes explicit declarations such as entity attribute is now value "
    "or entity attribute ist jetzt value; never rewrite a quote to fit this form. Other prose stays reviewable. "
    "Use the exact source_id and quote. event_at is an explicit ISO timestamp or the "
    "source timestamp for a current statement; uncertain time is null. expires_at requires "
    "an explicit ISO time in the quote; otherwise null. Suggestions are not user facts. "
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
    fields = {k: {"type":"string"} for k in ('entity','attribute','value','source_id','quote')}
    fields.update(domain={"type":"string","enum":list(domain_names)},
                  relation={"type":"string","enum":["assertion","extension","replacement"]},
                  event_at={"type":["string","null"]}, expires_at={"type":["string","null"]})
    props['assertions'] = {"type":"array","items":{"type":"object","properties":fields,
                            "required":list(fields),"additionalProperties":False}}
    return {"type": "object", "properties": props,
            "required": list(props.keys()), "additionalProperties": False}


def build_prompt(digest_text: str, domain_names: list[str],
                 pin_bodies: list[str]) -> str:
    pins_block = "\n".join(
        f"- {strip_secrets(body)[0]}" for body in pin_bodies
    ) or "(none)"
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
    assertions: list[dict] = field(default_factory=list)


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
        signal = str(it.get("signal") or "").strip() or None
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
        assertions=[a for a in data.get("assertions", [])[:MAX_ITEMS_PER_KIND] if isinstance(a,dict) and a.get("domain") in domain_names and isinstance(a.get("evidence"),dict)],
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
    has_more: bool = False
    batch_id: str | None = None
    warnings: tuple[str, ...] = ()
    skipped: str | None = None


def _near_duplicate(conn, cfg: Config, title: str, body: str,
                    domain: str, project: str | None = None) -> str | None:
    """Slug of the most similar active doc in the domain, if similarity
    reaches cfg.dedup_threshold. None when Ollama is down (dedup is
    best-effort; the save itself is never blocked)."""
    from .scope import write_scope
    project_scope = write_scope(project=project)
    if not project_scope or project_scope == "unknown":
        return None
    vecs = try_embed_texts([f"{title}\n{body}"], cfg)
    if vecs is None:
        return None
    lit = vec_literal(vecs[0])
    row = conn.execute(
        "SELECT d.slug, 1 - (c.embedding <=> %s::halfvec) AS sim"
        " FROM chunks c JOIN documents d ON d.id = c.document_id"
        " WHERE d.domain = %s AND d.status = 'active' AND d.project_scope = %s"
        " AND c.embedding IS NOT NULL AND assertion_eligible(d.id)"
        " ORDER BY c.embedding <=> %s::halfvec LIMIT 1",
        (lit, domain, project_scope, lit)).fetchone()
    if row and float(row["sim"]) >= cfg.dedup_threshold:
        return row["slug"]
    return None


def _audit(conn, op: str, summary: str) -> None:
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES ('mining', %s, %s)",
        (op, strip_secrets(summary)[0]))


def mine_session(conn, cfg: Config, *, session_id: str, transcript_path: str,
                 last_uuid: str | None, project: str | None,
                 runner=subprocess.run) -> MineResult:
    """Accept a bounded extraction durably, then apply all its effects atomically.

    A previously accepted input cursor wins over new model output/source appends.
    Caller transactions must not contain unrelated uncommitted writes.
    """
    row = conn.execute(
        "SELECT * FROM mining_batches WHERE session_id=%s AND input_cursor=%s",
        (session_id, last_uuid or "")).fetchone()
    conn.commit()
    if row is None:
        window = read_window(transcript_path, after_uuid=last_uuid,
                             max_chars=cfg.mine_max_digest_chars,
                             per_block=cfg.mine_per_block_chars)
        if window.last_uuid == last_uuid:
            return MineResult(new_last_uuid=last_uuid, skipped="empty digest",
                              warnings=window.warnings)
        domain_names = [d.name for d in list_domains(conn)]
        if not domain_names:
            conn.commit()
            return MineResult(new_last_uuid=last_uuid,
                              skipped="no domains defined (run 'rag domain add')")
        synthetic = window.synthetic
        if window.text.strip() and not synthetic:
            pin_bodies = [p.body for p in matching_pins(conn, project)]
            data = run_structured(
                build_prompt(window.text, domain_names, pin_bodies) + "\nSOURCE EVENTS (consumed fragments only):\n" + json.dumps(window.events, ensure_ascii=False),
                build_schema(domain_names), cfg, system=SYSTEM, runner=runner)
        else:
            data = {}
        # Persist only the normalized accepted batch, not unbounded raw output.
        clean, _ = strip_secrets_json(data)
        clean["assertions"] = ground_assertions(clean.get("assertions", []), window.events)
        ext = parse_extraction(clean, set(domain_names))
        row = conn.execute(
            "INSERT INTO mining_batches(session_id,input_cursor,output_cursor,"
            " extraction,domains,project,has_more,warnings)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (session_id,input_cursor) DO NOTHING RETURNING *",
            (session_id, last_uuid or "", window.last_uuid,
             json.dumps({**asdict(ext), "_skip_reason": "synthetic mining transcript" if synthetic else ("empty digest" if not window.text.strip() else None)}), json.dumps(domain_names),
             strip_secrets(project)[0] if project else None,
             window.has_more, json.dumps(window.warnings))).fetchone()
        if row is not None:
            _audit(conn, "mining_accept", f"accepted batch {row['id']}")
        conn.commit()
    # Lock the accepted row so even accidental concurrent callers cannot apply it twice.
    try:
        row = conn.execute(
            "SELECT * FROM mining_batches WHERE session_id=%s AND input_cursor=%s FOR UPDATE",
            (session_id, last_uuid or "")).fetchone()
        if row["result"] is not None:
            result = MineResult(**row["result"])
            conn.commit()
            return result
        ext = parse_extraction(row["extraction"], set(row["domains"]))
        result = _apply_extraction(conn, cfg, ext, session_id=session_id,
                                   project=row["project"], batch_id=str(row["id"]),
                                   output_cursor=row["output_cursor"])
        result = replace(result, has_more=row["has_more"], warnings=tuple(row["warnings"]),
                         skipped=row["extraction"].get("_skip_reason"))
        conn.execute("UPDATE mining_batches SET result=%s, applied_at=now() WHERE id=%s",
                     (json.dumps(asdict(result)), row["id"]))
        _audit(conn, "mining_apply", f"applied batch {row['id']}: {result.saved} documents")
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def _apply_extraction(conn, cfg, ext, *, session_id, project, batch_id,
                      output_cursor):
    provenance = {"origin": "session-mining", "session_id": session_id,
                  "project": project, "mining_batch": batch_id}
    saved = duplicates = 0
    for dtype, items in (("memory", ext.memories), ("lesson", ext.lessons),
                         ("signal", ext.signals)):
        for item in items:
            edges = list(item.edges)
            dup_slug = _near_duplicate(conn, cfg, item.title, item.body,
                                       item.domain, project)
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
                dtype=dtype, meta=meta, provenance={**provenance, "mining_item": f"{dtype}:{saved}"}, edges=edges,
                actor="mining", commit=False)
            saved += 1

    from .store import save_assertion
    for item in ext.assertions:
        result = save_assertion(conn, cfg, **item, project=project, actor='mining', commit=False)
        saved += not result.duplicate
        duplicates += result.duplicate

    for index, c in enumerate(ext.contradictions):
        target = conn.execute(
            "SELECT slug FROM documents WHERE slug = %s",
            (c["slug"],)).fetchone()
        save_document(
            conn, cfg,
            title=f"Contradiction: {c['slug']}",
            body=(f"{c['statement']}\n\n> {c['quote']}\n\n"
                  f"Contradicts [[{c['slug']}]]"
                  + ("" if target else " (slug not found at mining time)")),
            domain=c["domain"], dtype="lesson", provenance={**provenance, "mining_item": f"contradiction:{index}"},
            edges=[EdgeSpec("contradicts", c["slug"], evidence=c["quote"],
                            confidence="medium")],
            actor="mining", commit=False)

    for index, s in enumerate(ext.pin_suggestions):
        _audit(conn, "pin_suggestion",
               f"batch {batch_id} item pin_suggestion:{index} — "
               f"[{s['scope']}] {s['body']} — {s['reason']}"
               f" (session {session_id})")
    for index, c in enumerate(ext.contradictions_with_pins):
        # pins are automation-exempt: no document, no edge, no pin change —
        # the audit row IS the deliverable, surfaced by rag review
        _audit(conn, "pin_contradiction",
               f"batch {batch_id} item pin_contradiction:{index} — "
               f"pin: {c['pin']} — {c['statement']} > {c['quote']}"
               f" (session {session_id})")
    for index, d in enumerate(ext.domain_proposals):
        _audit(conn, "domain_proposal",
               f"batch {batch_id} item domain_proposal:{index} — "
               f"{d['name']}: {d['description']} — {d['reason']}"
               f" (session {session_id})")

    return MineResult(
        saved=saved + len(ext.contradictions), duplicates=duplicates,
        contradictions=len(ext.contradictions),
        pin_suggestions=len(ext.pin_suggestions),
        pin_contradictions=len(ext.contradictions_with_pins),
        domain_proposals=len(ext.domain_proposals),
        new_last_uuid=output_cursor, batch_id=batch_id)


def ground_assertions(items, events):
    """Accept only quotes in the exact consumed event; derive role from source."""
    from .validity import parse_time
    by_id = {e['source_id']:e for e in events}
    out=[]
    for item in (items if isinstance(items,list) else [])[:MAX_ITEMS_PER_KIND]:
        if not isinstance(item,dict): continue
        source=by_id.get(item.get('source_id'))
        quote=item.get('quote')
        if not source or not isinstance(quote,str) or not quote.strip() or quote not in source['text']:
            continue
        if not all(isinstance(item.get(k),str) and item[k].strip() for k in ('entity','attribute','value','domain')):
            continue
        if item.get('relation') not in ('assertion','extension','replacement'): continue
        when=item.get('event_at'); expiry=item.get('expires_at')
        try:
            parsed=parse_time(when)
            source_time=parse_time(source.get('timestamp'))
            if when and when not in quote and (source_time is None or parsed!=source_time): when=None
            if expiry and expiry not in quote: when=expiry=None
            end=parse_time(expiry)
            if end and (when is None or end<=parse_time(when)): when=expiry=None
        except (ValueError,TypeError): when=expiry=None
        evidence={'source_id':source['source_id'],'role':source.get('role') or 'unknown',
                  'quote':quote,'event_at':source.get('timestamp'),'offset':source['offset'],'complete':source.get('complete',False),
                  'grounding': 'explicit_statement' if source.get('complete') is True and explicit_statement(item,quote,source['text']) else 'review'}
        out.append({k:item[k] for k in ('entity','attribute','value','domain','relation')} |
                   {'event_at':when,'expires_at':expiry,'evidence':evidence})
    return out


def explicit_statement(item, quote, fragment):
    """Conservative, auditable EN/DE declaration forms; other prose stays reviewable.

    Match the whole consumed prose, not a selectively quoted clause inside a
    question, hypothetical or historical narrative. A recognized declaration must
    include the explicit entity, attribute and value in that order.
    """
    import re
    text=fragment.strip()
    text=re.sub(r'^\[(?:user|assistant)\]\s*','',text)
    if text.rstrip('.') != quote.strip().rstrip('.'):
        return False
    subject=re.escape(item['entity'].strip())+r'\s+'+re.escape(item['attribute'].strip())
    operator=(r'(?:is now|now|ist jetzt|jetzt|changed to|geändert auf)' if item['relation']=='replacement'
              else r'(?:is now|now|is|ist jetzt|jetzt|ist|=|:)')
    suffix=''
    if item.get('event_at') and item['event_at'] in quote:
        suffix+=r'\s+(?:since|at|seit|ab)\s+'+re.escape(item['event_at'])
    if item.get('expires_at'):
        suffix+=r'\s+(?:until|bis)\s+'+re.escape(item['expires_at'])
    pattern=subject+r'\s*'+operator+r'\s*'+re.escape(item['value'].strip())+suffix+r'\.?'
    return re.fullmatch(pattern,text,re.IGNORECASE) is not None
