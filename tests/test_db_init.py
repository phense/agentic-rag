import psycopg
import pytest

from agentic_rag import db
from agentic_rag.config import Config


def test_migrations_applied_and_recorded(conn):
    rows = conn.execute("SELECT filename FROM schema_migrations ORDER BY 1").fetchall()
    names = [r["filename"] for r in rows]
    assert "001_init.sql" in names


def test_migrations_are_idempotent(conn):
    applied = db.apply_migrations(conn, db.SQL_DIR)
    assert applied == []  # nothing pending on second run


def test_core_tables_exist(conn):
    for table in ["domains", "documents", "chunks", "edges", "pins",
                  "mining_queue", "audit_log", "continuation_checkpoints"]:
        assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0


def test_embedding_dim_matches_config(conn, cfg):
    row = conn.execute(
        "SELECT atttypmod AS dim FROM pg_attribute "
        "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    ).fetchone()
    assert row["dim"] == cfg.embed_dim


def test_refuted_requires_justification(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('t')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title) VALUES ('x','t','concept','X')"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE documents SET status = 'refuted' WHERE slug = 'x'")


def test_005_next_attempt_at_exists(conn):
    row = conn.execute(
        "SELECT column_default FROM information_schema.columns"
        " WHERE table_name = 'mining_queue'"
        " AND column_name = 'next_attempt_at'").fetchone()
    assert row is not None


def test_006_continuity_schema_and_queue_kind_exist(conn):
    columns = {
        row["column_name"]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'continuation_checkpoints'"
        ).fetchall()
    }
    assert {"session_id", "turn_id", "cursor", "transcript_fingerprint", "cwd",
            "project_root", "git", "snapshot", "enrichment", "references",
            "warnings", "state", "quality", "compacted_at", "created_at",
            "updated_at"} <= columns
    conn.execute("INSERT INTO mining_queue(kind) VALUES ('checkpoint_enrich')")


def test_refute_without_edge_and_audit_fails_at_commit(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('doomed', 'd', 'memory', 'T')")
    conn.commit()
    conn.execute(
        "UPDATE documents SET status='refuted', refuted_reason='r',"
        " refuted_evidence='e', refuted_at=now() WHERE slug='doomed'")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.commit()
    conn.rollback()


def test_refute_with_edge_and_audit_commits(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    ids = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('old-claim', 'd', 'memory', 'Old'),"
        "        ('new-evidence', 'd', 'lesson', 'New')"
        " RETURNING id").fetchall()
    old_id, new_id = ids[0]["id"], ids[1]["id"]
    conn.execute(
        "UPDATE documents SET status='refuted', refuted_reason='contradicted',"
        " refuted_evidence='quote', refuted_at=now() WHERE id=%s", (old_id,))
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, dst_slug, predicate, created_by)"
        " VALUES (%s, %s, 'old-claim', 'contradicts', 'mining')",
        (new_id, old_id))
    conn.execute(
        "INSERT INTO audit_log(actor, op, document_id, summary)"
        " VALUES ('mining', 'refute', %s, 'refuted by new-evidence')",
        (old_id,))
    conn.commit()   # deferred trigger satisfied — must not raise
    row = conn.execute(
        "SELECT status FROM documents WHERE id=%s", (old_id,)).fetchone()
    assert row["status"] == "refuted"


def test_recall_signals_matches_signal_docs_only(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body) VALUES"
        " ('sig-jetsam', 'd', 'signal', 'Jetsam OOM',"
        "  'signal: jetsam killed process memory pressure'),"
        " ('note-jetsam', 'd', 'memory', 'Note',"
        "  'jetsam mentioned in a plain memory')")
    for slug in ("sig-jetsam", "note-jetsam"):
        doc = conn.execute(
            "SELECT id FROM documents WHERE slug=%s", (slug,)).fetchone()
        conn.execute(
            "INSERT INTO chunks(document_id, idx, content)"
            " SELECT id, 0, body FROM documents WHERE slug=%s", (slug,))
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM recall_signals('jetsam | nonexistenttoken', 3)"
    ).fetchall()
    assert [r["slug"] for r in rows] == ["sig-jetsam"]


def test_init_db_rejects_non_1024_dim():
    with pytest.raises(RuntimeError, match="1024"):
        db.init_db(Config(embed_dim=768))
