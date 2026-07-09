"""Plan-3 migration: import the ultra-memory corpus through the write
gateway. One-shot, resumable, idempotent by provenance source_id. The
source is never written. Spec §9; deviations documented in the plan doc.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psycopg

from . import domains as domains_mod
from . import llm
from . import pins as pins_mod
from . import search as search_mod
from . import store
from .config import Config
from .store import EdgeSpec
from .ultra_source import (SourceDoc, iter_wiki_pages, open_memory_db,
                           parse_wiki_page, read_memories)

MIGRATION_DIR = Path.home() / ".agentic-rag" / "migration"

_ORIGINS = ("wiki-migration", "memory-migration")


@dataclass
class MigrationStats:
    docs_imported: int = 0
    docs_skipped: int = 0
    signals_created: int = 0
    pins_created: int = 0
    pins_skipped: int = 0
    edges_created: int = 0
    redactions: int = 0
    embed_missing: int = 0
    domains_created: list[str] = field(default_factory=list)
    slug_conflicts: list[list[str]] = field(default_factory=list)
    redacted_docs: list[list] = field(default_factory=list)
    unmapped: dict[str, int] = field(default_factory=dict)

    def note(self, warning: str) -> None:
        self.unmapped[warning] = self.unmapped.get(warning, 0) + 1

    def summary(self) -> str:
        lines = [
            f"imported: {self.docs_imported} docs"
            f" (+{self.signals_created} signal children),"
            f" skipped (already imported): {self.docs_skipped}",
            f"pins: {self.pins_created} created, {self.pins_skipped} skipped",
            f"edges written: {self.edges_created}",
            f"redactions: {self.redactions} in {len(self.redacted_docs)} docs",
            f"saved without embedding (queued): {self.embed_missing}",
            f"domains created: {', '.join(self.domains_created) or '—'}",
            f"slug conflicts (renamed): {len(self.slug_conflicts)}",
        ]
        if self.unmapped:
            lines.append("warnings:")
            ordered = sorted(self.unmapped.items(), key=lambda kv: -kv[1])
            for w, n in ordered[:40]:
                lines.append(f"  {n:>5}× {w}")
            if len(ordered) > 40:
                lines.append(f"  … and {len(ordered) - 40} more warning kinds")
        return "\n".join(lines)


def scan_source(source: Path) -> tuple[list[SourceDoc], list[SourceDoc]]:
    wiki_root = source / "wiki"
    if not wiki_root.is_dir():
        raise FileNotFoundError(f"no wiki/ under {source}")
    wiki_docs = [parse_wiki_page(p, wiki_root) for p in iter_wiki_pages(wiki_root)]
    memory_docs: list[SourceDoc] = []
    memory_db = source / "memory.db"
    if memory_db.exists():                 # optional: llm-wiki stores may be wiki-only
        sq = open_memory_db(memory_db)
        try:
            memory_docs = read_memories(sq)
        finally:
            sq.close()
    return wiki_docs, memory_docs


def imported_source_ids(conn) -> set[str]:
    rows = conn.execute(
        "SELECT provenance->>'source_id' AS sid FROM documents"
        " WHERE provenance->>'origin' = ANY(%s)", (list(_ORIGINS),)).fetchall()
    return {r["sid"] for r in rows if r["sid"]}


def ensure_domains(conn, needed: set[str], stats: MigrationStats) -> None:
    for name in sorted(needed):
        if conn.execute("SELECT 1 FROM domains WHERE name = %s",
                        (name,)).fetchone():
            continue  # never clobber an existing description
        domains_mod.add_domain(conn, name, "", actor="migration")
        stats.domains_created.append(name)


def _save(conn, cfg, doc: SourceDoc, stats: MigrationStats, *,
          slug, title, body, dtype, edges, provenance):
    """One gateway save with loud-but-handled slug conflicts."""
    try:
        return store.save_document(
            conn, cfg, title=title, body=body, domain=doc.domain,
            dtype=dtype, status=doc.status, slug=slug, meta=doc.meta,
            provenance=provenance, edges=edges, actor="migration")
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        res = store.save_document(  # retry on the auto-unique path
            conn, cfg, title=title, body=body, domain=doc.domain,
            dtype=dtype, status=doc.status, slug=None, meta=doc.meta,
            provenance=provenance, edges=edges, actor="migration")
        stats.slug_conflicts.append([slug or "", res.slug])
        return res


def _import_one(conn, cfg, doc: SourceDoc, stats: MigrationStats) -> None:
    for w in doc.warnings:
        stats.note(w)
    res = _save(conn, cfg, doc, stats, slug=doc.slug,
                title=doc.title, body=doc.body,
                dtype=doc.dtype, edges=list(doc.edges),
                provenance=doc.provenance)
    stats.docs_imported += 1
    stats.edges_created += res.n_edges
    stats.redactions += res.redactions
    if res.redactions:
        stats.redacted_docs.append([res.slug, res.redactions])
    if any("embedding" in w for w in res.warnings):
        stats.embed_missing += 1

    if doc.signal_body and doc.status == "active":
        sig_prov = dict(doc.provenance,
                        source_id=f"{doc.source_id}#signal")
        sres = _save(conn, cfg, doc, stats,
                     slug=f"{res.slug}-signal" if doc.slug else None,
                     title=f"{doc.title} — Signal", body=doc.signal_body,
                     dtype="signal",
                     edges=[EdgeSpec("derived_from", res.slug)],
                     provenance=sig_prov)
        stats.signals_created += 1
        stats.edges_created += sres.n_edges

    if doc.pinned:
        if conn.execute("SELECT 1 FROM pins WHERE document_id = %s",
                        (res.doc_id,)).fetchone():
            stats.pins_skipped += 1
        else:
            pins_mod.add_pin(conn, document_id=res.doc_id, scope="global",
                             actor="migration")
            stats.pins_created += 1


def run_migration(conn, cfg: Config, source: Path, *, dry_run: bool = False,
                  limit: int | None = None, log=print) -> MigrationStats:
    stats = MigrationStats()
    wiki_docs, memory_docs = scan_source(source)
    all_docs = wiki_docs + memory_docs
    log(f"source scan: {len(wiki_docs)} wiki pages, {len(memory_docs)} memories"
        f" ({sum(1 for d in memory_docs if d.pinned)} pinned,"
        f" {sum(1 for d in all_docs if d.signal_body)} signal sections)")

    if dry_run:
        for d in all_docs:
            for w in d.warnings:
                stats.note(w)
        by = {}
        for d in all_docs:
            key = (d.domain, d.dtype, d.status)
            by[key] = by.get(key, 0) + 1
        for (dom, dt, st), n in sorted(by.items()):
            log(f"  {n:>5}  {dom:<15} {dt:<10} {st}")
        dupes = {}
        for d in all_docs:
            if d.slug:
                dupes[d.slug] = dupes.get(d.slug, 0) + 1
        # duplicate-slug notes are printed unconditionally, on their own
        # lines, so they never get lost behind the summary's [:40] warning
        # cap (they did on the real corpus: 5 notes, ~88 warning kinds) —
        # they ALSO go into stats.note() so they're on the record.
        dup_notes = [f"duplicate wiki slug: {slug} ×{n}"
                     for slug, n in sorted(dupes.items()) if n > 1]
        for note in dup_notes:
            stats.note(note)
        if dup_notes:
            log(f"duplicate wiki slugs ({len(dup_notes)}):")
            for note in dup_notes:
                log(f"  {note}")
        log(stats.summary())
        return stats

    ensure_domains(conn, {d.domain for d in all_docs}, stats)
    done = imported_source_ids(conn)
    for doc in all_docs:
        if doc.source_id in done:
            stats.docs_skipped += 1
            continue
        if limit is not None and stats.docs_imported >= limit:
            break
        _import_one(conn, cfg, doc, stats)
        if stats.docs_imported % 100 == 0 and stats.docs_imported:
            log(f"  … {stats.docs_imported} imported")

    _persist_stats(stats, log=log)
    log(stats.summary())
    return stats


def _persist_stats(stats: MigrationStats, *, log=print) -> None:
    """Merge cumulative run stats (resume-friendly) for the acceptance
    report. Atomic write (tmp file + os.replace) so a killed/jetsammed run
    never leaves a half-written file for the next run to choke on; a
    corrupt existing file degrades to 'no previous stats' with a loud
    warning, never a crash mid-migration."""
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    path = MIGRATION_DIR / "run-stats.json"
    data = asdict(stats)
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            log(f"WARNING: run-stats.json corrupt, starting fresh ({e})")
            prev = {}
        for k in ("docs_imported", "docs_skipped", "signals_created",
                  "pins_created", "pins_skipped", "edges_created",
                  "redactions", "embed_missing"):
            data[k] += prev.get(k, 0)
        for k in ("domains_created", "slug_conflicts", "redacted_docs"):
            data[k] = prev.get(k, []) + data[k]
        for w, n in prev.get("unmapped", {}).items():
            data["unmapped"][w] = data["unmapped"].get(w, 0) + n
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


_DOMAIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {"type": "array", "items": {
            "type": "object",
            "properties": {"slug": {"type": "string"},
                           "domain": {"type": "string",
                                      "pattern": "^[a-z0-9][a-z0-9-]*$"}},
            "required": ["slug", "domain"]}},
        "new_domains": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string",
                                    "pattern": "^[a-z0-9][a-z0-9-]*$"},
                           "description": {"type": "string"}},
            "required": ["name", "description"]}},
    },
    "required": ["assignments"],
}

_CLASSIFY_PROMPT = """You are classifying knowledge documents into domains.

Existing domains (STRONGLY prefer these; reuse before inventing):
{domains}

For each item, output an assignment to the best-fitting domain. Only if a
clearly better domain is missing AND would plausibly hold 15+ documents of
this corpus, propose it under new_domains (kebab-case name, one-line
description) and assign items to it. Content may be German or English.

Items:
{items}
"""


def classify_domains(conn, cfg: Config, *, batch: int = 20,
                     runner=subprocess.run, log=print) -> Path:
    rows = conn.execute(
        "SELECT slug, title, domain, left(body, 400) AS excerpt"
        " FROM documents WHERE status = 'active'"
        " AND provenance->>'origin' = ANY(%s) ORDER BY slug",
        (list(_ORIGINS),)).fetchall()
    doms = domains_mod.list_domains(conn)
    dom_lines = "\n".join(f"- {d.name}: {d.description}" for d in doms)
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    tsv = MIGRATION_DIR / "domain-report.tsv"
    new_doms: dict[str, str] = {}
    moves: dict[str, int] = {}
    dropped_invalid = 0
    with tsv.open("w") as f:
        f.write("slug\tcurrent\tproposed\n")
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            items = "\n".join(
                f"- slug={r['slug']} | current={r['domain']} |"
                f" title={r['title']} | excerpt={r['excerpt']!r}"
                for r in chunk)
            data = llm.run_structured(
                _CLASSIFY_PROMPT.format(domains=dom_lines, items=items),
                CLASSIFY_SCHEMA, cfg, runner=runner)
            # never trust LLM output even behind --json-schema: a tab or
            # newline in a domain name would corrupt the TSV contract that
            # `rag migrate apply-domains` (Task 9) parses with split("\t").
            # fullmatch, not match: $ matches BEFORE a trailing newline
            assignments = data.get("assignments", [])
            # .get, not a["slug"]: an LLM assignment missing a slug must be
            # dropped-and-counted like an invalid domain name, never
            # KeyError the whole classify run away.
            by_slug = {}
            for a in assignments:
                slug = a.get("slug")
                if not slug or not _DOMAIN_NAME_RE.fullmatch(a.get("domain", "")):
                    dropped_invalid += 1
                    continue
                by_slug[slug] = a["domain"]
            for nd in data.get("new_domains", []):
                if _DOMAIN_NAME_RE.fullmatch(nd.get("name", "")):
                    new_doms.setdefault(nd["name"], nd["description"])
                else:
                    dropped_invalid += 1
            for r in chunk:
                proposed = by_slug.get(r["slug"], "")
                f.write(f"{r['slug']}\t{r['domain']}\t{proposed}\n")
                if proposed and proposed != r["domain"]:
                    key = f"{r['domain']} → {proposed}"
                    moves[key] = moves.get(key, 0) + 1
            f.flush()
            log(f"classified {min(i + batch, len(rows))}/{len(rows)}")

    md = MIGRATION_DIR / "domain-report.md"
    lines = ["# Domain re-classification report", "",
             f"{len(rows)} active migrated documents classified.", "",
             "## Proposed moves (count by current → proposed)", ""]
    lines += [f"- {k}: {n}" for k, n in
              sorted(moves.items(), key=lambda kv: -kv[1])] or ["- none"]
    if dropped_invalid:
        lines += [f"- dropped invalid LLM domain names: {dropped_invalid}"]
    lines += ["", "## Proposed NEW domains", ""]
    lines += [f"- **{n}** — {d}" for n, d in sorted(new_doms.items())] \
        or ["- none"]
    lines += ["", "## How to apply", "",
              "1. Review/edit `domain-report.tsv` (delete lines you reject;"
              " the `proposed` column is what will be applied).",
              "2. Create approved new domains first:"
              " `rag domain add <name> --description '…'`.",
              "3. `rag migrate apply-domains " + str(tsv) + " --yes`."]
    md.write_text("\n".join(lines) + "\n")
    return md


def apply_domain_report(conn, tsv_path: Path, *, log=print) -> tuple[int, int]:
    lines = tsv_path.read_text().splitlines()
    if not lines or lines[0] != "slug\tcurrent\tproposed":
        raise ValueError(f"not a domain-report TSV: {tsv_path}")
    moves: list[tuple[str, str]] = []
    for lineno, ln in enumerate(lines[1:], start=2):
        if not ln.strip():
            continue
        parts = ln.split("\t")
        if len(parts) != 3:  # fix(plan) Task 9: hand-edited rows must fail
            raise ValueError(  # with file:line, not a bare unpack error
                f"{tsv_path}:{lineno}: malformed row — expected 3"
                f" tab-separated fields (slug/current/proposed),"
                f" got {len(parts)}")
        slug, current, proposed = parts
        if proposed and proposed != current:
            moves.append((slug, proposed))
    missing = sorted({p for _, p in moves if not conn.execute(
        "SELECT 1 FROM domains WHERE name = %s", (p,)).fetchone()})
    if missing:
        raise ValueError(
            "unknown domains in report — create them first with"
            f" 'rag domain add': {', '.join(missing)}")
    applied = skipped = 0
    for slug, proposed in moves:
        row = conn.execute("SELECT id, domain FROM documents WHERE slug = %s",
                           (slug,)).fetchone()
        if row is None:
            log(f"  skip (no such slug): {slug}")
            skipped += 1
            continue
        if row["domain"] == proposed:
            # fix(plan) Task 9: the TSV's `current` column is stale after a
            # first apply — check the LIVE domain so re-runs are true no-ops
            # (no redundant set_domain audit rows)
            skipped += 1
            continue
        store.set_domain(conn, str(row["id"]), proposed, actor="migration")
        applied += 1
    return applied, skipped


def _table(rows, header) -> list[str]:
    out = [" | ".join(header), " | ".join("---" for _ in header)]
    out += [" | ".join(str(c) for c in r) for r in rows]
    return out


def acceptance_report(conn, cfg: Config, *, golden: Path | None = None) -> Path:
    L: list[str] = ["# Migration acceptance report", ""]

    L += ["## Documents", ""]
    rows = conn.execute(
        "SELECT provenance->>'origin' AS origin, dtype, status, count(*) AS n"
        " FROM documents WHERE provenance->>'origin' = ANY(%s)"
        " GROUP BY 1, 2, 3 ORDER BY 1, 2, 3", (list(_ORIGINS),)).fetchall()
    L += _table([(r["origin"], r["dtype"], r["status"], r["n"])
                 for r in rows], ("origin", "dtype", "status", "n"))
    doms = conn.execute(
        "SELECT domain, count(*) AS n FROM documents"
        " WHERE provenance->>'origin' = ANY(%s) GROUP BY 1 ORDER BY n DESC",
        (list(_ORIGINS),)).fetchall()
    L += ["", "By domain: " +
          ", ".join(f"{r['domain']} {r['n']}" for r in doms), ""]

    L += ["## Edges", ""]
    rows = conn.execute(
        "SELECT predicate, count(*) AS n,"
        " count(*) FILTER (WHERE dst_id IS NULL) AS dangling"
        " FROM edges WHERE created_by = 'migration'"
        " GROUP BY 1 ORDER BY n DESC").fetchall()
    L += _table([(r["predicate"], r["n"], r["dangling"]) for r in rows],
                ("predicate", "n", "dangling"))
    top = conn.execute(
        "SELECT dst_slug, count(*) AS n FROM edges"
        " WHERE created_by = 'migration' AND dst_id IS NULL"
        " GROUP BY 1 ORDER BY n DESC LIMIT 20").fetchall()
    L += ["", "Top dangling targets: " +
          (", ".join(f"{r['dst_slug']} ({r['n']})" for r in top) or "none"), ""]
    L += ["Note: the memory.db `links` table (18 trivial informed_by rows from"
          " un-migrated session_events) was deliberately NOT imported"
          " (plan §Deviations).", ""]

    L += ["## Pins", ""]
    rows = conn.execute("SELECT body, scope FROM pins WHERE active"
                        " ORDER BY created_at").fetchall()
    L += [f"- {r['body']}  [{r['scope']}]" for r in rows] or ["- none"]

    stats_file = MIGRATION_DIR / "run-stats.json"
    L += ["", "## Import-run stats", ""]
    if stats_file.exists():
        try:
            s = json.loads(stats_file.read_text())
        except json.JSONDecodeError:
            # atomic os.replace writes make this unlikely, but a report
            # must never crash on a corrupt/truncated stats file
            L += [f"- run-stats.json unreadable (corrupt?): {stats_file}"]
        else:
            # .get with defaults: an older-format stats file must degrade a
            # line to 'n/a', never KeyError the whole report away (fix(plan)
            # during Task 10)
            L += [f"- imported {s.get('docs_imported', 'n/a')} docs,"
                  f" {s.get('signals_created', 'n/a')} signal children,"
                  f" {s.get('pins_created', 'n/a')} pins;"
                  f" {s.get('edges_created', 'n/a')} edges",
                  f"- redactions: {s.get('redactions', 'n/a')}"
                  f" (URL-credential pattern may over-redact — eyeball below)",
                  f"- top redacted docs: " + (", ".join(
                      f"{slug} ({n})" for slug, n in sorted(
                          s.get("redacted_docs", []),
                          key=lambda x: -x[1])[:10]) or "none"),
                  f"- slug conflicts (renamed):"
                  f" {s.get('slug_conflicts') or 'none'}",
                  f"- saved without embedding (queued):"
                  f" {s.get('embed_missing', 'n/a')}"]
    else:
        L += ["- no run-stats.json found (run `rag migrate run` first)"]

    L += ["", "## Golden queries", ""]
    if golden and golden.exists():
        lines_all = golden.read_text().splitlines()
        header = lines_all[0] if lines_all else ""
        if header != "query\texpected_slug":
            # visible, not fatal: line 1 is still skipped as the header
            # either way — a hand-edited file with a mangled/missing header
            # must not silently mis-evaluate row 2 as the header instead
            L.append(f"- MALFORMED header: {header!r} (expected"
                     f" query<TAB>expected_slug)")
        hits = n_rows = 0
        search_warnings: set[str] = set()
        # hand-edited living checklist: a malformed row degrades to a
        # visible MALFORMED line, never an unpack crash that destroys the
        # whole report (fix(plan) during Task 10)
        for lineno, ln in enumerate(lines_all[1:], start=2):
            if not ln.strip():
                continue
            parts = [p.strip() for p in ln.split("\t")]
            if len(parts) != 2 or not all(parts):
                L.append(f"- MALFORMED row {lineno} (expected"
                         f" query<TAB>expected_slug): {ln!r}")
                continue
            q, expected = parts
            n_rows += 1
            found, warns = search_mod.search(conn, cfg, q, k=8)
            search_warnings.update(warns)
            ok = any(h.slug == expected for h in found)
            hits += ok
            L.append(f"- {'HIT ' if ok else 'MISS'} {q!r} → {expected}")
        L += ["", f"**{hits}/{n_rows} hit@8**"]
        if search_warnings:
            # a golden run without Ollama measures FTS-only and
            # under-reports — the reader must see that
            L += ["", "⚠️ search degraded during this run — hit rates are"
                  " NOT comparable to full hybrid search: "
                  + "; ".join(sorted(search_warnings))]
    else:
        L += ["SKIPPED — no golden-queries file supplied"
              " (pass --golden <your-eval.tsv>: a TSV of query<TAB>expected_slug)"]

    L += ["", "## Spot check (deterministic sample — read these manually)", ""]
    rows = conn.execute(
        "SELECT slug, title, domain, dtype FROM documents"
        " WHERE provenance->>'origin' = ANY(%s)"
        " ORDER BY md5(slug) LIMIT 10", (list(_ORIGINS),)).fetchall()
    L += [f"- [[{r['slug']}]] {r['title']} ({r['domain']}/{r['dtype']})"
          for r in rows]

    L += ["", "## Audit", "",
          "audit_log rows for this migration carry count summaries, not"
          " diffs (spec §4 wording; BACKLOG note) — per-document diffs are"
          " reconstructable from provenance.source_path against the"
          " read-only source.", ""]

    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    out = MIGRATION_DIR / "acceptance-report.md"
    out.write_text("\n".join(L) + "\n")
    return out
