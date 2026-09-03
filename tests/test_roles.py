import psycopg
import pytest

from agentic_rag import db


@pytest.fixture
def writer(dbinit, cfg, conn):
    # `conn` guarantees truncated tables; seed one row as owner
    conn.execute("INSERT INTO domains(name) VALUES ('t')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title) VALUES ('d1','t','concept','D1')"
    )
    conn.commit()
    w = db.connect(cfg, role="writer")
    yield w
    w.close()


def test_writer_can_insert_and_update(writer):
    writer.execute(
        "INSERT INTO documents(slug, domain, dtype, title) VALUES ('d2','t','lesson','D2')"
    )
    writer.execute("UPDATE documents SET title = 'D2b' WHERE slug = 'd2'")
    writer.commit()


def test_writer_cannot_delete_documents(writer):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("DELETE FROM documents WHERE slug = 'd1'")


def test_writer_cannot_truncate(writer):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("TRUNCATE documents CASCADE")


def test_writer_cannot_drop_table(writer):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("DROP TABLE documents CASCADE")


def test_audit_log_append_only_for_writer(writer):
    writer.execute(
        "INSERT INTO audit_log(actor, op, summary) VALUES ('t','test','x')"
    )
    writer.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("UPDATE audit_log SET summary = 'y'")
    writer.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("DELETE FROM audit_log")


def test_writer_cannot_delete_chunks_directly(writer):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("DELETE FROM chunks")


def test_writer_swaps_chunks_via_replace_chunks(writer):
    doc = writer.execute("SELECT id FROM documents WHERE slug = 'd1'").fetchone()
    writer.execute(
        "SELECT replace_chunks(%s, %s, %s)",
        (doc["id"], ["hello world"], [None]),
    )
    writer.commit()
    n = writer.execute(
        "SELECT count(*) AS n FROM chunks WHERE document_id = %s", (doc["id"],)
    ).fetchone()["n"]
    assert n == 1


def test_reader_is_select_only(dbinit, cfg):
    r = db.connect(cfg, role="reader")
    assert r.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] >= 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        r.execute("INSERT INTO domains(name) VALUES ('nope')")
    r.close()


def test_checkpoint_privileges_follow_the_writer_reader_matrix(dbinit, cfg):
    w = db.connect(cfg, role="writer")
    try:
        w.execute(
            "INSERT INTO continuation_checkpoints(session_id, cursor, source)"
            " VALUES ('roles-session', 'roles-cursor', 'PreCompact')"
        )
        w.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w.execute("DELETE FROM continuation_checkpoints")
        w.rollback()
    finally:
        w.close()

    r = db.connect(cfg, role="reader")
    try:
        assert r.execute("SELECT count(*) AS n FROM continuation_checkpoints").fetchone()["n"] >= 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            r.execute(
                "UPDATE continuation_checkpoints SET source = 'changed'"
            )
    finally:
        r.close()


def test_future_tables_inherit_reader_admin_grants(conn, cfg):
    conn.autocommit = True
    conn.execute("CREATE TABLE _future_probe (id int, note text)")
    conn.execute("INSERT INTO _future_probe VALUES (1, 'seed')")
    try:
        r = db.connect(cfg, role="reader")
        assert r.execute("SELECT count(*) AS n FROM _future_probe"
                         ).fetchone()["n"] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            r.execute("INSERT INTO _future_probe VALUES (2, 'r')")
        r.close()
        # writer rights are per-table BY DESIGN (§8 matrix) — no default.
        # A blanket writer default would be re-applied additively to every
        # table pg_restore --clean recreates (UPDATE on audit_log, INSERT
        # on chunks) — the restore path must never weaken the matrix.
        w = db.connect(cfg, role="writer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w.execute("INSERT INTO _future_probe VALUES (3, 'w')")
        w.close()
        a = db.connect(cfg, role="admin")
        a.autocommit = True
        a.execute("INSERT INTO _future_probe VALUES (4, 'a')")
        a.execute("DELETE FROM _future_probe WHERE id = 4")
        a.close()
    finally:
        conn.execute("DROP TABLE _future_probe")
        conn.autocommit = False


def test_admin_can_delete_where_writer_cannot(conn, cfg):
    # positive capability check (gate): the admin path rag purge relies on
    conn.execute("INSERT INTO domains(name) VALUES ('roles-d')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('purgeable', 'roles-d', 'memory', 'X')")
    conn.commit()
    a = db.connect(cfg, role="admin")
    a.execute("DELETE FROM documents WHERE slug = 'purgeable'")
    a.commit()
    a.close()
    assert conn.execute(
        "SELECT count(*) AS n FROM documents WHERE slug='purgeable'"
    ).fetchone()["n"] == 0
