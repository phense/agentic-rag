"""Connections (role-scoped) and the SQL-file migration runner."""
from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import Config

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

_ROLE_USERS = {"owner": None, "reader": "rag_reader",
               "writer": "rag_writer", "admin": "rag_admin"}


def dsn(cfg: Config, role: str = "owner", dbname: str | None = None) -> str:
    parts = [f"dbname={dbname or cfg.db_name}"]
    if cfg.db_host:
        parts.append(f"host={cfg.db_host}")
    user = _ROLE_USERS[role]
    if user:
        parts.append(f"user={user}")
    return " ".join(parts)


def connect(cfg: Config, role: str = "owner",
            dbname: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn(cfg, role, dbname), row_factory=dict_row)


def apply_migrations(conn: psycopg.Connection, sql_dir: Path) -> list[str]:
    """Apply pending sql/*.sql in filename order; all pending files commit
    together (one transaction on a non-autocommit connection)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {
        r["filename"]
        for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()
    }
    applied: list[str] = []
    for f in sorted(sql_dir.glob("*.sql")):
        if f.name in done:
            continue
        conn.execute(f.read_text())
        conn.execute(
            "INSERT INTO schema_migrations(filename) VALUES (%s)", (f.name,)
        )
        applied.append(f.name)
    if not conn.autocommit:
        conn.commit()
    return applied


def init_db(cfg: Config, sql_dir: Path = SQL_DIR) -> list[str]:
    """Create the database if missing, then apply pending migrations."""
    if cfg.embed_dim != 1024:
        raise RuntimeError(
            f"embed_dim={cfg.embed_dim} but the schema fixes embeddings at "
            f"halfvec(1024) (bge-m3). To use another dimension, regenerate "
            f"sql/001_init.sql for that size first.")
    admin = psycopg.connect(dsn(cfg, "owner", dbname="postgres"), autocommit=True)
    exists = admin.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (cfg.db_name,)
    ).fetchone()
    if not exists:
        admin.execute(f'CREATE DATABASE "{cfg.db_name}"')
    admin.close()
    conn = connect(cfg, role="owner")
    try:
        applied = apply_migrations(conn, sql_dir)
        from . import domains as domains_mod
        domains_mod.seed_defaults(conn)
        return applied
    finally:
        conn.close()
