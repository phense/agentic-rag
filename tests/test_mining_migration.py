import pytest
import psycopg

from agentic_rag import db
from agentic_rag.benchmark.database import isolated_database


def test_additive_upgrade_preserves_existing_queue_and_is_idempotent(cfg, tmp_path):
    # Exercise the real 008 -> 009 boundary without removing later shared RLS.
    staged = tmp_path / 'legacy-migrations'
    staged.mkdir()
    paths = sorted(db.SQL_DIR.glob('*.sql'))[:9]
    for path in paths[:8]:
        (staged / path.name).write_text(path.read_text())
    with isolated_database(cfg, initialize=False) as owned:
        with db.connect(owned) as conn:
            db.apply_migrations(conn, staged)
            job = conn.execute("INSERT INTO mining_queue(session_id,last_uuid,payload) VALUES ('legacy','old-uuid','{\"project\":\"/legacy\"}') RETURNING id").fetchone()['id']
            conn.commit()
            (staged / paths[8].name).write_text(paths[8].read_text())
            assert db.apply_migrations(conn, staged) == ['009_mining_batches.sql']
            row = conn.execute('SELECT session_id,last_uuid,payload,status,attempts FROM mining_queue WHERE id=%s',(job,)).fetchone()
            assert dict(row) == {'session_id':'legacy','last_uuid':'old-uuid','payload':{'project':'/legacy'},'status':'pending','attempts':0}
            assert db.apply_migrations(conn, staged) == []


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
