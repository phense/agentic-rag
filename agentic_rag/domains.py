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


def list_domains(conn) -> list[DomainInfo]:
    rows = conn.execute(
        "SELECT d.name, d.description, count(doc.id) AS docs"
        " FROM domains d LEFT JOIN documents doc"
        "   ON doc.domain = d.name AND doc.status = 'active'"
        " GROUP BY d.name, d.description ORDER BY d.name"
    ).fetchall()
    return [DomainInfo(r["name"], r["description"], r["docs"]) for r in rows]
