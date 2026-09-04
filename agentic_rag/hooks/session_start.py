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

from .. import db, jobs, provider_health
# module attribute so tests can monkeypatch session_start.WARNING_STATE
from ..backup import WARNING_STATE
from ..config import MAX_CONTEXT_CHARS, Config, load_config
from ..continuity import capture, store
from ..continuity.render import MIN_RENDER_CHARS, render_checkpoint
from ..domains import list_domains
from ..pins import matching_pins, render_pins
from . import common

CURATION_MAX_AGE_H = 24
_TRIM_ORDER = ("knowledge", "domains", "checkpoint")
_TRUNCATED = ("⚠️ context truncated to fit the {limit}-char Claude hook limit: "
              "{detail}; see rag status")


def _join(parts: list[tuple[str, str]], warnings: list[str]) -> str:
    body = [text for _, text in parts]
    if warnings:
        body.insert(1, "\n".join(warnings))
    return "\n\n".join(body)


def fit_context(
    parts: list[tuple[str, str]], warnings: list[str], max_chars: int
) -> str:
    """Trim named sections (knowledge, domains, checkpoint, then pins) until
    the joined context fits ``max_chars``; every cut is announced up front."""
    kept = list(parts)
    notes = list(warnings)
    text = _join(kept, notes)
    if len(text) <= max_chars:
        return text
    dropped: list[str] = []
    for name in _TRIM_ORDER:
        if not any(part_name == name for part_name, _ in kept):
            continue
        kept = [part for part in kept if part[0] != name]
        dropped.append(name)
        text = _join(kept, notes + [_TRUNCATED.format(
            limit=max_chars, detail="dropped " + ", ".join(dropped))])
        if len(text) <= max_chars:
            return text
    # Pins are law: cut whole trailing pin lines, say how many, keep the rest.
    pin_index = next(
        (i for i, (name, _) in enumerate(kept) if name == "pins"), None)
    if pin_index is not None:
        heading, _, body = kept[pin_index][1].partition("\n")
        lines = body.split("\n")
        total = len(lines)
        while lines:
            lines.pop()
            detail = (
                f"{total - len(lines)} of {total} pins cut"
                + (f"; dropped {', '.join(dropped)}" if dropped else "")
                + " — curate pins (rag pin list)"
            )
            trial = kept[:pin_index] + [
                ("pins", heading + "\n" + "\n".join(lines))
            ] + kept[pin_index + 1:]
            text = _join(trial, notes + [
                _TRUNCATED.format(limit=max_chars, detail=detail)])
            if len(text) <= max_chars:
                return text
    detail = "hard cut" + (f"; dropped {', '.join(dropped)}" if dropped else "")
    warning = _TRUNCATED.format(limit=max_chars, detail=detail)
    text = _join(kept, notes + [warning])
    return text[:max_chars]


def _checkpoint_for_context(
        conn, *, cwd: str | None, session_id: str | None,
        source: str | None):
    checkpoint = None
    if isinstance(session_id, str) and session_id.strip():
        checkpoint = store.latest_for_session(conn, session_id)
    if checkpoint is not None or source not in {"startup", "resume"}:
        return checkpoint
    if not isinstance(cwd, str) or not cwd.strip() or not session_id:
        return None

    # Reuse the public capture boundary to discover and canonicalize the Git
    # project root.  This does not persist a new checkpoint.
    location = capture.capture_snapshot({
        "session_id": session_id,
        "hook_event_name": "SessionStart",
        "source": source,
        "cwd": cwd,
    })
    if location.project_root is None:
        return None
    return store.latest_for_project(conn, location.project_root)


def build_context(
        conn, cfg: Config, cwd: str | None, session_id: str | None = None,
        source: str | None = None) -> str:
    parts: list[tuple[str, str]] = [("header", "# agentic-rag memory")]
    warnings: list[str] = []

    if WARNING_STATE.exists():
        warnings.append(
            f"⚠️ backup: {common.sanitize_error(WARNING_STATE.read_text().strip())}")
    n_err = conn.execute(
        "SELECT count(*) AS n FROM mining_queue WHERE status = 'error'"
    ).fetchone()["n"]
    if n_err:
        warnings.append(
            f"⚠️ {n_err} queue job(s) in error state — see `rag status`")
    health = provider_health.read_health()
    if health is not None and not health.available:
        safe_provider = common.sanitize_error(health.provider)
        since = (
            f" since {health.first_failure_at:%Y-%m-%d %H:%M %Z}"
            if health.first_failure_at is not None else ""
        )
        remediation = (
            " — run `codex login`, then the next worker run resumes automatically"
            if health.provider == "codex" else " — see `rag status`"
        )
        warnings.append(
            f"⚠️ session mining provider {safe_provider} unavailable"
            f"{since}{remediation}")

    pin_list = matching_pins(conn, cwd)
    if pin_list:
        text, pin_warnings = render_pins(
            pin_list, stale_days=cfg.stale_days,
            budget_chars=cfg.pin_budget_chars)
        warnings.extend(f"⚠️ {w}" for w in pin_warnings)
        parts.append(
            ("pins", "## Pinned rules (all of them — pins are law)\n" + text))

    domain_list = list_domains(conn)
    if domain_list:
        parts.append((
            "domains",
            "## Knowledge domains (memory_search accepts domain=)\n"
            + "\n".join(f"- {d.name} ({d.docs} docs) — "
                        f"{d.description}" for d in domain_list),
        ))

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
            parts.append((
                "knowledge",
                "## Recent knowledge for this project (memory_get <slug>)\n"
                + "\n".join(f"- [[{r['slug']}]] {r['title']} ({r['dtype']},"
                            f" {r['ts']:%Y-%m-%d})" for r in rows),
            ))

    try:
        checkpoint = _checkpoint_for_context(
            conn, cwd=cwd, session_id=session_id, source=source)
        if checkpoint is not None:
            current_project_root = None
            if isinstance(cwd, str) and cwd.strip() and session_id:
                current_project_root = capture.capture_snapshot({
                    "session_id": session_id,
                    "hook_event_name": "SessionStart",
                    "source": source or "startup",
                    "cwd": cwd,
                }).project_root
            rendered = render_checkpoint(
                checkpoint,
                max_chars=max(MIN_RENDER_CHARS, cfg.checkpoint_render_max_chars),
                current_cwd=cwd,
                current_project_root=current_project_root,
                stale_days=cfg.stale_days,
            )
            parts.append(("checkpoint", "## Continuation checkpoint\n" + rendered))
    except Exception as exc:  # noqa: BLE001 — continuity is optional context
        common.log_hook_error("session_start.continuity", repr(exc))
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — the outer visible failure remains
            pass
        warnings.append(
            "⚠️ checkpoint restoration delayed: "
            + common.sanitize_error(f"{type(exc).__name__}: {exc}")
        )

    return fit_context(
        parts, warnings, min(cfg.context_max_chars, MAX_CONTEXT_CHARS))


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
            text = build_context(
                conn,
                cfg,
                payload.get("cwd"),
                session_id=payload.get("session_id"),
                source=payload.get("source"),
            )
            _trigger_maintenance(conn)
        finally:
            conn.close()
        common.emit_context(stdout, "SessionStart", text)
    except Exception as e:  # noqa: BLE001 — fail closed, VISIBLY
        common.log_hook_error("session_start", repr(e))
        safe_error = common.sanitize_error(f"{type(e).__name__}: {e}")
        common.emit_context(
            stdout, "SessionStart",
            f"⚠️ agentic-rag unavailable: {safe_error}")


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
