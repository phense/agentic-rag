"""Real engine/SQL authorization, including counts, graph and definer writers."""
from dataclasses import replace

import psycopg
import pytest

from agentic_rag import db, store, mcp_server
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database


@pytest.fixture(scope='module')
def service_store():
    cfg=Config(ollama_url='http://127.0.0.1:1',rerank_url='http://127.0.0.1:1')
    with isolated_database(cfg) as owned:
        with db.connect(owned) as conn:
            for domain in ('alpha','beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)',(domain,))
            conn.commit()
            docs={}
            for slug,domain,project in [('allowed','alpha','/projects/a'),('foreign','beta','/projects/b'),('same-topic-foreign','alpha','/projects/b')]:
                docs[slug]=store.save_document(conn,owned,title=slug,body='Synthetic protected evidence '+slug,domain=domain,dtype='memory',slug=slug,project=project).doc_id
            store.save_document(conn,owned,title='allowed',body='Synthetic protected evidence allowed',domain='alpha',dtype='memory',doc_id=docs['allowed'],project='/projects/a',edges=[store.EdgeSpec('references','foreign')])
        yield owned,docs


def principal(*,readonly=False):
    from agentic_rag.service.auth import Principal
    return Principal('alice','vm1','one',frozenset({'alpha'}),frozenset() if readonly else frozenset({'alpha'}),frozenset({'/projects/a'}),frozenset() if readonly else frozenset({'/projects/a'}))


def test_role_scoped_connection_filters_rows_counts_graph_and_survives_commit(service_store):
    from agentic_rag.service.context import request_scope
    cfg,docs=service_store
    with request_scope(principal(),cfg):
        with db.connect(cfg,role='writer') as conn:
            assert [r['slug'] for r in conn.execute('SELECT slug FROM documents')] == ['allowed']
            conn.commit()  # existing gateway commits must not clear authorization
            assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n'] == 1
            assert conn.execute('SELECT * FROM edges').fetchall() == []
            assert conn.execute('SELECT * FROM chunks WHERE document_id=%s',(docs['foreign'],)).fetchall()==[]
        assert mcp_server.memory_get('foreign').get('document') is None
        assert mcp_server.memory_domains()['domains'] == [{'name':'alpha','description':'','docs':1}]
        assert mcp_server.memory_neighbors('allowed')['edges'] == []
    # Local legacy scope remains unchanged on the same canonical database.
    with db.connect(cfg,role='reader') as conn:
        assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==3


def test_security_definer_write_cannot_mutate_guessed_foreign_document(service_store):
    from agentic_rag.service.context import request_scope
    cfg,docs=service_store
    with request_scope(principal(),cfg):
        for statement,args in [('SELECT replace_chunks(%s,%s,%s)',(docs['foreign'],['overwrite'],[None])),('SELECT put_chunk_contexts(%s,%s,%s,%s,%s,%s)',(docs['foreign'],[],[],[],[],None))]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.connect(cfg,role='writer') as conn:conn.execute(statement,args)
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT body FROM documents WHERE id=%s',(docs['foreign'],)).fetchone()['body']=='Synthetic protected evidence foreign'


def test_ro_cannot_write_and_rw_cannot_change_foreign_scope(service_store):
    from agentic_rag.service.context import request_scope
    cfg,docs=service_store
    with request_scope(principal(readonly=True),cfg):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg,role='writer') as conn:conn.execute("UPDATE documents SET title='bad' WHERE id=%s",(docs['allowed'],))
    with request_scope(principal(),cfg):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg,role='writer') as conn:conn.execute("UPDATE documents SET project_scope='/projects/b' WHERE id=%s",(docs['allowed'],))


def test_revoked_project_cannot_refute_its_earlier_owned_evidence(service_store):
    from agentic_rag.service.context import request_scope
    cfg,_=service_store
    p=principal()
    with db.connect(cfg) as conn:
        result=store.save_claim(conn,cfg,title='Scoped evidence',body='Synthetic source stays active',domain='alpha',dtype='memory',project='/projects/a',claim_kind='stated',evidence=[{'namespace':p.session_id('earlier'),'source_id':'one','role':'user','quote':'Synthetic source stays active','complete':True}])
        key=conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',(result.doc_id,)).fetchone()['source_key']
    revoked=replace(p,read_domains=frozenset({'beta'}),write_domains=frozenset({'beta'}),read_projects=frozenset({'/projects/b'}),write_projects=frozenset({'/projects/b'}))
    with request_scope(revoked,cfg):
        with pytest.raises(ValueError,match='source not found'):
            with db.connect(cfg,role='writer') as conn:store.set_source_state(conn,key,state='removed',reason='No current authority')
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s',(key,)).fetchone()['state']=='active'
