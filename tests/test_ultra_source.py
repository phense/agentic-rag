"""Wiki-side tests for the read-only ultra-memory source readers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agentic_rag import ultra_source as us


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture
def wiki(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    _write(root, "nature/concepts/watershed/rivers/snowmelt-surge.md", (
        "---\n"
        "type: mechanism\n"
        'title: "Snowmelt → River Surge"\n'
        "theme: watershed/rivers\n"
        "anchor: snowmelt-surge\n"
        "created: 2026-05-23\n"
        "updated: 2026-05-23\n"
        "---\n\n"
        "# Snowmelt\n\nSee [[watershed-rivers-index]] and "
        "[[climate/snow-accumulation]] and [[snowmelt-surge]].\n\n"
        "## Signal\n\nflooding downstream after snowmelt\n"
    ))
    _write(root, "nature/concepts/chlorophyll.md", (
        "---\n"
        "type: concept\n"
        "title: Chlorophyll\n"
        "sources: [plant-biology-primer]\n"
        "graph:\n"
        "  node_type: concept\n"
        "  relationships:\n"
        "    - predicate: depends_on\n"
        "      object: concept:light-absorption\n"
        '      evidence: "touchstone quote"\n'
        "      confidence: high\n"
        "      status: current\n"
        "    - predicate: made_up_pred\n"
        "      object: concept:other-thing\n"
        "---\n\nBody with [[chlorophyll|self]] link skipped.\n"
    ))
    _write(root, "nature/concepts/rivers-index.md", (
        "---\ntype: theme-index\ntitle: Rivers Index\n---\n\n"
        "- x → [[watershed/flow-rate]]\n"
    ))
    _write(root, "nature/concepts/agriculture/agriculture-2797.md", (
        "---\ntype: redirect\n"
        'title: "→ agriculture-0370"\n'
        "---\nMerged into [[agriculture-supply/agriculture-0370]].\n"
    ))
    _write(root, "nature/index.md", "---\ntype: master-index\ntitle: Nature\n---\nhub\n")
    _write(root, "index.md", "---\ntype: master-index\ntitle: Wiki\n---\nroot\n")
    _write(root, "SCHEMA.md", "schema doc, no frontmatter\n")
    _write(root, ".page-template.md", "---\ntype: mechanism\n---\n[[<anchor>]]\n")
    _write(root, "graph/README.md", "compiled artifacts\n")
    return root


def test_iter_excludes_template_and_graph(wiki):
    names = [p.name for p in us.iter_wiki_pages(wiki)]
    assert ".page-template.md" not in names and "README.md" not in names
    assert "snowmelt-surge.md" in names


def test_parse_mechanism_page(wiki):
    doc = us.parse_wiki_page(
        wiki / "nature/concepts/watershed/rivers/snowmelt-surge.md", wiki)
    assert doc.slug == "snowmelt-surge"
    # idempotency key = relative path (unique), not the slug (dupable stems)
    assert doc.source_id == "nature/concepts/watershed/rivers/snowmelt-surge.md"
    assert doc.provenance["source_id"] == doc.source_id
    assert doc.dtype == "concept" and doc.domain == "nature"
    assert doc.status == "active"
    assert doc.title == "Snowmelt → River Surge"
    assert doc.signal_body == "flooding downstream after snowmelt"
    assert doc.provenance["origin"] == "wiki-migration"
    preds = {(e.predicate, e.dst_slug) for e in doc.edges}
    # wikilinks → references (basename-normalized, self-link dropped),
    # theme → part_of theme-index
    assert ("references", "watershed-rivers-index") in preds
    assert ("references", "snow-accumulation") in preds
    assert ("part_of", "watershed-rivers-index") in preds
    assert not any(d == "snowmelt-surge" for _, d in preds)
    assert doc.meta["type"] == "mechanism"
    assert isinstance(doc.meta["created"], str)  # yaml dates JSON-safe


def test_parse_graph_relationships_with_predicate_fallback(wiki):
    doc = us.parse_wiki_page(wiki / "nature/concepts/chlorophyll.md", wiki)
    by_dst = {e.dst_slug: e for e in doc.edges}
    dep = by_dst["light-absorption"]
    assert dep.predicate == "depends_on" and dep.confidence == "high"
    assert dep.evidence == "touchstone quote"
    fb = by_dst["other-thing"]
    assert fb.predicate == "references"           # off-vocabulary fallback
    assert fb.evidence.startswith("[made_up_pred]")
    assert any("made_up_pred" in w for w in doc.warnings)


def test_parse_index_and_redirect_archived(wiki):
    idx = us.parse_wiki_page(wiki / "nature/concepts/rivers-index.md", wiki)
    assert idx.dtype == "index" and idx.status == "archived"
    red = us.parse_wiki_page(
        wiki / "nature/concepts/agriculture/agriculture-2797.md", wiki)
    assert red.dtype == "reference" and red.status == "archived"
    assert red.edges == (us.EdgeSpec("duplicate_of", "agriculture-0370"),)


def test_index_md_slugs_are_namespaced(wiki):
    top = us.parse_wiki_page(wiki / "nature/index.md", wiki)
    root = us.parse_wiki_page(wiki / "index.md", wiki)
    assert top.slug == "nature-index" and root.slug == "index"


def test_schema_md_lowercased_and_root_files_archived(wiki):
    doc = us.parse_wiki_page(wiki / "SCHEMA.md", wiki)
    assert doc.slug == "schema" and doc.status == "archived"
    assert doc.dtype == "reference" and doc.title  # falls back to stem/heading


def test_split_frontmatter_repairs_unquoted_title_colon(wiki):
    # The uniform real-corpus break (57/1703 wiki pages, measured
    # 2026-07-06): an unquoted `title:` value that itself contains a colon
    # reads as a second mapping key to PyYAML. One repair retry (quote the
    # value) must recover full frontmatter, not just fall back to reference.
    p = _write(wiki, "nature/concepts/colon-title.md", (
        "---\ntype: mechanism\ntitle: A: B\ntheme: geology\n---\n\nBody.\n"
    ))
    fm, body, warnings = us.split_frontmatter(p.read_text())
    assert fm == {"type": "mechanism", "title": "A: B", "theme": "geology"}
    assert warnings == ["frontmatter repaired: quoted title"]
    doc = us.parse_wiki_page(p, wiki)
    assert doc.title == "A: B" and doc.dtype == "concept"


def test_split_frontmatter_genuinely_broken_still_degrades(wiki):
    # A frontmatter break the title-colon repair can't fix (bad indent, no
    # unquoted-colon title line) must still degrade exactly as before: type
    # lost, original YAML error surfaced — never a silent success.
    p = _write(wiki, "nature/concepts/bad-indent.md", (
        "---\ntype: mechanism\ntitle: Fine\n  bad: [unterminated\n---\n\nBody.\n"
    ))
    fm, body, warnings = us.split_frontmatter(p.read_text())
    assert fm == {}
    assert len(warnings) == 1
    assert warnings[0].startswith("frontmatter YAML error:")
    doc = us.parse_wiki_page(p, wiki)
    assert doc.dtype == "reference"                # type lost, as before


def test_title_fallback_ignores_headings_inside_code_fences(wiki):
    p = _write(wiki, "nature/concepts/fenced-title.md", (
        "---\ntype: mechanism\n---\n\n"
        "```bash\n"
        "# not the title\n"
        "```\n\n"
        "# Real Title\n\nBody text.\n"
    ))
    doc = us.parse_wiki_page(p, wiki)
    assert doc.title == "Real Title"


def test_signal_extraction_ignores_fenced_hash_lines(wiki):
    p = _write(wiki, "nature/concepts/fenced-signal.md", (
        "---\ntype: mechanism\ntitle: Fenced Signal\n---\n\n"
        "# Fenced Signal\n\n"
        "## Signal\n\n"
        "leading signal text\n\n"
        "```python\n"
        "# fenced comment\n"
        "```\n\n"
        "trailing signal text\n\n"
        "## Next\n\nother section\n"
    ))
    doc = us.parse_wiki_page(p, wiki)
    assert "# fenced comment" in doc.signal_body
    assert "trailing signal text" in doc.signal_body
    assert "Next" not in doc.signal_body and "other section" not in doc.signal_body


_MEM_DDL = """
CREATE TABLE memories (id TEXT PRIMARY KEY, type TEXT, title TEXT, body TEXT,
  created_at TEXT, updated_at TEXT, origin_session_id TEXT, last_verified TEXT,
  valid_until TEXT, strength REAL DEFAULT 1.0, access_count INT DEFAULT 0,
  last_accessed TEXT, status TEXT DEFAULT 'active', supersedes TEXT,
  pinned INT DEFAULT 0, description TEXT, index_hook TEXT,
  node_type TEXT DEFAULT 'memory', file_slug TEXT, sort_order TEXT,
  topic TEXT, created_by TEXT DEFAULT 'human', outcome_weight REAL DEFAULT 1.0);
CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT,
  status TEXT, branch TEXT, cwd TEXT, first_prompt TEXT, summary TEXT,
  commit_shas TEXT);
"""


@pytest.fixture
def memdb(tmp_path: Path) -> Path:
    db = tmp_path / "memory.db"
    c = sqlite3.connect(db)
    c.executescript(_MEM_DDL)
    c.execute("INSERT INTO sessions(id, cwd) VALUES ('s1', '/Users/example/Agents/x')")
    c.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " node_type, origin_session_id, pinned) VALUES"
        " ('sing-abc', 'memory', 'Massive API tip', 'drop as_of', '2026-07-04',"
        "  'field-data', 'session-knowledge', 's1', 0)")
    c.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " node_type, pinned) VALUES"
        " ('feedback-oauth', 'feedback', 'OAuth only', 'Nie API-Keys nutzen."
        "\n\n## Signal\n\nANTHROPIC_API_KEY', '2026-05-29', NULL, 'memory', 1)")
    c.execute(
        "INSERT INTO memories(id, type, title, body, created_at, topic,"
        " node_type, pinned) VALUES"
        " ('lrn-1', 'memory', 'A lesson', 'learned', '2026-06-01',"
        "  'weird-new-topic', 'learning', 0)")
    c.execute(
        "INSERT INTO memories(id, type, title, body, created_at, status)"
        " VALUES ('gone', 'memory', 'x', 'y', '2026-06-01', 'deleted')")
    c.commit()
    c.close()
    return db


def test_open_memory_db_is_readonly(memdb):
    sq = us.open_memory_db(memdb)
    with pytest.raises(sqlite3.OperationalError):
        sq.execute("INSERT INTO sessions(id) VALUES ('nope')")
    sq.close()


def test_read_memories_maps_and_enriches(memdb):
    sq = us.open_memory_db(memdb)
    docs = {d.source_id: d for d in us.read_memories(sq)}
    sq.close()
    assert set(docs) == {"sing-abc", "feedback-oauth", "lrn-1"}  # active only

    m = docs["sing-abc"]
    assert m.slug is None and m.dtype == "memory" and m.domain == "field-data"
    assert m.provenance == {"origin": "memory-migration", "source_id": "sing-abc",
                            "session_id": "s1", "project": "/Users/example/Agents/x"}
    assert m.meta["topic"] == "field-data" and not m.pinned

    fb = docs["feedback-oauth"]
    assert fb.dtype == "lesson" and fb.pinned
    assert fb.domain == "general"                 # NULL topic → general fallback
    assert fb.signal_body == "ANTHROPIC_API_KEY"

    ln = docs["lrn-1"]
    assert ln.dtype == "lesson"                   # node_type=learning refines
    assert ln.domain == "weird-new-topic"         # topic slugified directly
    assert ln.warnings == ()                      # no more "unmapped topic" warning


def test_memory_domain_slugify_collapse_falls_back_to_general():
    # a non-empty topic that slugifies to empty (punctuation / non-ASCII with
    # no ASCII decomposition) must still yield the 'general' floor, never an
    # empty-string domain
    assert us._memory_domain({"topic": "###"}) == "general"
    assert us._memory_domain({"topic": "ß"}) == "general"   # ß
    assert us._memory_domain({"topic": None}) == "general"
    assert us._memory_domain({"topic": "field-data"}) == "field-data"
