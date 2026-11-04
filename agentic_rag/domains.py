"""Domains as data: the 'where can I look' map (spec §4). Absorbed from cli.py."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainInfo:
    name: str
    description: str
    docs: int


def add_domain(conn, name: str, description: str = "", actor: str = "cli") -> None:
    conn.execute(
        "INSERT INTO domains(name, description) VALUES (%s, %s)"
        " ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
        (name, description),
    )
    conn.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES (%s,%s,%s)",
        (actor, "domain_add",
         f"domain '{name}' ({description or 'no description'})"),
    )
    conn.commit()


def seed_defaults(conn) -> None:
    """Ensure the always-available 'general' domain exists so a fresh install
    can `rag save` before defining any domains. Idempotent."""
    add_domain(conn, "general", "Uncategorized knowledge", actor="init")


def list_domains(conn, *, filter=None, cfg=None,project=None,scope=None) -> list[DomainInfo]:
    if filter is not None:
        from .config import load_config
        from .metadata import filtered,argument
        from .scope import selection
        scopes=selection(project,scope)
        with filtered(conn,cfg or load_config(),filter,scopes=scopes) as selected:
            rows=conn.execute("SELECT d.name,d.description,count(doc.id) docs FROM domains d LEFT JOIN documents doc ON doc.domain=d.name AND doc.status='active' AND assertion_eligible(doc.id) AND (%s::text[] IS NULL OR doc.project_scope=ANY(%s)) AND public.rag_metadata_document(doc.id,%s) GROUP BY d.name,d.description ORDER BY d.name",(scopes,scopes,argument(selected))).fetchall()
        return [DomainInfo(r["name"],r["description"],r["docs"]) for r in rows]
    from .service.read_limits import rows as bounded_rows
    rows = bounded_rows(conn,
        "SELECT d.name, d.description, count(doc.id) AS docs"
        " FROM domains d LEFT JOIN documents doc"
        "   ON doc.domain = d.name AND doc.status = 'active'"
        " GROUP BY d.name, d.description ORDER BY d.name"
    )
    return [DomainInfo(r["name"], r["description"], r["docs"]) for r in rows]
