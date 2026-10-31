"""Custom default ACLs and role membership must not expose control state."""
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
import pytest

from agentic_rag import db,store
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service.schema import validate_schema,ServiceSchemaError


def test_control_state_strips_default_grants_and_rejects_later_exposure(tmp_path):
    cfg=Config(db_host='127.0.0.1',ollama_url='http://127.0.0.1:1')
    roles=['dashboard_acl_'+uuid.uuid4().hex[:12] for _ in range(3)]
    group,member,owner=roles
    with psycopg.connect(db.dsn(cfg,dbname='postgres'),autocommit=True) as admin:
        for role in roles:admin.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER').format(sql.Identifier(role)))
        try:
            with isolated_database(cfg,initialize=False) as owned:
                prefix=tmp_path/'prefix';prefix.mkdir()
                for f in sorted(db.SQL_DIR.glob('*.sql'))[:24]:(prefix/f.name).write_bytes(f.read_bytes())
                with db.connect(owned) as conn:
                    db.apply_migrations(conn,prefix)
                    conn.execute("INSERT INTO domains(name) VALUES ('general')");conn.commit()
                    doc=store.save_document(conn,owned,title='Retained ACL test',body='Synthetic retained knowledge',domain='general',dtype='memory')
                    before=conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl']
                    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE ON TABLES TO {}').format(sql.Identifier(group)))
                    conn.commit()
                    assert db.apply_migrations(conn,db.SQL_DIR)==['025_dashboard.sql','026_request_tracing.sql','027_provider_indexes.sql','028_reranker_settings.sql','029_source_evidence.sql','030_pattern_synthesis.sql','031_memory_lifecycle.sql']
                    assert conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl']==before
                    assert conn.execute('SELECT body FROM documents WHERE id=%s',(doc.doc_id,)).fetchone()['body']=='Synthetic retained knowledge'
                    for table in ('dashboard_changes','dashboard_setup','dashboard_presence','request_traces'):
                        assert not conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') exposed",(group,table)).fetchone()['exposed']
                    validate_schema(conn)
                    # A later grant to a group exposes state to all its members.
                    conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(group),sql.Identifier(member)))
                    conn.execute(sql.SQL('GRANT UPDATE ON dashboard_changes TO {}').format(sql.Identifier(group)))
                    with pytest.raises(ServiceSchemaError):validate_schema(conn)
                    conn.rollback()
                    # SET ROLE authority is also an unexpected owner path.
                    conn.execute(sql.SQL('ALTER TABLE dashboard_changes OWNER TO {}').format(sql.Identifier(owner)))
                    conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(owner),sql.Identifier(member)))
                    with pytest.raises(ServiceSchemaError):validate_schema(conn)
                    conn.rollback()
        finally:
            for role in reversed(roles):admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


@pytest.mark.parametrize('role',['reader','writer','admin'])
@pytest.mark.parametrize('table',['dashboard_changes','dashboard_setup','dashboard_presence','request_traces'])
def test_control_owner_cannot_be_restricted_database_role(role,table,tmp_path):
    from agentic_rag.service.api import create_app
    from starlette.testclient import TestClient
    from .test_api import app_fixture
    from .test_dashboard import login
    from .test_dashboard_policy import apply
    with isolated_database(Config(ollama_url='http://127.0.0.1:1')) as owned:
        app,path=app_fixture(tmp_path,owned)
        with TestClient(app,base_url='https://testserver') as client:
            result=apply(client,login(client),{'kind':'machine','id':'vm1','fields':{'label':'Real owner-drift audit'}})
            assert result.status_code==200,result.text
            operation=result.json()['operation_id']
        with db.connect(owned) as conn:
            conn.execute(sql.SQL('ALTER TABLE {} OWNER TO {}').format(sql.Identifier(table),sql.Identifier('rag_'+role)))
        with psycopg.connect(db.dsn(owned,role)) as attacker:
            assert attacker.execute("SELECT has_table_privilege(current_user,%s,'UPDATE')",(table,)).fetchone()[0]
            if table=='dashboard_changes':
                assert attacker.execute("UPDATE dashboard_changes SET state='not_applied' WHERE operation_id=%s RETURNING state",(operation,)).fetchone()[0]=='not_applied'
        with db.connect(owned) as conn:
            with pytest.raises(ServiceSchemaError):validate_schema(conn)
        with pytest.raises(ServiceSchemaError):create_app(owned,path,allowed_hosts=['testserver'])


@pytest.mark.parametrize('table,column',[
    ('dashboard_changes','state'),('dashboard_setup','checks'),('dashboard_presence','version'),('request_traces','outcome'),
])
def test_column_grant_cannot_expose_control_state(table,column):
    with isolated_database(Config(ollama_url='http://127.0.0.1:1')) as owned:
        with db.connect(owned) as conn:
            conn.execute(sql.SQL('GRANT UPDATE ({}) ON {} TO rag_reader').format(sql.Identifier(column),sql.Identifier(table)))
            assert conn.execute("SELECT has_column_privilege('rag_reader',%s,%s,'UPDATE') exposed",(table,column)).fetchone()['exposed']
            assert not conn.execute("SELECT has_table_privilege('rag_reader',%s,'UPDATE') exposed",(table,)).fetchone()['exposed']
            with pytest.raises(ServiceSchemaError):validate_schema(conn)
