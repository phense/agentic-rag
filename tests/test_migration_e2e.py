"""End-to-end migration chain test (Plan 3, Task 11).

One test that walks the full chain against the test DB with the no-embed
config, over a source tree that exercises every reader/engine branch:
mechanism page (theme + `## Signal` + wikilinks + fenced code block),
concept page with `graph.relationships` (incl. one off-vocabulary
predicate), theme-index, redirect stub, root-level SCHEMA.md (no
frontmatter), a title-less page whose first `# ` line hides inside a code
fence, a German memory (umlauts in the title), a pinned feedback memory
with its own `## Signal` section, a project memory joined to a session's
cwd, and a deleted memory that must never be imported.

Assertions stay structural — counts are derived from THIS fixture, never
from live-corpus totals.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from agentic_rag import migration, search as search_mod
from agentic_rag.config import Config

from tests._mig_fixture import MEM_DDL


def _no_embed_cfg() -> Config:
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


def _build_full_source(tmp_path: Path) -> Path:
    root = tmp_path / "ultra"
    wiki = root / "wiki"
    concepts = wiki / "nature" / "concepts"
    concepts.mkdir(parents=True)

    # Mechanism page: theme (→ part_of rivers-index), wikilink (→ references
    # beta), a fenced code block (fence-aware masking must not treat its
    # '#' as a heading and must not truncate the Signal section), and a
    # `## Signal` section carrying the token "AlphaError" for recall_signals.
    (concepts / "alpha.md").write_text(
        "---\n"
        "type: mechanism\n"
        "title: Alpha\n"
        "theme: rivers\n"
        "---\n\n"
        "Links [[beta]].\n\n"
        "```python\n"
        "# not a heading — inside a fence\n"
        "x = 1\n"
        "```\n\n"
        "## Signal\n\n"
        "AlphaError: calibration overflow triggers this exception.\n"
    )

    # Concept page: graph.relationships with one off-vocabulary predicate
    # ("elaborates" is not in PREDICATES nor PREDICATE_MAP → falls back to
    # "references" and is warned about).
    (concepts / "beta.md").write_text(
        "---\n"
        "type: concept\n"
        "title: Beta\n"
        "graph:\n"
        "  relationships:\n"
        "    - predicate: elaborates\n"
        "      object: \"concept:alpha\"\n"
        "      evidence: \"off-vocabulary predicate test\"\n"
        "      confidence: medium\n"
        "---\n\n"
        "Beta body text.\n"
    )

    # Theme-index page: resolves alpha's "part_of rivers-index" edge to a real
    # (non-dangling) document; type theme-index → archived, out of search.
    (concepts / "rivers-index.md").write_text(
        "---\ntype: theme-index\ntitle: Rivers Index\n---\n\nIndex body.\n"
    )

    # Redirect stub: archived, duplicate_of → beta; body carries a phrase
    # used to prove archived docs never surface in hybrid search.
    (concepts / "old-stub.md").write_text(
        "---\ntype: redirect\ntitle: Gone\nredirect_to: beta\n---\n\n"
        "This is the redirect stub body, merged into [[beta]].\n"
    )

    # Root-level page, no frontmatter at all → dtype falls back to
    # 'reference', status forced 'archived' (root_level), title falls back
    # to the path stem ("SCHEMA") since there is no '# ' heading either.
    (wiki / "SCHEMA.md").write_text(
        "Raw schema notes with no frontmatter and no leading heading.\n"
    )

    # Title-corruption fence path: NO title in frontmatter AND the body's
    # first '# ' line sits INSIDE a code fence. The title fallback must
    # skip the fenced line (fence-aware masking) and pick the first real
    # heading — "Fence Title", never "not the title".
    (concepts / "fence-page.md").write_text(
        "---\ntype: mechanism\n---\n\n"
        "```python\n"
        "# not the title\n"
        "y = 2\n"
        "```\n\n"
        "# Fence Title\n\n"
        "Text after the real heading.\n"
    )

    db_path = root / "memory.db"
    sq = sqlite3.connect(db_path)
    sq.executescript(MEM_DDL)
    sq.execute("INSERT INTO sessions(id, cwd) VALUES ('sess-1', ?)",
               ("/Users/example/Agents/x",))
    sq.execute(
        "INSERT INTO memories(id, type, title, body, created_at,"
        " origin_session_id, topic, pinned) VALUES"
        " ('mem-project', 'project', 'Agentic RAG Projektstatus',"
        " 'Kurzer Stand des Migrationsprojekts.', '2026-06-01',"
        " 'sess-1', NULL, 0)")
    # German memory: umlauts + ß in the title exercise slugify's NFKD-strip
    # path (Größe → groe — ß has no NFKD decomposition and is dropped).
    sq.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " pinned) VALUES ('mem-de', 'memory', 'Größe und Prüfung',"
        " 'Kalibrierungsnotiz zur Prüfgröße.', '2026-06-02',"
        " 'programming', 0)")
    # Pinned feedback memory with its own Signal section → one document-pin
    # AND a second signal child (distinct content from alpha's).
    sq.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " pinned) VALUES ('pin-fb', 'feedback', 'Nie ungefragt loeschen',"
        " 'Wichtige Regel.\n\n## Signal\n\nDeleteWithoutAsk: caused data"
        " loss once.', '2026-06-03', 'nature', 1)")
    # Deleted memory: must never be read/imported (filtered at the SQL
    # source, not just by the engine).
    sq.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " status, pinned) VALUES ('mem-deleted', 'memory', 'Old note',"
        " 'Should not appear.', '2026-06-04', 'nature', 'deleted', 0)")
    sq.commit()
    sq.close()
    return root


def test_full_migration_chain(conn, tmp_path):
    src = _build_full_source(tmp_path)
    cfg = _no_embed_cfg()

    stats = migration.run_migration(conn, cfg, src)

    # counts: every active source row landed exactly once, nothing skipped,
    # no explicit-slug collisions (6 wiki pages + 3 active memories;
    # mem-deleted is invisible — filtered at the source's own SQL query).
    # Signal children (alpha's + pin-fb's) are counted separately below and
    # land as +2 more rows in `documents` (11 total), never in docs_imported.
    assert stats.docs_imported == 9
    assert stats.docs_skipped == 0 and stats.slug_conflicts == []
    assert stats.signals_created == 2
    assert stats.pins_created == 1
    assert sorted(stats.domains_created) == ["general", "nature", "programming"]
    # the off-vocabulary predicate branch actually fired
    assert any("predicate fallback" in w for w in stats.unmapped)

    rows = conn.execute("SELECT slug, title, dtype, status, domain"
                        " FROM documents ORDER BY slug").fetchall()
    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["alpha"]["dtype"] == "concept"
    # title fallback is fence-aware: the fenced '# not the title' line is
    # masked; the first REAL heading becomes the title
    assert by_slug["fence-page"]["title"] == "Fence Title"
    assert by_slug["alpha-signal"]["dtype"] == "signal"
    assert by_slug["old-stub"]["status"] == "archived"
    assert by_slug["rivers-index"]["status"] == "archived"
    assert by_slug["schema"]["status"] == "archived"
    assert by_slug["schema"]["domain"] == "general"     # root-level → general
    # German memory: slugify drops ß entirely (no NFKD decomposition) and
    # strips ü's diaeresis — "Größe und Prüfung" → "groe-und-prufung"
    # (BACKLOG "Plan 3 notes" ß-gate, verified structurally here)
    assert "groe-und-prufung" in by_slug
    assert by_slug["groe-und-prufung"]["domain"] == "programming"

    preds = conn.execute(
        "SELECT predicate, dst_slug, dst_id FROM edges").fetchall()
    pairs = {(r["predicate"], r["dst_slug"]) for r in preds}
    assert ("references", "beta") in pairs          # alpha's wikilink
    assert ("part_of", "rivers-index") in pairs      # alpha's theme edge
    assert ("references", "alpha") in pairs          # beta's off-vocab fallback
    assert ("duplicate_of", "beta") in pairs         # old-stub's redirect
    assert ("derived_from", "alpha") in pairs        # alpha-signal → alpha
    # rivers-index actually exists → the theme edge is NOT dangling
    rivers_edge = next(r for r in preds if (r["predicate"], r["dst_slug"])
                       == ("part_of", "rivers-index"))
    assert rivers_edge["dst_id"] is not None

    # the deleted memory never became a document — asserted directly, not
    # just via count arithmetic
    assert conn.execute(
        "SELECT 1 FROM documents"
        " WHERE provenance->>'source_id' = 'mem-deleted'").fetchone() is None

    # idempotent re-run: nothing imported twice
    again = migration.run_migration(conn, cfg, src)
    assert again.docs_imported == 0
    n = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    assert n == 11

    # the recall-reflex corpus exists: signal children match via SQL
    hit = conn.execute(
        "SELECT * FROM recall_signals('AlphaError', 3)").fetchall()
    assert any(r["slug"].endswith("-signal") for r in hit)
    assert any(r["slug"] == "alpha-signal" for r in hit)

    # archived stays out of hybrid search results by default (no-embed cfg
    # → FTS-only path; hybrid_search filters status='active' regardless)
    hits, _ = search_mod.search(conn, cfg, "redirect stub body")
    assert "old-stub" not in {h.slug for h in hits}

    # pins: document-pin with derived pointer body, scope global
    pin = conn.execute("SELECT * FROM pins").fetchone()
    assert pin["document_id"] is not None
    assert pin["scope"] == "global"
    assert pin["body"].startswith("[[")

    # provenance enables SessionStart project-doc selection
    row = conn.execute(
        "SELECT provenance FROM documents"
        " WHERE provenance->>'source_id' = 'mem-project'").fetchone()
    assert row["provenance"]["project"].startswith("/")

    # dry-run purity check: even with real data already imported, a
    # dry-run over the same source writes nothing
    before = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    dry = migration.run_migration(conn, cfg, src, dry_run=True)
    after = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    assert dry.docs_imported == 0
    assert before == after == 11
