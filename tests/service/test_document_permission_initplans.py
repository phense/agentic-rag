"""Original 021 policy versus statement-local inputs, through actual RLS roles."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from agentic_rag import db, domains, embedding_reuse, query_cache, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config

FIXTURE=Path(__file__).parents[1]/'fixtures/document-permission-initplans'
BEFORE=(FIXTURE/'before.sql').read_text()
assert hashlib.sha256(BEFORE.encode()).hexdigest()==json.loads((FIXTURE/'FROZEN.json').read_text())['sha256']
MIGRATION='035_document_permission_initplans.sql'
HELPER='public.rag_service_permission(text,jsonb)'
ROLES=('rag_reader','rag_writer','rag_admin')
TABLES=('documents','chunks','chunk_contexts','edges','claim_records','claim_evidence')


@pytest.fixture(scope='module')
def permission_db():
    with pytest.MonkeyPatch.context() as patch,isolated_database(Config()) as cfg:
        patch.setattr(store,'try_embed_texts',lambda *a,**k:None)
        patch.setattr(embedding_reuse,'model_digest',lambda cfg:None)
        patch.setattr(query_cache,'model_digest',lambda cfg:None)
        docs=[]
        with db.connect(cfg) as owner:
            for domain in ('alpha','beta'):domains.add_domain(owner,domain)
            for i,(domain,project) in enumerate([('alpha','/projects/a'),('alpha','/projects/b'),('beta','/projects/a'),('beta','/projects/b')]):
                result=store.save_claim(owner,cfg,title=f'Permission original {i}',body=f'Original blue maintenance {i}',domain=domain,dtype='memory',project=project,claim_kind='stated',evidence=[{'namespace':f'session:permission-{i}','source_id':'original','quote':f'Original blue maintenance {i}','role':'user','complete':True}],edges=[store.EdgeSpec('references',docs[-1]['slug'])] if docs else [])
                docs.append(dict(id=result.doc_id,slug=result.slug,domain=domain,project=project))
            for table in TABLES:owner.execute(sql.SQL('ANALYZE {}').format(sql.Identifier(table)))
            owner.commit()
        yield cfg,docs


@contextmanager
def policy_conn(cfg,role,variant):
    # One owner transaction holds rollback-only DDL, then switches to a real
    # RLS role. Never run arms concurrently on the same policy.
    with db.connect(cfg) as conn:
        if variant=='before':conn.execute(BEFORE)
        conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
        try:yield conn
        finally:conn.rollback()


def bind(conn,*,active='1',rd='["alpha"]',rp='["/projects/a"]',wd='["alpha"]',wp='["/projects/a"]'):
    # Each invocation specifies the complete state; None means truly unset on
    # a fresh backend, not RESET of an already-created placeholder.
    for key,value in dict(active=active,read_domains=rd,read_projects=rp,write_domains=wd,write_projects=wp).items():
        if value is not None:conn.execute('SELECT set_config(%s,%s,true)',('rag_service.'+key,value))


def rows(conn,table):
    return conn.execute(sql.SQL('SELECT to_jsonb(t) row FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))).fetchall()


def outcome(cfg,role,variant,settings,table):
    try:
        with policy_conn(cfg,role,variant) as conn:
            bind(conn,**settings)
            return rows(conn,table)
    except psycopg.Error as exc:return exc.sqlstate


@pytest.mark.parametrize('role',ROLES)
@pytest.mark.parametrize('settings',[
    {},dict(rd='["*"]',rp='["*"]'),dict(rd='[]'),dict(rp='[]'),dict(rd='null'),dict(rd=None,rp=None),
    dict(rd=''),dict(rd='{'),dict(rp='{'),dict(rd='[]',rp='{'),dict(rd='"alpha"'),
    dict(rd='{"alpha":false}'),dict(rd='[["alpha"]]'),dict(rd='["Alpha"]'),
    dict(active='0',rd='{',rp='{'),dict(active=None,rd='{',rp='{'),dict(active='',rd='{',rp='{'),
])
def test_original_and_current_nested_visibility_and_errors(permission_db,role,settings):
    cfg,_=permission_db
    for table in TABLES:
        expected=outcome(cfg,role,'before',settings,table)
        assert outcome(cfg,role,'current',settings,table)==expected,(role,settings,table)
    if settings=={}:
        assert len(outcome(cfg,role,'current',settings,'documents'))==1
    if settings.get('rd')=='[]':assert outcome(cfg,role,'current',settings,'documents')==[]


@pytest.mark.parametrize('role',ROLES)
@pytest.mark.parametrize('variant',['before','current'])
def test_generic_plan_live_domain_and_project_revocation(permission_db,role,variant):
    cfg,_=permission_db
    with policy_conn(cfg,role,variant) as conn:
        bind(conn);conn.execute('SET LOCAL plan_cache_mode=force_generic_plan')
        conn.execute('PREPARE permission_read AS SELECT id,title FROM documents ORDER BY id')
        initial=conn.execute('EXECUTE permission_read').fetchall();assert len(initial)==1
        for _ in range(8):
            bind(conn,rd='[]');assert conn.execute('EXECUTE permission_read').fetchall()==[]
            bind(conn,rp='[]');assert conn.execute('EXECUTE permission_read').fetchall()==[]
            bind(conn);assert conn.execute('EXECUTE permission_read').fetchall()==initial
        # The nested SQL function also gets a new executor on every call.
        first=conn.execute("SELECT * FROM hybrid_search_candidates('blue')").fetchall();assert first
        bind(conn,rd='[]');assert conn.execute("SELECT * FROM hybrid_search_candidates('blue')").fetchall()==[]
        bind(conn);assert conn.execute("SELECT * FROM hybrid_search_candidates('blue')").fetchall()==first


@pytest.mark.parametrize('role',['rag_writer','rag_admin'])
@pytest.mark.parametrize('wd,wp,domain,project,expected',[
    ('["alpha"]','["/projects/a"]','alpha','/projects/a','ok'),
    ('[]','["*"]','alpha','/projects/a','42501'),
    ('["*"]','[]','alpha','/projects/a','42501'),
    ('["alpha"]','["/projects/a"]','beta','/projects/a','42501'),
    ('["*"]','["*"]','beta','/projects/b','ok'),
    ('null','["*"]','alpha','/projects/a','42501'),
    ('{','["*"]','alpha','/projects/a','22P02'),
    ('["*"]','["*"]',None,'/projects/a','23502'),
    ('[]','["*"]',None,'/projects/a','42501'),
])
def test_scoped_insert_and_update_keep_error_contract(permission_db,role,wd,wp,domain,project,expected):
    cfg,docs=permission_db
    for operation in ('insert','update'):
        outcomes=[]
        for variant in ('before','current'):
            try:
                with policy_conn(cfg,role,variant) as conn:
                    bind(conn,rd='["*"]',rp='["*"]',wd=wd,wp=wp)
                    # Policy-only writes are deliberately rolled back. Persistent
                    # fixtures above use the real audited gateway.
                    if operation=='insert':conn.execute("INSERT INTO documents(title,slug,body,domain,dtype,project_scope) VALUES ('Permission transient','permission-transient','synthetic',%s,'memory',%s)",(domain,project))
                    else:conn.execute('UPDATE documents SET domain=%s,project_scope=%s WHERE id=%s',(domain,project,docs[0]['id']))
                    outcomes.append('ok')
            except psycopg.Error as exc:outcomes.append(exc.sqlstate)
        assert outcomes==[expected,expected],(operation,role,outcomes)


def test_policy_inputs_are_lazy_inlined_and_keep_point_access(permission_db):
    cfg,docs=permission_db
    with policy_conn(cfg,'rag_reader','current') as conn:
        bind(conn)
        plan=conn.execute('EXPLAIN (VERBOSE,FORMAT JSON) SELECT id FROM documents').fetchone()['QUERY PLAN'][0]['Plan']
        text=json.dumps(plan)
        assert 'InitPlan' in text, 'permission settings are still evaluated inside the row filter'
        assert 'rag_service_permission' not in text, 'helper call must be inlined'
        assert text.count('current_setting')>=2
        assert 'Gather' not in text
        # Tiny fixture: force the available point-index path so a four-row
        # cost estimate cannot hide an index-access regression.
        conn.execute('SET LOCAL enable_seqscan=off')
        point=conn.execute('EXPLAIN (VERBOSE,FORMAT JSON) SELECT id FROM documents WHERE id=%s',(docs[0]['id'],)).fetchone()['QUERY PLAN'][0]['Plan']
        assert 'Index' in json.dumps(point), 'do not replace point reads with corpus scans'
    with policy_conn(cfg,'rag_reader','current') as conn:
        bind(conn,rd='{',rp='{')
        assert conn.execute('SELECT id FROM documents WHERE false').fetchall()==[]


def test_helper_is_pure_hardened_and_executable_for_existing_roles(permission_db):
    cfg,_=permission_db
    with db.connect(cfg) as conn:
        row=conn.execute("SELECT prosecdef,proleakproof,proisstrict,proparallel,provolatile,proconfig,prosrc FROM pg_proc WHERE oid=to_regprocedure(%s)",(HELPER,)).fetchone()
        assert row is not None
        assert {k:row[k] for k in row if k!='prosrc'}==dict(prosecdef=False,proleakproof=False,proisstrict=False,proparallel='u',provolatile='s',proconfig=None)
        assert 'OPERATOR(pg_catalog.?|)' in row['prosrc']
        for role in ROLES:assert conn.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\') ok',(role,HELPER)).fetchone()['ok']
        # Input-only helper keeps PUBLIC execution like the original helper,
        # preserving extra deployment roles without adding table authority.
        assert conn.execute("SELECT EXISTS(SELECT FROM aclexplode(proacl) WHERE grantee=0 AND privilege_type='EXECUTE') ok FROM pg_proc WHERE oid=to_regprocedure(%s)",(HELPER,)).fetchone()['ok']
