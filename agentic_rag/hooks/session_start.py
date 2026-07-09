"""SessionStart hook (spec §5, mechanism 1) — fail-closed-VISIBLE.

Injects: ALL matching pins (no cap; explicit warning when over budget), the
domain map, project-relevant documents, and every operational warning
(backup fallback, queue errors). On ANY error the hook still injects
'agentic-rag unavailable: <reason>' — absence of knowledge is always
visible, never silent (the ultra-memory fail-open lesson). Also the daily
curation trigger: last curation > 24 h → enqueue a curate job and spawn the
worker; and any due jobs → spawn the worker (mining tail pickup)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from .. import db, jobs
# module attribute so tests can monkeypatch session_start.WARNING_STATE
from ..backup import WARNING_STATE
from ..config import Config, load_config
from ..domains import list_domains
from ..pins import matching_pins, render_pins
from . import common

CURATION_MAX_AGE_H = 24


def build_context(conn, cfg: Config, cwd: str | None) -> str:
    parts: list[str] = ["# agentic-rag memory"]
    warnings: list[str] = []

    if WARNING_STATE.exists():
        warnings.append(f"⚠️ backup: {WARNING_STATE.read_text().strip()}")
    n_err = conn.execute(
        "SELECT count(*) AS n FROM mining_queue WHERE status = 'error'"
    ).fetchone()["n"]
    if n_err:
        warnings.append(
            f"⚠️ {n_err} queue job(s) in error state — see `rag status`")

    pin_list = matching_pins(conn, cwd)
    if pin_list:
        text, pin_warnings = render_pins(
            pin_list, stale_days=cfg.stale_days,
            budget_chars=cfg.pin_budget_chars)
        warnings.extend(f"⚠️ {w}" for w in pin_warnings)
        parts.append("## Pinned rules (all of them — pins are law)\n" + text)

    domain_list = list_domains(conn)
    if domain_list:
        parts.append("## Knowledge domains (memory_search accepts domain=)\n"
                     + "\n".join(f"- {d.name} ({d.docs} docs) — "
                                 f"{d.description}" for d in domain_list))

    if cwd:
        # same path-prefix semantics as pins.matching_pins — a session in a
        # SUBDIRECTORY of the mined project must still see its knowledge
        rows = conn.execute(
            "SELECT slug, title, dtype,"
            "       COALESCE(verified_at, updated_at) AS ts"
            " FROM documents WHERE status = 'active'"
            " AND ((provenance->>'project' IS NOT NULL"
            "       AND (%(cwd)s = provenance->>'project'"
            "            OR %(cwd)s LIKE provenance->>'project' || '/%%'))"
            "      OR id IN (SELECT document_id FROM pins"
            "                WHERE active AND document_id IS NOT NULL"
            "                AND scope LIKE '/%%'"
            "                AND (%(cwd)s = scope"
            "                     OR %(cwd)s LIKE scope || '/%%')))"
            " ORDER BY COALESCE(verified_at, updated_at) DESC"
            " LIMIT %(k)s", {"cwd": cwd, "k": cfg.context_docs}).fetchall()
        if rows:
            parts.append(
                "## Recent knowledge for this project (memory_get <slug>)\n"
                + "\n".join(f"- [[{r['slug']}]] {r['title']} ({r['dtype']},"
                            f" {r['ts']:%Y-%m-%d})" for r in rows))

    if warnings:
        parts.insert(1, "\n".join(warnings))
    return "\n\n".join(parts)


def _trigger_maintenance(conn) -> None:
    """Daily curation guarantee (spec §7) + mining-tail pickup. Never runs
    work in-process — enqueue and spawn only."""
    last = jobs.last_curation_at(conn)
    spawn = False
    if last is None or (datetime.now(timezone.utc) - last
                        > timedelta(hours=CURATION_MAX_AGE_H)):
        jobs.enqueue_curate(conn, reason="stale (>24h) at SessionStart")
        spawn = True
    if jobs.due_jobs_exist(conn):
        spawn = True
    if spawn:
        common.spawn_worker()


def run(payload: dict, stdout) -> None:
    if not common.is_interactive(payload):
        return
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            text = build_context(conn, cfg, payload.get("cwd"))
            _trigger_maintenance(conn)
        finally:
            conn.close()
        common.emit_context(stdout, "SessionStart", text)
    except Exception as e:  # noqa: BLE001 — fail closed, VISIBLY
        common.log_hook_error("session_start", repr(e))
        common.emit_context(
            stdout, "SessionStart",
            f"⚠️ agentic-rag unavailable: {type(e).__name__}: {e}")


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
