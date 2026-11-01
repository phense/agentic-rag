"""RAG-067 T067-003: bindings follow session RLS; a foreign session stays invisible."""
import psycopg
import pytest

from agentic_rag import db, extraction_policy as ep, mining
from agentic_rag.service.context import request_scope
from .test_scope import principal, service_store  # noqa: F401


def test_binding_rls_limits_rows_to_the_principal_session(service_store):
    cfg, _ = service_store
    p = principal()
    own, foreign = p.session_id('own-session'), 'svc1:someone-else:x'
    b = ep.build_bundle(None, '/projects/a', ['alpha'])
    with db.connect(cfg) as owner:
        owner.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                      " VALUES (%s,'',%s,%s,'window')", (foreign, b.digest, ep.canonical(b.snapshot)))
        owner.commit()
    with request_scope(p, cfg), db.connect(cfg, role='writer') as conn:
        winner, created = mining.bind_policy(conn, session_id=own, input_cursor='', bundle=b, origin='window')
        assert created
        assert [r['session_id'] for r in conn.execute('SELECT session_id FROM extraction_policy_bindings')] == [own]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                         " VALUES (%s,'c',%s,%s,'window')", (foreign, b.digest, ep.canonical(b.snapshot)))
        conn.rollback()
