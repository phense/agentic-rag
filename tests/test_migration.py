"""Import-engine tests: idempotency, signal children, pins, conflicts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_rag import migration, store
from agentic_rag.config import Config

from tests._mig_fixture import build_collision_source, build_source


def _no_embed_cfg() -> Config:
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_source(tmp_path)


def test_run_migration_imports_everything(conn, source):
    stats = migration.run_migration(conn, _no_embed_cfg(), source)
    # 3 wiki + 2 memories + 1 signal child
    assert stats.docs_imported == 5 and stats.signals_created == 1
    assert stats.pins_created == 1

    rows = conn.execute("SELECT slug, dtype, status, domain FROM documents"
                        " ORDER BY slug").fetchall()
    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["alpha"]["dtype"] == "concept"
    assert by_slug["old-stub"]["status"] == "archived"
    assert by_slug["alpha-signal"]["dtype"] == "signal"
    # memory title "Beta" collides with wiki slug beta → auto-uniquified
    assert "beta-2" in by_slug and by_slug["beta-2"]["domain"] == "nature"

    preds = conn.execute(
        "SELECT predicate, dst_slug, created_by FROM edges").fetchall()
    assert all(r["created_by"] == "migration" for r in preds)
    pairs = {(r["predicate"], r["dst_slug"]) for r in preds}
    assert ("references", "beta") in pairs
    assert ("part_of", "rivers-index") in pairs        # dangling — allowed
    assert ("duplicate_of", "beta") in pairs
    assert ("derived_from", "alpha") in pairs

    pin = conn.execute("SELECT body, scope FROM pins").fetchone()
    assert pin["scope"] == "global" and pin["body"].startswith("[[")


def test_run_migration_is_idempotent(conn, source):
    migration.run_migration(conn, _no_embed_cfg(), source)
    stats2 = migration.run_migration(conn, _no_embed_cfg(), source)
    assert stats2.docs_imported == 0 and stats2.pins_created == 0
    assert stats2.docs_skipped == 5
    n = conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    assert n == 6  # 3 wiki + 2 memories + 1 signal child — nothing doubled


def test_dry_run_writes_nothing(conn, source):
    stats = migration.run_migration(conn, _no_embed_cfg(), source, dry_run=True)
    assert stats.docs_imported == 0
    assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM domains").fetchone()["n"] == 0


def test_summary_shows_tail_marker_when_warnings_truncated():
    # On the real corpus the summary's [:40] cap silently swallowed the 5
    # duplicate-wiki-slug notes among ~88 warning kinds — the reader had no
    # way to know more existed.
    stats = migration.MigrationStats()
    for i in range(45):
        stats.note(f"warning kind {i}")
    text = stats.summary()
    assert "… and 5 more warning kinds" in text


def test_summary_no_tail_marker_under_cap():
    stats = migration.MigrationStats()
    stats.note("only one kind")
    assert "more warning kinds" not in stats.summary()


def test_dry_run_prints_duplicate_slug_notes_separately(conn, collision_source):
    # Duplicate-slug notes must be visible on their own, unconditionally —
    # never only inside stats.summary()'s capped warnings block (they'd be
    # invisible past the 40th warning kind on the real corpus).
    logs: list[str] = []
    stats = migration.run_migration(conn, _no_embed_cfg(), collision_source,
                                    dry_run=True, log=logs.append)
    dup_lines = [ln for ln in logs
                 if "duplicate wiki slug: mineral-groups-index" in ln]
    assert dup_lines, logs
    # ALSO on the record in stats, per the fix spec
    assert any("duplicate wiki slug: mineral-groups-index" in w
               for w in stats.unmapped)


def test_limit_supports_partial_then_resume(conn, source):
    s1 = migration.run_migration(conn, _no_embed_cfg(), source, limit=2)
    assert s1.docs_imported == 2
    s2 = migration.run_migration(conn, _no_embed_cfg(), source)
    assert s2.docs_imported == 3 and s2.docs_skipped == 2


@pytest.fixture
def collision_source(tmp_path: Path) -> Path:
    return build_collision_source(tmp_path)


def test_scan_source_without_memory_db(tmp_path):
    wiki = tmp_path / "src" / "wiki" / "topic"
    wiki.mkdir(parents=True)
    (wiki / "note.md").write_text("---\ntype: concept\ntitle: N\n---\n\nBody.\n")
    wiki_docs, memory_docs = migration.scan_source(tmp_path / "src")
    assert len(wiki_docs) == 1
    assert memory_docs == []            # no memory.db is fine, not an error


def test_explicit_slug_collision_retries_loudly(conn, collision_source):
    # The second same-stem save must hit the UniqueViolation retry path:
    # renamed loudly, BOTH docs imported.
    stats = migration.run_migration(conn, _no_embed_cfg(), collision_source)
    assert stats.docs_imported == 2
    assert len(stats.slug_conflicts) == 1
    wanted, actual = stats.slug_conflicts[0]
    assert wanted == "mineral-groups-index" and actual != wanted
    slugs = {r["slug"] for r in conn.execute(
        "SELECT slug FROM documents").fetchall()}
    assert "mineral-groups-index" in slugs and actual in slugs
    # iter_wiki_pages is sorted: default/... imports first and keeps the wiki
    # slug; nature/... collides and is renamed from its slugified title
    keeper = conn.execute("SELECT title FROM documents WHERE slug = %s",
                          ("mineral-groups-index",)).fetchone()
    assert keeper["title"] == "Mineral Groups (default)"
    assert actual == "mineral-groups"


def test_resume_does_not_lose_second_same_stem_page(conn, collision_source):
    # source_id is the relative path, not the slug: after a crash between
    # the two same-stem pages, resume must still import the second one
    # (a slug-keyed done-set would silently skip it forever).
    s1 = migration.run_migration(conn, _no_embed_cfg(), collision_source,
                                 limit=1)
    assert s1.docs_imported == 1 and s1.docs_skipped == 0
    s2 = migration.run_migration(conn, _no_embed_cfg(), collision_source)
    assert s2.docs_imported == 1 and s2.docs_skipped == 1
    slugs = {r["slug"] for r in conn.execute(
        "SELECT slug FROM documents").fetchall()}
    assert slugs == {"mineral-groups-index", "mineral-groups"}


import json as _json


def _fake_runner_factory(calls):
    """Collects prompts; classifies every batch item into 'nature' and
    proposes one new domain. Signature mirrors tests/test_mining.py's
    `def runner(cmd, **kw)` convention (llm.run_structured calls
    runner(cmd, capture_output=True, text=True, timeout=…, env=…))."""
    def fake_runner(cmd, **kw):
        calls.append(cmd)
        prompt = cmd[cmd.index("-p") + 1]
        slugs = [ln.split("slug=")[1].split(" |")[0]
                 for ln in prompt.splitlines() if "slug=" in ln]
        payload = {"assignments": [{"slug": s, "domain": "nature"}
                                   for s in slugs],
                   "new_domains": [{"name": "geology",
                                    "description": "Geology"}]}
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, stdout=_json.dumps(payload), stderr="")
    return fake_runner


def test_classify_writes_tsv_and_md(conn, source, monkeypatch, tmp_path):
    migration.run_migration(conn, _no_embed_cfg(), source)
    calls: list = []
    out_md = migration.classify_domains(conn, _no_embed_cfg(), batch=2,
                                        runner=_fake_runner_factory(calls),
                                        log=lambda *_: None)
    tsv = migration.MIGRATION_DIR / "domain-report.tsv"
    assert out_md.exists() and tsv.exists()
    lines = tsv.read_text().splitlines()
    assert lines[0] == "slug\tcurrent\tproposed"
    # only ACTIVE migrated docs are classified (no archived redirect stub)
    slugs = {ln.split("\t")[0] for ln in lines[1:]}
    assert "old-stub" not in slugs and "alpha" in slugs
    assert all(ln.split("\t")[2] == "nature" for ln in lines[1:])
    assert len(calls) >= 2                       # batching happened
    assert "geology" in out_md.read_text()       # new-domain proposal surfaced


def test_classify_drops_invalid_llm_domain_names(conn, source):
    # Never trust LLM output, even behind --json-schema: a domain name with
    # a tab/newline would corrupt the TSV that Task 9 parses with split("\t").
    migration.run_migration(conn, _no_embed_cfg(), source)

    def bad_runner(cmd, **kw):
        prompt = cmd[cmd.index("-p") + 1]
        slugs = [ln.split("slug=")[1].split(" |")[0]
                 for ln in prompt.splitlines() if "slug=" in ln]
        assignments = [{"slug": slugs[0], "domain": "nature"}]
        # $ matches before a trailing newline — .match() would let this
        # through and write a spurious blank TSV line; only fullmatch is safe
        assignments += [{"slug": slugs[1], "domain": "nature\n"}]
        assignments += [{"slug": s, "domain": "bad\tdomain"}
                        for s in slugs[2:]]
        payload = {"assignments": assignments,
                   "new_domains": [{"name": "Bad Name",
                                    "description": "kein kebab-case"}]}
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, stdout=_json.dumps(payload),
                                   stderr="")

    out_md = migration.classify_domains(conn, _no_embed_cfg(),
                                        runner=bad_runner,
                                        log=lambda *_: None)
    tsv = migration.MIGRATION_DIR / "domain-report.tsv"
    lines = tsv.read_text().splitlines()
    # the TSV contract survives hostile names: exactly 3 fields per row
    assert all(len(ln.split("\t")) == 3 for ln in lines)
    by = {ln.split("\t")[0]: ln.split("\t")[2] for ln in lines[1:]}
    assert by["alpha"] == "nature"               # valid proposal intact
    assert all(v == "" for s, v in by.items() if s != "alpha")
    md = out_md.read_text()
    # 3× "bad\tdomain" + 1× "nature\n" + 1× "Bad Name"
    assert "dropped invalid LLM domain names: 5" in md
    assert "Bad Name" not in md                  # invalid new domain filtered


def test_classify_drops_assignment_missing_slug(conn, source):
    # An LLM assignment with no "slug" key at all must be dropped-and-counted
    # like an invalid domain name, never KeyError the classify run away.
    migration.run_migration(conn, _no_embed_cfg(), source)

    def runner(cmd, **kw):
        prompt = cmd[cmd.index("-p") + 1]
        slugs = [ln.split("slug=")[1].split(" |")[0]
                 for ln in prompt.splitlines() if "slug=" in ln]
        assignments = [{"slug": s, "domain": "nature"} for s in slugs]
        assignments.append({"domain": "nature"})   # missing "slug"
        payload = {"assignments": assignments, "new_domains": []}
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, stdout=_json.dumps(payload),
                                   stderr="")

    out_md = migration.classify_domains(conn, _no_embed_cfg(),
                                        runner=runner,
                                        log=lambda *_: None)
    tsv = migration.MIGRATION_DIR / "domain-report.tsv"
    lines = tsv.read_text().splitlines()
    assert all(len(ln.split("\t")) == 3 for ln in lines)   # no crash, TSV intact
    by = {ln.split("\t")[0]: ln.split("\t")[2] for ln in lines[1:]}
    assert by["alpha"] == "nature"
    assert "dropped invalid LLM domain names: 1" in out_md.read_text()


def test_apply_domain_report(conn, source, tmp_path):
    migration.run_migration(conn, _no_embed_cfg(), source)
    conn.execute("INSERT INTO domains(name, description)"
                 " VALUES ('geology', '')")
    conn.commit()
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\n"
                   "alpha\tnature\tgeology\n"       # applied
                   "beta\tnature\tnature\n"         # same → skipped
                   "ghost\tnature\tgeology\n")      # unknown slug → skipped
    applied, skipped = migration.apply_domain_report(conn, tsv,
                                                     log=lambda *_: None)
    assert (applied, skipped) == (1, 1)
    row = conn.execute("SELECT domain FROM documents WHERE slug='alpha'"
                       ).fetchone()
    assert row["domain"] == "geology"


def test_apply_domain_report_aborts_on_unknown_domain(conn, source, tmp_path):
    migration.run_migration(conn, _no_embed_cfg(), source)
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\nalpha\tnature\tnope\n")
    with pytest.raises(ValueError, match="rag domain add"):
        migration.apply_domain_report(conn, tsv, log=lambda *_: None)
    row = conn.execute("SELECT domain FROM documents WHERE slug='alpha'"
                       ).fetchone()
    assert row["domain"] == "nature"               # nothing applied


def test_apply_domain_report_rejects_malformed_row_with_location(
        conn, source, tmp_path):
    # Peter hand-edits this TSV — a bad row must fail with file:line,
    # not a bare tuple-unpack traceback.
    migration.run_migration(conn, _no_embed_cfg(), source)
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\n"
                   "alpha\tnature\tgeology\textra\n")   # 4 fields
    with pytest.raises(ValueError, match=r"r\.tsv:2"):
        migration.apply_domain_report(conn, tsv, log=lambda *_: None)
    row = conn.execute("SELECT domain FROM documents WHERE slug='alpha'"
                       ).fetchone()
    assert row["domain"] == "nature"               # nothing applied


def test_apply_domain_report_rerun_is_noop(conn, source, tmp_path):
    # The TSV's `current` column is stale after a first apply — the live
    # domain must be checked so re-runs are true no-ops (no redundant
    # set_domain audit rows).
    migration.run_migration(conn, _no_embed_cfg(), source)
    conn.execute("INSERT INTO domains(name, description)"
                 " VALUES ('geology', '')")
    conn.commit()
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\nalpha\tnature\tgeology\n")
    assert migration.apply_domain_report(conn, tsv,
                                         log=lambda *_: None) == (1, 0)
    assert migration.apply_domain_report(conn, tsv,
                                         log=lambda *_: None) == (0, 1)
    n = conn.execute(
        "SELECT count(*) AS n FROM audit_log"
        " WHERE op = 'set_domain' AND document_id ="
        " (SELECT id FROM documents WHERE slug = 'alpha')").fetchone()["n"]
    assert n == 1


def test_acceptance_report_sections(conn, source, tmp_path):
    migration.run_migration(conn, _no_embed_cfg(), source)
    golden = tmp_path / "golden.tsv"
    # fixture's beta.md body is literally "Body." (tests/_mig_fixture.py) —
    # query "Body" so the FTS-only (no-embed) path deterministically hits it
    golden.write_text("query\texpected_slug\nBody\tbeta\n")
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=golden)
    text = out.read_text()
    assert "## Documents" in text and "wiki-migration" in text
    assert "## Edges" in text and "dangling" in text
    assert "## Pins" in text
    assert "## Golden queries" in text and "1/1" in text
    assert "## Spot check" in text
    assert "count summaries, not diffs" in text     # audit_log caveat (BACKLOG)
    # no-embed cfg → FTS-only run: the degraded-search warning must be
    # visible so hit rates are never mistaken for full-hybrid numbers
    assert "search degraded" in text


def test_acceptance_report_flags_malformed_golden_header(conn, source,
                                                          tmp_path):
    # A hand-edited golden file with a wrong/missing header must surface a
    # visible note — never silently mis-evaluate row 2 as the header, and
    # never skip evaluating the real data rows either.
    migration.run_migration(conn, _no_embed_cfg(), source)
    golden = tmp_path / "golden.tsv"
    golden.write_text("oops\twrongheader\nBody\tbeta\n")
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=golden)
    text = out.read_text()
    assert ("MALFORMED header: 'oops\\twrongheader'"
            " (expected query<TAB>expected_slug)") in text
    assert "1/1 hit@8" in text          # row 2 still evaluated as data


def test_acceptance_report_without_golden_is_visible(conn, source):
    migration.run_migration(conn, _no_embed_cfg(), source)
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=None)
    assert "SKIPPED" in out.read_text()


def test_acceptance_report_malformed_golden_rows_visible(conn, source,
                                                         tmp_path):
    # Peter hand-edits this living checklist — a malformed row must degrade
    # to a visible MALFORMED line, never unpack-crash the whole report.
    migration.run_migration(conn, _no_embed_cfg(), source)
    golden = tmp_path / "golden.tsv"
    golden.write_text("query\texpected_slug\n"
                      "Body\tbeta\n"                 # line 2: valid
                      "only-one-field\n"             # line 3: 1 field
                      "a\tb\tc\n")                   # line 4: 3 fields
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=golden)
    text = out.read_text()
    assert "MALFORMED row 3" in text and "MALFORMED row 4" in text
    assert "1/1 hit@8" in text          # denominator counts well-formed only
    assert "## Documents" in text and "## Edges" in text
    assert "## Pins" in text and "## Spot check" in text


def test_acceptance_report_survives_old_stats_format(conn, source):
    # An older-format run-stats.json (missing keys) must degrade lines to
    # 'n/a', never KeyError the report away.
    migration.run_migration(conn, _no_embed_cfg(), source)
    stats_file = migration.MIGRATION_DIR / "run-stats.json"
    stats_file.write_text('{"docs_imported": 5}')    # reduced key set
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=None)
    text = out.read_text()
    assert "imported 5 docs" in text and "n/a" in text
    assert "## Spot check" in text                   # report completed


def test_persist_stats_writes_atomically_no_tmp_left(conn, source):
    migration.run_migration(conn, _no_embed_cfg(), source)
    stats_file = migration.MIGRATION_DIR / "run-stats.json"
    assert stats_file.exists()
    assert not stats_file.with_suffix(".json.tmp").exists()
    assert json.loads(stats_file.read_text())["docs_imported"] == 5


def test_persist_stats_recovers_from_corrupt_previous_file(conn, source):
    # A truncated/corrupt run-stats.json (killed process mid-write, before
    # this fix's atomic replace) must degrade to 'no previous stats' with a
    # loud warning — never crash the migration run.
    migration.MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    stats_file = migration.MIGRATION_DIR / "run-stats.json"
    stats_file.write_text("{not json")
    logs: list[str] = []
    stats = migration.run_migration(conn, _no_embed_cfg(), source,
                                    log=logs.append)
    assert stats.docs_imported == 5
    assert any("run-stats.json corrupt" in ln for ln in logs)
    assert json.loads(stats_file.read_text())["docs_imported"] == 5


def test_acceptance_report_survives_corrupt_stats_file(conn, source):
    migration.run_migration(conn, _no_embed_cfg(), source)
    stats_file = migration.MIGRATION_DIR / "run-stats.json"
    stats_file.write_text("{not json")
    out = migration.acceptance_report(conn, _no_embed_cfg(), golden=None)
    text = out.read_text()
    assert "run-stats.json unreadable (corrupt?)" in text
    assert "## Spot check" in text                   # report completed
