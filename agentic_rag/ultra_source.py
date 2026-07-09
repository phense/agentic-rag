"""Read-only readers for an llm-wiki source corpus (topic-partitioned markdown + optional memory.db).

NEVER writes to the source. memory.db is opened with a mode=ro URI; wiki
files are only read. All mapping tables (type→dtype, topic→domain,
predicate normalization) live here as data. Source facts as of 2026-07-05
are documented in the Plan-3 doc.
"""
from __future__ import annotations

import datetime
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from .chunker import _fence_spans, slugify
from .store import EdgeSpec

WIKI_EXCLUDE_DIRS = {"graph"}
WIKI_EXCLUDE_FILES = {".page-template.md"}

# ultra-memory page type → documents.dtype (CHECK: concept lesson signal
# source synthesis memory reference index)
TYPE_DTYPE = {
    "mechanism": "concept",
    "concept": "concept",
    "synthesis": "synthesis",
    "source": "source",
    "practice": "lesson",
    "theme-index": "index",
    "master-index": "index",
    "redirect": "reference",
}
ARCHIVED_TYPES = {"theme-index", "master-index", "redirect"}

PREDICATES = {"references", "extends", "depends_on", "complements",
              "contrasts_with", "informs", "part_of", "derived_from",
              "supersedes", "contradicts", "duplicate_of"}
PREDICATE_MAP = {"informed_by": "informs", "leads_to": "informs",
                 "causes": "informs", "relates_to": "references"}

_FM = re.compile(r"\A---\n(.*?)\n---[ \t]*\n?", re.DOTALL)
# The single most common frontmatter break (measured 2026-07-06: 57/1703
# real wiki pages, 3.3%): an unquoted `title:` value that itself contains a
# colon, e.g. `title: Rivers: a short overview` — PyYAML reads the second
# colon as a new mapping key and raises "mapping values are not allowed
# here". Quoting the value on a single repair retry recovers the type and
# anchors that would otherwise be lost (dtype falls back to reference,
# 5 redirect stubs import ACTIVE with degraded edges).
_TITLE_UNQUOTED_COLON = re.compile(r'^title:\s*(?!["\'])(.*:.*)$', re.MULTILINE)
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_SIGNAL_SEC = re.compile(r"^## Signal[ \t]*$\n(.*?)(?=^#{1,2} |\Z)",
                         re.MULTILINE | re.DOTALL)
WIKI_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class SourceDoc:
    source_id: str
    title: str
    body: str
    domain: str
    dtype: str
    status: str
    meta: dict
    provenance: dict
    slug: str | None = None
    edges: tuple[EdgeSpec, ...] = ()
    signal_body: str | None = None
    pinned: bool = False
    warnings: tuple[str, ...] = ()


def _jsonable(obj):
    """YAML parses dates/datetimes — meta goes to jsonb, so stringify them."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def _quote_title(m: re.Match) -> str:
    value = m.group(1).replace('"', '\\"')
    return f'title: "{value}"'


def split_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    m = _FM.match(text)
    if m is None:
        return {}, text, []
    body = text[m.end():]
    raw = m.group(1)
    try:
        fm = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        repaired, n = _TITLE_UNQUOTED_COLON.subn(_quote_title, raw, count=1)
        if n:
            try:
                fm = yaml.safe_load(repaired) or {}
            except yaml.YAMLError:
                fm = None
            if isinstance(fm, dict):
                return fm, body, ["frontmatter repaired: quoted title"]
        # retry didn't apply or didn't help — surface the ORIGINAL error,
        # not the repair attempt's (the repair is a narrow guess; the real
        # bug may be elsewhere in the frontmatter)
        return {}, body, [f"frontmatter YAML error: {e}"]
    if not isinstance(fm, dict):
        return {}, body, ["frontmatter is not a mapping"]
    return fm, body, []


def _mask_fences(body: str) -> str:
    """Same length as body, but '#' inside code fences neutralized, so
    heading regexes never match inside a fence."""
    return "".join(span.replace("#", " ") if fenced else span
                   for span, fenced in _fence_spans(body))


def extract_signal(body: str) -> str | None:
    m = _SIGNAL_SEC.search(_mask_fences(body))
    if m is None:
        return None
    return body[m.start(1):m.end(1)].strip() or None


def normalize_link(raw: str) -> str | None:
    """[[topic/slug#anchor|label]] → slug; None for template placeholders."""
    t = raw.split("|")[0].split("#")[0].strip()
    t = t.rsplit("/", 1)[-1].strip()
    if t.endswith(".md"):
        t = t[:-3]
    return t if WIKI_SLUG_RE.match(t) else None


def extract_wikilinks(body: str, own_slug: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in _WIKILINK.finditer(body):
        t = normalize_link(m.group(1))
        if t is None or t == own_slug or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def wiki_slug(path: Path, wiki_root: Path) -> str:
    rel = path.relative_to(wiki_root)
    stem = path.stem
    if stem == "index":
        return "-".join([*rel.parent.parts, "index"]) if rel.parent.parts \
            else "index"
    return stem if WIKI_SLUG_RE.match(stem) else slugify(stem)


def iter_wiki_pages(wiki_root: Path) -> list[Path]:
    return sorted(
        p for p in wiki_root.rglob("*.md")
        if not (set(p.relative_to(wiki_root).parts[:-1]) & WIKI_EXCLUDE_DIRS)
        and p.name not in WIKI_EXCLUDE_FILES
    )


def _graph_edges(fm: dict, warnings: list[str]) -> list[EdgeSpec]:
    rels = (fm.get("graph") or {}).get("relationships") or []
    edges: list[EdgeSpec] = []
    if not isinstance(rels, list):
        warnings.append("graph.relationships is not a list — skipped")
        return edges
    for rel in rels:
        if not isinstance(rel, dict):
            continue
        obj = str(rel.get("object", ""))
        dst = normalize_link(obj.split(":", 1)[-1])
        if dst is None:
            warnings.append(f"unparsable relationship object: {obj!r}")
            continue
        raw_pred = str(rel.get("predicate", ""))
        pred = raw_pred if raw_pred in PREDICATES else \
            PREDICATE_MAP.get(raw_pred, "references")
        evidence = rel.get("evidence") or None
        if pred != raw_pred:
            warnings.append(f"predicate fallback: {raw_pred!r} → {pred}")
            evidence = f"[{raw_pred}] {evidence or ''}".strip()
        conf = rel.get("confidence")
        conf = conf if conf in ("high", "medium", "low") else None
        edges.append(EdgeSpec(pred, dst, evidence=evidence, confidence=conf))
    return edges


def parse_wiki_page(path: Path, wiki_root: Path) -> SourceDoc:
    rel = path.relative_to(wiki_root)
    fm, body, warnings = split_frontmatter(path.read_text())
    slug = wiki_slug(path, wiki_root)
    ptype = str(fm.get("type", "") or "")
    dtype = TYPE_DTYPE.get(ptype)
    if dtype is None:
        if ptype:
            warnings.append(f"unknown page type {ptype!r} → reference")
        dtype = "reference"
    root_level = len(rel.parts) == 1
    status = "archived" if (ptype in ARCHIVED_TYPES or root_level) else "active"
    # domain = the top-level topic partition dir (llm-wiki is topic-partitioned);
    # root-level pages have no topic → the always-present 'general' domain.
    domain = (slugify(rel.parts[0]) or "general") if not root_level else "general"
    title = str(fm.get("title") or "").strip()
    if not title:
        m = re.search(r"^# (.+)$", _mask_fences(body), re.MULTILINE)
        title = body[m.start(1):m.end(1)].strip() if m else path.stem

    edges: list[EdgeSpec] = []
    if ptype == "redirect":
        target = fm.get("redirect_to") or fm.get("redirects_to")
        target = normalize_link(str(target)) if target else None
        if target is None:
            links = extract_wikilinks(body, slug)
            target = links[0] if links else None
        if target:
            edges.append(EdgeSpec("duplicate_of", target))
        else:
            warnings.append("redirect without resolvable target")
    else:
        edges.extend(EdgeSpec("references", t)
                     for t in extract_wikilinks(body, slug))
        theme = str(fm.get("theme") or "").strip()
        if theme:
            idx_slug = theme.replace("/", "-") + "-index"
            if idx_slug != slug:
                edges.append(EdgeSpec("part_of", idx_slug))
        edges.extend(_graph_edges(fm, warnings))

    return SourceDoc(
        # source_id is the migration idempotency key — the relative path,
        # NOT the slug: two same-stem pages share a slug, and a slug-keyed
        # resume would silently skip the second one forever. source_path
        # stays alongside (identical for wiki) so provenance keeps the
        # same shape as the memory reader's; the redundancy is deliberate.
        source_id=str(rel),
        title=title,
        body=body.strip() or title,
        domain=domain,
        dtype=dtype,
        status=status,
        meta=_jsonable(fm),
        provenance={"origin": "wiki-migration", "source_id": str(rel),
                    "source_path": str(rel)},
        slug=slug,
        edges=tuple(edges),
        signal_body=extract_signal(body) if status == "active" else None,
        warnings=tuple(warnings),
    )


# memories.type → dtype; node_type=learning refines memory → lesson
MEMORY_TYPE_DTYPE = {"memory": "memory", "project": "memory",
                     "feedback": "lesson", "user": "memory",
                     "reference": "reference"}

_MEMORY_META_COLS = ("type", "node_type", "topic", "created_by", "strength",
                     "access_count", "description", "index_hook", "file_slug",
                     "created_at", "updated_at", "last_verified", "supersedes")


def open_memory_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"memory.db not found: {db_path}")
    sq = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    sq.row_factory = sqlite3.Row
    return sq


def _memory_domain(row: sqlite3.Row) -> str:
    topic = (row["topic"] or "").strip()
    return slugify(topic) or "general"


def read_memories(sq: sqlite3.Connection) -> list[SourceDoc]:
    rows = sq.execute(
        "SELECT m.*, s.cwd AS session_cwd FROM memories m"
        " LEFT JOIN sessions s ON s.id = m.origin_session_id"
        " WHERE m.status = 'active' ORDER BY m.created_at, m.id").fetchall()
    docs: list[SourceDoc] = []
    for row in rows:
        warnings: list[str] = []
        body = (row["body"] or "").strip()
        title = (row["title"] or "").strip() or \
            (body.splitlines()[0].lstrip("# ").strip()[:80] if body else row["id"])
        dtype = MEMORY_TYPE_DTYPE.get(row["type"] or "memory", "memory")
        if row["node_type"] == "learning":
            dtype = "lesson"
        if row["supersedes"]:
            warnings.append(f"supersedes not migrated: {row['supersedes']}")
        provenance = {"origin": "memory-migration", "source_id": row["id"]}
        if row["origin_session_id"]:
            provenance["session_id"] = row["origin_session_id"]
        if row["session_cwd"]:
            provenance["project"] = row["session_cwd"]
        meta = {k: row[k] for k in _MEMORY_META_COLS if row[k] not in (None, "")}
        docs.append(SourceDoc(
            source_id=row["id"],
            title=title,
            body=body or title,
            domain=_memory_domain(row),
            dtype=dtype,
            status="active",
            meta=_jsonable(meta),
            provenance=provenance,
            slug=None,
            signal_body=extract_signal(body),
            pinned=bool(row["pinned"]),
            warnings=tuple(warnings),
        ))
    return docs
