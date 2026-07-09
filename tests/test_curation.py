import json

import pytest

from agentic_rag import curation, db
from agentic_rag.config import Config


def _doc(conn, slug, *, domain="d", dtype="memory", title=None, body="b",
         status="active"):
    return str(conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body, status)"
        " VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (slug, domain, dtype, title or slug, body, status)).fetchone()["id"])


def _seed(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    conn.commit()


def _refuse_runner(cmd, **kw):
    class P:
        returncode, stderr = 0, ""
        stdout = json.dumps({"refute": False, "reason": "", "quote": ""})
    return P()


def _refute_runner(cmd, **kw):
    class P:
        returncode, stderr = 0, ""
        stdout = json.dumps({"refute": True,
                             "reason": "superseded by session evidence",
                             "quote": "user: X is actually false"})
    return P()


def test_pass_resolves_dangling_edges(conn, cfg):
    _seed(conn)
    a = _doc(conn, "a")
    conn.execute(
        "INSERT INTO edges(src_id, dst_slug, predicate, created_by)"
        " VALUES (%s, 'later-doc', 'references', 'mining')", (a,))
    conn.commit()
    _doc(conn, "later-doc")
    conn.commit()
    rep = curation.run_pass(conn, cfg, runner=_refuse_runner)
    assert rep.dangling_resolved == 1
    row = conn.execute(
        "SELECT dst_id FROM edges WHERE dst_slug='later-doc'").fetchone()
    assert row["dst_id"] is not None


def test_pass_merges_exact_duplicates_keeps_oldest(conn, cfg):
    _seed(conn)
    _doc(conn, "orig", body="identical text")
    # both INSERTs share the transaction timestamp — backdate the original
    # so "keep the oldest" is deterministic, not a uuid tiebreak
    conn.execute("UPDATE documents SET created_at = created_at"
                 " - interval '1 hour' WHERE slug = 'orig'")
    _doc(conn, "copy", body="identical text")
    rep = curation.run_pass(conn, cfg, runner=_refuse_runner)
    assert rep.merged == 1
    st = {r["slug"]: r["status"] for r in conn.execute(
        "SELECT slug, status FROM documents").fetchall()}
    assert st["orig"] == "active"
    assert st["copy"] == "archived"
    edge = conn.execute(
        "SELECT * FROM edges WHERE predicate='duplicate_of'").fetchone()
    assert edge is not None


def test_pass_refutes_contradicted_doc_with_full_justification(conn, cfg):
    _seed(conn)
    old = _doc(conn, "old-claim", body="X is true")
    contra = _doc(conn, "contradiction-old-claim", dtype="lesson",
                  body="session says X is false")
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, dst_slug, predicate, evidence,"
        " created_by) VALUES (%s, %s, 'old-claim', 'contradicts',"
        " 'user: X is actually false', 'mining')", (contra, old))
    conn.commit()
    rep = curation.run_pass(conn, cfg, runner=_refute_runner)
    assert rep.reviewed == 1 and rep.refuted == 1
    row = conn.execute(
        "SELECT status, refuted_reason, refuted_evidence FROM documents"
        " WHERE slug='old-claim'").fetchone()
    assert row["status"] == "refuted"
    assert row["refuted_reason"]
    assert row["refuted_evidence"]
    audits = {r["op"] for r in conn.execute(
        "SELECT op FROM audit_log").fetchall()}
    assert {"refute", "refute_review", "curation_pass"} <= audits


def test_pass_keeps_doc_when_llm_says_no_and_never_rereviews(conn, cfg):
    _seed(conn)
    # DISTINCT bodies are load-bearing: with the default body both docs are
    # exact duplicates, the merge step fires BEFORE refute review and (equal
    # created_at, same txn) archives a random one of the pair — coin-flip
    # flakiness observed live during Task 11
    old = _doc(conn, "kept-claim", body="X is true")
    contra = _doc(conn, "contradiction-kept-claim", dtype="lesson",
                  body="session evidence says X is false")
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, dst_slug, predicate, created_by)"
        " VALUES (%s, %s, 'kept-claim', 'contradicts', 'mining')",
        (contra, old))
    conn.commit()
    rep1 = curation.run_pass(conn, cfg, runner=_refuse_runner)
    assert rep1.reviewed == 1 and rep1.refuted == 0
    def exploding(cmd, **kw):
        raise AssertionError("already-reviewed doc must not be re-reviewed")
    rep2 = curation.run_pass(conn, cfg, runner=exploding)
    assert rep2.reviewed == 0
    st = conn.execute("SELECT status FROM documents WHERE slug='kept-claim'"
                      ).fetchone()["status"]
    assert st == "active"


def test_pass_respects_budget(conn, cfg):
    _seed(conn)
    for i in range(4):
        _doc(conn, f"dup-{i}-a", body=f"same {i}")
        _doc(conn, f"dup-{i}-b", body=f"same {i}")
    rep = curation.run_pass(conn, cfg, budget=2, runner=_refuse_runner)
    assert rep.merged == 2                      # budget caps the pass
    rep2 = curation.run_pass(conn, cfg, budget=10, runner=_refuse_runner)
    assert rep2.merged == 2                     # the rest next pass


def test_purge_deletes_only_old_refuted(conn, cfg):
    _seed(conn)
    old = _doc(conn, "old-refuted")
    fresh = _doc(conn, "fresh-refuted")
    keeper = _doc(conn, "active-doc")
    for slug, doc_id, days in (("old-refuted", old, 40), ("fresh-refuted", fresh, 5)):
        conn.execute(
            "INSERT INTO edges(src_id, dst_id, dst_slug, predicate,"
            " created_by) VALUES (%s, %s, %s, 'contradicts', 'manual')",
            (keeper, doc_id, slug))
        conn.execute(
            "INSERT INTO audit_log(actor, op, document_id, summary)"
            " VALUES ('cli', 'refute', %s, 'test')", (doc_id,))
        conn.execute(
            "UPDATE documents SET status='refuted', refuted_reason='r',"
            " refuted_evidence='e',"
            " refuted_at = now() - make_interval(days => %s)"
            " WHERE id = %s", (days, doc_id))
    conn.commit()
    with pytest.raises(RuntimeError):
        curation.purge(conn, older_days=30)
    admin = db.connect(cfg, role="admin")
    try:
        n = curation.purge(admin, older_days=30, assume_yes=True)
    finally:
        admin.close()
    assert n == 1
    slugs = {r["slug"] for r in conn.execute(
        "SELECT slug FROM documents").fetchall()}
    assert "old-refuted" not in slugs
    assert {"fresh-refuted", "active-doc"} <= slugs


def test_review_report_lists_worklists(conn, cfg):
    _seed(conn)
    a = _doc(conn, "a")
    _doc(conn, "b")
    conn.execute(
        "INSERT INTO edges(src_id, dst_slug, predicate, created_by)"
        " VALUES (%s, 'missing-doc', 'references', 'mining')", (a,))
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary)"
        " VALUES ('mining', 'pin_suggestion', '[global] test rule — said')")
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES"
        " ('mining', 'pin_contradiction', 'pin: calibration rule — violated')")
    conn.execute(
        "INSERT INTO pins(body, last_verified)"
        " VALUES ('ancient rule', now() - interval '90 days')")
    conn.commit()
    rep = curation.review_report(conn, cfg)
    assert any(d["dst_slug"] == "missing-doc" for d in rep["dangling"])
    assert any("test rule" in s["summary"] for s in rep["suggestions"])
    assert any(s["op"] == "pin_contradiction" for s in rep["suggestions"])
    assert any(p["body"] == "ancient rule" for p in rep["stale_pins"])
