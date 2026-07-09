"""Shared ultra-memory source-tree builder for migration tests (Plan 3).

Used by tests/test_migration.py (engine-level) and tests/test_cli.py
(CLI-level preflight/dry-run tests) so the on-disk fixture shape lives in
exactly one place.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MEM_DDL = (
    "CREATE TABLE memories (id TEXT PRIMARY KEY, type TEXT, title TEXT,"
    " body TEXT, created_at TEXT, updated_at TEXT, origin_session_id TEXT,"
    " last_verified TEXT, valid_until TEXT, strength REAL, access_count INT,"
    " last_accessed TEXT, status TEXT DEFAULT 'active', supersedes TEXT,"
    " pinned INT DEFAULT 0, description TEXT, index_hook TEXT,"
    " node_type TEXT DEFAULT 'memory', file_slug TEXT, sort_order TEXT,"
    " topic TEXT, created_by TEXT, outcome_weight REAL);"
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT,"
    " ended_at TEXT, status TEXT, branch TEXT, cwd TEXT, first_prompt TEXT,"
    " summary TEXT, commit_shas TEXT);")


def build_source(tmp_path: Path) -> Path:
    root = tmp_path / "ultra"
    wiki = root / "wiki"
    (wiki / "nature" / "concepts").mkdir(parents=True)
    (wiki / "nature" / "concepts" / "alpha.md").write_text(
        "---\ntype: mechanism\ntitle: Alpha\ntheme: rivers\n---\n\n"
        "Links [[beta]].\n\n## Signal\n\nAlphaError\n")
    (wiki / "nature" / "concepts" / "beta.md").write_text(
        "---\ntype: concept\ntitle: Beta\n---\n\nBody.\n")
    (wiki / "nature" / "concepts" / "old-stub.md").write_text(
        "---\ntype: redirect\ntitle: gone\n---\nMerged into [[beta]].\n")
    db = root / "memory.db"
    c = sqlite3.connect(db)
    c.executescript(MEM_DDL)
    c.execute("INSERT INTO memories(id, type, title, body, created_at, topic,"
              " pinned) VALUES ('pin-1', 'feedback', 'OAuth only',"
              " 'Nie API-Keys.', '2026-05-29', NULL, 1)")
    c.execute("INSERT INTO memories(id, type, title, body, created_at, topic)"
              " VALUES ('mem-1', 'memory', 'Beta', 'Titel kollidiert mit Wiki.',"
              " '2026-06-01', 'nature')")
    c.commit()
    c.close()
    return root


def build_collision_source(tmp_path: Path) -> Path:
    # Two topic dirs, same file stem → same explicit wiki slug (the real
    # corpus has such duplicate index stems). memory.db empty — wiki-only.
    root = tmp_path / "ultra"
    wiki = root / "wiki"
    (wiki / "nature" / "concepts").mkdir(parents=True)
    (wiki / "default" / "concepts").mkdir(parents=True)
    (wiki / "nature" / "concepts" / "mineral-groups-index.md").write_text(
        "---\ntype: theme-index\ntitle: Mineral Groups\n---\n\nA.\n")
    (wiki / "default" / "concepts" / "mineral-groups-index.md").write_text(
        "---\ntype: theme-index\ntitle: Mineral Groups (default)\n---\n\nB.\n")
    db = root / "memory.db"
    c = sqlite3.connect(db)
    c.executescript(MEM_DDL)
    c.commit()
    c.close()
    return root
