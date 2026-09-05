"""Pins: user-owned standing rules, injected at SessionStart (spec §4/§5).

No cap ever; deterministic order (priority, then created_at — never
updated_at). Automation may never create/change/delete a pin — the only
writers are the user (CLI) and Claude acting on the user's explicit
instruction (MCP), both of which land here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class PinInfo:
    id: str
    document_id: str | None
    body: str
    scope: str
    priority: int
    active: bool
    created_at: datetime
    last_verified: datetime | None


def _validate_scope(conn, scope: str) -> None:
    """global | existing domain | absolute path — anything else is stored
    raw today and then silently never matches (live-smoke find 2026-07-05)."""
    if scope == "global" or scope.startswith("/"):
        return
    if conn.execute("SELECT 1 FROM domains WHERE name = %s",
                    (scope,)).fetchone():
        return
    raise ValueError(
        f"invalid pin scope {scope!r}: must be 'global', an existing domain,"
        " or an absolute project path")


def add_pin(conn, *, body: str | None = None, document_id: str | None = None,
            scope: str = "global", priority: int = 100,
            actor: str = "cli") -> str:
    from .scope import path_anchor
    _validate_scope(conn, scope)
    canonical_path = path_anchor(scope) if scope.startswith("/") else None
    if body is None and document_id is None:
        raise ValueError("a pin needs body text or a document_id")
    if body is None:
        row = conn.execute(
            "SELECT slug, title FROM documents WHERE id = %s",
            (document_id,)).fetchone()
        if row is None:
            raise ValueError(f"no such document: {document_id}")
        body = f"[[{row['slug']}]] — {row['title']}"
    row = conn.execute(
        "INSERT INTO pins(document_id, body, scope, priority, scope_path)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (document_id, body, scope, priority, canonical_path)).fetchone()
    pin_id = str(row["id"])
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
        (actor, "pin_add", f"pin {pin_id} [{scope}] {body[:120]}"))
    conn.commit()
    return pin_id


def unpin(conn, pin_id: str, actor: str = "cli") -> bool:
    n = conn.execute(
        "UPDATE pins SET active = false WHERE id = %s AND active",
        (pin_id,)).rowcount
    if n:
        conn.execute(
            "INSERT INTO audit_log(actor, op, summary) VALUES (%s, %s, %s)",
            (actor, "pin_remove", f"pin {pin_id} deactivated"))
    conn.commit()
    return bool(n)


def verify_pin(conn, pin_id: str) -> bool:
    n = conn.execute(
        "UPDATE pins SET last_verified = now() WHERE id = %s AND active",
        (pin_id,)).rowcount
    conn.commit()
    return bool(n)


def matching_pins(conn, project_dir: str | None) -> list[PinInfo]:
    """Active pins for SessionStart: global + path-prefix scopes.

    Domain-scoped pins are deliberately NOT matched here — no domain is
    knowable from a cwd; they surface via rag pin list / rag review.
    """
    from .scope import pin_paths
    rows = conn.execute(
        "SELECT * FROM pins WHERE active"
        " AND (scope = 'global' OR COALESCE(scope_path, scope) = ANY(%s))"
        " ORDER BY priority, created_at", (pin_paths(project_dir),)).fetchall()
    return [
        PinInfo(str(r["id"]), _s(r["document_id"]), r["body"], r["scope"],
                r["priority"], r["active"], r["created_at"],
                r["last_verified"])
        for r in rows
    ]


def list_pins(conn, include_inactive: bool = False) -> list[PinInfo]:
    rows = conn.execute(
        "SELECT * FROM pins WHERE active OR %s ORDER BY priority, created_at",
        (include_inactive,)).fetchall()
    return [
        PinInfo(str(r["id"]), _s(r["document_id"]), r["body"], r["scope"],
                r["priority"], r["active"], r["created_at"],
                r["last_verified"])
        for r in rows
    ]


def render_pins(pin_list: list[PinInfo], *, stale_days: int,
                budget_chars: int, today: date | None = None
                ) -> tuple[str, list[str]]:
    """Render ALL pins (no cap, spec §5); stale ones get an explicit marker;
    an over-budget total produces a WARNING, never silent folding."""
    today = today or date.today()
    lines = []
    for p in pin_list:
        anchor = (p.last_verified or p.created_at).date()
        marker = ""
        if (today - anchor).days > stale_days:
            marker = f" (unverified since {anchor.isoformat()})"
        scope = "" if p.scope == "global" else f" [{p.scope}]"
        lines.append(f"- {p.body}{scope}{marker}")
    text = "\n".join(lines)
    warnings = []
    if len(text) > budget_chars:
        warnings.append(
            f"pins exceed the injection budget ({len(text)} chars > "
            f"{budget_chars}) — please curate pins (rag pin list); "
            f"ALL pins were still injected")
    return text, warnings


def _s(v) -> str | None:
    return str(v) if v is not None else None


def refresh_scope_paths(conn) -> int:
    """Repair derived path anchors only; caller owns transaction, raw pins unchanged."""
    from .scope import path_anchor
    count = 0
    for row in conn.execute("SELECT id,scope,scope_path FROM pins WHERE left(scope,1)='/'").fetchall():
        value = path_anchor(row['scope'])
        changed = conn.execute(
            'UPDATE pins SET scope_path=%s WHERE id=%s AND scope=%s'
            ' AND scope_path IS DISTINCT FROM %s',
            (value,row['id'],row['scope'],value)).rowcount
        if changed:
            conn.execute('INSERT INTO audit_log(actor,op,summary) VALUES (%s,%s,%s)',
                         ('migration','pin_scope_path',f"normalized derived path for pin {row['id']}"))
        count += changed
    return count
