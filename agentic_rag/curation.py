"""Bounded, justified curation (spec §7). Runs ONLY inside the single writer.

Allowed actions: resolve dangling links (deterministic), merge exact
duplicates (identical body within a domain — the newer copy is archived with
a duplicate_of edge, content is identical so nothing is lost), review mined
contradictions (one Haiku call each; refuting requires reason + evidence +
edge + audit row — the 005 constraint trigger rejects anything less), and an
audit stamp per pass. Pins are never touched. Hard deletion happens only in
purge(), on an admin connection, for refuted > older_days.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .config import Config
from .llm import run_structured

REFUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "refute": {"type": "boolean"},
        "reason": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["refute", "reason", "quote"],
    "additionalProperties": False,
}

REFUTE_SYSTEM = (
    "You review ONE stored knowledge document against contradicting session "
    "evidence. Answer refute=true ONLY when the evidence clearly shows the "
    "stored document is wrong or outdated; when in doubt, refute=false. "
    "On refute=true give a one-sentence reason and the literal evidence "
    "quote."
)


@dataclass(frozen=True)
class CurationReport:
    dangling_resolved: int = 0
    merged: int = 0
    reviewed: int = 0
    refuted: int = 0


def _resolve_dangling(conn) -> int:
    return conn.execute(
        "UPDATE edges e SET dst_id = d.id FROM documents d"
        " WHERE e.dst_id IS NULL AND d.slug = e.dst_slug"
        " AND d.id <> e.src_id"
    ).rowcount


def _lock_scope_pair(conn, first, second, expected_scope):
    """Revalidate under ordered row locks before applying a planned mutation."""
    rows = conn.execute(
        "SELECT id,project_scope,status FROM documents WHERE id=ANY(%s::uuid[])"
        " ORDER BY id FOR UPDATE", ([str(first),str(second)],)).fetchall()
    return (len(rows)==2 and expected_scope != 'unknown'
            and all(r['status']=='active' and r['project_scope']==expected_scope for r in rows))


def _merge_exact_duplicates(conn, budget: int) -> int:
    """Archive newer exact-body copies within a domain (budgeted)."""
    if budget <= 0:
        return 0
    rows = conn.execute(
        "SELECT d2.id AS dup_id, d2.slug AS dup_slug, d1.slug AS keep_slug,"
        " d1.id AS keep_id, d1.project_scope AS expected_scope"
        " FROM documents d1 JOIN documents d2"
        "   ON d1.domain = d2.domain AND d1.body = d2.body"
        "   AND d1.project_scope = d2.project_scope AND d1.project_scope <> 'unknown'"
        "   AND d1.id <> d2.id AND d1.created_at <= d2.created_at"
        "   AND (d1.created_at < d2.created_at OR d1.id < d2.id)"
        " WHERE d1.status = 'active' AND d2.status = 'active'"
        " AND NOT EXISTS (SELECT 1 FROM fact_assertions a WHERE a.document_id IN (d1.id,d2.id))"
        " AND NOT EXISTS (SELECT 1 FROM claim_records c WHERE c.document_id IN (d1.id,d2.id))"
        " AND d1.body <> ''"
        " ORDER BY d2.created_at LIMIT %s", (budget,)).fetchall()
    applied = 0
    for r in rows:
        if not _lock_scope_pair(conn,r["dup_id"],r["keep_id"],r["expected_scope"]):
            continue
        conn.execute(
            "UPDATE documents SET status = 'archived' WHERE id = %s",
            (r["dup_id"],))
        conn.execute(
            "INSERT INTO edges(src_id, dst_id, dst_slug, predicate,"
            " evidence, created_by)"
            " SELECT %s, d.id, %s, 'duplicate_of',"
            "        'exact body duplicate, archived by curation', 'mining'"
            " FROM documents d WHERE d.slug = %s"
            " ON CONFLICT (src_id, dst_slug, predicate) DO NOTHING",
            (r["dup_id"], r["keep_slug"], r["keep_slug"]))
        conn.execute(
            "INSERT INTO audit_log(actor, op, document_id, summary)"
            " VALUES ('mining', 'curation_merge', %s, %s)",
            (r["dup_id"],
             f"archived exact duplicate '{r['dup_slug']}'"
             f" of '{r['keep_slug']}'"))
        applied += 1
    return applied


def _refute_candidates(conn, limit: int) -> list[dict]:
    """Active docs with an incoming mined `contradicts` edge and no
    refute_review audit row after that edge appeared — the deterministic
    worklist mining produces."""
    if limit <= 0:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT DISTINCT ON (d.id) d.id, d.slug, d.title, d.body,"
        "       e.evidence, src.body AS contra_body, src.id AS source_id,"
        "       d.project_scope AS expected_scope, e.created_at AS evidence_at"
        " FROM documents d"
        " JOIN edges e ON e.dst_id = d.id AND e.predicate = 'contradicts'"
        "   AND e.created_by = 'mining'"
        " JOIN documents src ON src.id = e.src_id"
        " AND src.project_scope = d.project_scope AND d.project_scope <> 'unknown'"
        " WHERE d.status = 'active' AND src.status = 'active'"
        " AND NOT EXISTS (SELECT 1 FROM fact_assertions a WHERE a.document_id IN (d.id,src.id))"
        " AND NOT EXISTS (SELECT 1 FROM claim_records c WHERE c.document_id IN (d.id,src.id))"
        " AND (d.reactivated_at IS NULL OR e.created_at > d.reactivated_at)"
        " AND NOT EXISTS ("
        "   SELECT 1 FROM audit_log a WHERE a.document_id = d.id"
        "   AND a.op = 'refute_review' AND a.at >= e.created_at)"
        " ORDER BY d.id, e.created_at LIMIT %s", (limit,)).fetchall()]


def _review_refutes(conn, cfg: Config, budget: int, runner) -> tuple[int, int]:
    reviewed = refuted = 0
    for c in _refute_candidates(conn, budget):
        prompt = (
            f"STORED DOCUMENT '{c['slug']}' — {c['title']}:\n{c['body']}\n\n"
            f"CONTRADICTING EVIDENCE (mined from a session):\n"
            f"{c['contra_body']}\n\n"
            f"Edge evidence: {c['evidence'] or '(none)'}\n\n"
            "Should the stored document be refuted?")
        data = run_structured(prompt, REFUTE_SCHEMA, cfg,
                              system=REFUTE_SYSTEM, runner=runner)
        if not _lock_scope_pair(conn,c["id"],c["source_id"],c["expected_scope"]):
            continue
        epoch=conn.execute('SELECT reactivated_at FROM documents WHERE id=%s',(c['id'],)).fetchone()['reactivated_at']
        if epoch is not None and c['evidence_at'] <= epoch:
            continue
        reviewed += 1
        if data.get("refute") and str(data.get("reason", "")).strip():
            reason = str(data["reason"]).strip()
            quote = str(data.get("quote", "")).strip() or "(see edge evidence)"
            conn.execute(
                "INSERT INTO audit_log(actor, op, document_id, summary)"
                " VALUES ('mining', 'refute', %s, %s)",
                (c["id"], f"refuted: {reason}"))
            conn.execute(
                "UPDATE documents SET status='refuted', refuted_reason=%s,"
                " refuted_evidence=%s, refuted_at=now() WHERE id=%s",
                (reason, quote, c["id"]))
            refuted += 1
        conn.execute(
            "INSERT INTO audit_log(actor, op, document_id, summary)"
            " VALUES ('mining', 'refute_review', %s, %s)",
            (c["id"], "reviewed" + (": refuted" if data.get("refute")
                                    else ": kept")))
    return reviewed, refuted


def run_pass(conn, cfg: Config, *, budget: int | None = None,
             runner=subprocess.run) -> CurationReport:
    budget = cfg.curation_budget if budget is None else budget
    dangling = _resolve_dangling(conn)
    merged = _merge_exact_duplicates(conn, budget)
    reviewed, refuted = _review_refutes(conn, cfg, budget - merged, runner)
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary)"
        " VALUES ('mining', 'curation_pass', %s)",
        (f"dangling={dangling} merged={merged} reviewed={reviewed}"
         f" refuted={refuted}",))
    conn.commit()
    return CurationReport(dangling, merged, reviewed, refuted)


def purge(admin_conn, *, older_days: int = 30,
          assume_yes: bool = False) -> int:
    """Two-stage deletion, stage two (spec §7): hard-delete documents refuted
    more than older_days ago. Admin connection required — the writer role
    cannot DELETE by construction. Never called by automation."""
    if not assume_yes:
        raise RuntimeError(
            "purge requires explicit confirmation (assume_yes=True)")
    rows = admin_conn.execute(
        "DELETE FROM documents WHERE status = 'refuted'"
        " AND refuted_at < now() - make_interval(days => %s)"
        " RETURNING slug", (older_days,)).fetchall()
    admin_conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES ('cli', 'purge', %s)",
        (f"hard-deleted {len(rows)} refuted docs (older than {older_days}d):"
         f" {', '.join(r['slug'] for r in rows)[:400]}",))
    admin_conn.commit()
    return len(rows)


def review_report(conn, cfg: Config) -> dict:
    """The on-demand human/Claude worklist for `rag review` (spec §7)."""
    duplicate_candidates = [dict(r) for r in conn.execute(
        "SELECT s.slug AS src_slug, e.dst_slug, e.evidence"
        " FROM edges e JOIN documents s ON s.id = e.src_id"
        " JOIN documents t ON t.id = e.dst_id"
        " WHERE e.predicate = 'duplicate_of'"
        " AND s.status = 'active' AND t.status = 'active'"
        " AND s.project_scope = t.project_scope AND s.project_scope <> 'unknown'"
        " ORDER BY e.created_at DESC LIMIT 50").fetchall()]
    dangling = [dict(r) for r in conn.execute(
        "SELECT s.slug AS src_slug, e.dst_slug, e.predicate"
        " FROM edges e JOIN documents s ON s.id = e.src_id"
        " WHERE e.dst_id IS NULL ORDER BY e.created_at DESC LIMIT 50"
    ).fetchall()]
    stale_pins = [dict(r) for r in conn.execute(
        "SELECT id, body, scope,"
        "       COALESCE(last_verified, created_at) AS anchor"
        " FROM pins WHERE active"
        " AND COALESCE(last_verified, created_at)"
        "     < now() - make_interval(days => %s)"
        " ORDER BY anchor", (cfg.stale_days,)).fetchall()]
    suggestions = [dict(r) for r in conn.execute(
        "SELECT op, summary, at FROM audit_log"
        " WHERE op IN ('pin_suggestion', 'domain_proposal',"
        "              'pin_contradiction')"
        " ORDER BY at DESC LIMIT 30").fetchall()]
    queue_errors = [dict(r) for r in conn.execute(
        "SELECT id, kind, session_id, attempts, last_error"
        " FROM mining_queue WHERE status = 'error' ORDER BY id"
    ).fetchall()]
    unknown_scopes = [dict(r) for r in conn.execute(
        "SELECT id, slug FROM documents WHERE project_scope = 'unknown' ORDER BY slug LIMIT 100").fetchall()]
    unknown_count = conn.execute("SELECT count(*) AS n FROM documents WHERE project_scope = 'unknown'").fetchone()["n"]
    temporal_review = [dict(r) for r in conn.execute(
        "SELECT d.slug,a.* FROM fact_assertions a JOIN documents d ON d.id=a.document_id"
        " WHERE a.disposition='review' ORDER BY d.created_at DESC LIMIT 100").fetchall()]
    from .evidence import summary
    claim_review=[{'slug':r['slug'],**summary(conn,str(r['id']))} for r in conn.execute(
        "SELECT d.id,d.slug FROM documents d JOIN claim_records c ON c.document_id=d.id"
        " WHERE c.review_state<>'confirmed' OR NOT claim_eligible(d.id) ORDER BY d.created_at DESC LIMIT 100").fetchall()]
    return {"claim_review":claim_review,"temporal_review": temporal_review, "unknown_scopes": unknown_scopes, "unknown_scope_count": unknown_count,
            "duplicate_candidates": duplicate_candidates,
            "dangling": dangling, "stale_pins": stale_pins,
            "suggestions": suggestions, "queue_errors": queue_errors}
