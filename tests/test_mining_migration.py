import pytest
import psycopg

from agentic_rag import db


def test_additive_upgrade_preserves_existing_queue_and_is_idempotent(conn):
    # Only the dedicated test database is used. Reconstruct the pre-009 boundary.
    assert conn.info.dbname == 'agentic_rag_test'
    conn.execute('DROP TABLE mining_batches')
    conn.execute("DELETE FROM schema_migrations WHERE filename='009_mining_batches.sql'")
    job = conn.execute("INSERT INTO mining_queue(session_id,last_uuid,payload) VALUES ('legacy','old-uuid','{\"project\":\"/legacy\"}') RETURNING id").fetchone()['id']
    conn.commit()
    assert db.apply_migrations(conn,db.SQL_DIR) == ['009_mining_batches.sql']
    row = conn.execute('SELECT session_id,last_uuid,payload,status,attempts FROM mining_queue WHERE id=%s',(job,)).fetchone()
    assert dict(row) == {'session_id':'legacy','last_uuid':'old-uuid','payload':{'project':'/legacy'},'status':'pending','attempts':0}
    assert db.apply_migrations(conn,db.SQL_DIR) == []


def test_batch_roles_retain_non_destructive_privileges(conn,cfg):
    reader=db.connect(cfg,role='reader')
    writer=db.connect(cfg,role='writer')
    try:
        assert reader.execute('SELECT count(*) AS n FROM mining_batches').fetchone()['n'] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("UPDATE mining_batches SET result='{}'")
        for statement in ['DELETE FROM mining_batches','TRUNCATE mining_batches','DROP TABLE mining_batches']:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                writer.execute(statement)
            writer.rollback()
    finally:
        reader.close()
        writer.close()
