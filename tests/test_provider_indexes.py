"""Owned PostgreSQL lifecycle proofs; no real inference or production database."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import httpx
import psycopg
import pytest

from agentic_rag import db, providers

REAL_EMBED=providers.embed_profile
REAL_VERIFY=providers.verify_identity


@pytest.fixture
def managed(conn,cfg,monkeypatch):
    from agentic_rag import indexes
    conn.execute('TRUNCATE embedding_selection,embedding_generations CASCADE')
    conn.execute('INSERT INTO embedding_selection(singleton) VALUES(true)')
    conn.execute("INSERT INTO domains(name,description) VALUES ('general','Synthetic') ON CONFLICT DO NOTHING")
    profiles={name:providers.EmbeddingProfile(provider='ollama',model=name,revision=revision*64,
        url='http://localhost:11434',dimensions=dim) for name,revision,dim in [('two','a',2),('three','b',3),('other','c',2)]}
    cfg=replace(cfg,embedding_profiles=profiles)
    monkeypatch.setattr(providers,'verify_identity',lambda profile:profile.identity)
    monkeypatch.setattr(providers,'embed_profile',lambda texts,p:[[1.0]+[0.0]*(p.dimensions-1) for _ in texts])
    def save(title='Original',content='original fact',scope='global'):
        row=conn.execute("INSERT INTO documents(title,body,slug,domain,dtype,project_scope) VALUES(%s,%s,%s,'general','reference',%s) RETURNING id",(title,content,title.lower().replace(' ','-'),scope)).fetchone()
        chunk=conn.execute('INSERT INTO chunks(document_id,idx,content) VALUES(%s,0,%s) RETURNING id',(row['id'],content)).fetchone()
        return row['id'],chunk['id']
    return indexes,cfg,save


def test_generation_rebuild_is_opt_in_resumable_and_never_imports_legacy(conn,managed):
    ix,cfg,save=managed
    save();save('Second')
    gen=ix.create(conn,cfg,'blue','two')
    assert gen.dimensions==2 and ix.active(conn,cfg) is None
    with pytest.raises(ValueError,match='corpus'):ix.build(conn,cfg,'blue')
    progress=ix.build(conn,cfg,'blue',limit=1,allow_corpus=True)
    assert progress['written']==1 and progress['remaining']==1
    with pytest.raises(ValueError,match='coverage'):ix.activate(conn,cfg,'blue')
    assert ix.active(conn,cfg) is None
    assert ix.build(conn,cfg,'blue',limit=1,allow_corpus=True)['remaining']==0
    ix.activate(conn,cfg,'blue')
    bound=ix.query_vector(ix.active(conn,cfg),cfg,'unrelated query')
    hits=ix.candidates(conn,bound,'unrelated query',domain='general',scopes=['global'],at=None,history=False,k=8)
    assert len(hits)==2
    assert all(h['score']>0 for h in hits)
    assert conn.execute('SELECT count(*) n FROM chunks WHERE embedding IS NOT NULL').fetchone()['n']==0


def test_incompatible_dimensions_equal_dim_revision_and_catchup_rollback(conn,managed):
    # Mixing any earlier space, or trusting old coverage, loses current knowledge.
    ix,cfg,save=managed
    save();old=ix.create(conn,cfg,'old','two')
    ix.build(conn,cfg,'old',allow_corpus=True);ix.activate(conn,cfg,'old')
    other=ix.create(conn,cfg,'other','other')
    assert other.identity!=old.identity and other.dimensions==old.dimensions
    new=ix.create(conn,cfg,'new','three')
    ix.build(conn,cfg,'new',allow_corpus=True);ix.activate(conn,cfg,'new',expected_active=old)
    save('After cutover','new fact')
    with pytest.raises(ValueError,match='coverage'):ix.rollback(conn,cfg,'old')
    assert ix.active(conn,cfg).id==new.id
    assert ix.build(conn,cfg,'old',allow_corpus=True)['written']==1
    ix.rollback(conn,cfg,'old',expected_active=new)
    rows=ix.candidates(conn,ix.query_vector(ix.active(conn,cfg),cfg,'quasar'),'quasar',scopes=['global'])
    assert {r['title'] for r in rows}=={'Original','After cutover'}
    assert ix.query_vector(new,cfg,'quasar').selection.dimensions==3
    with pytest.raises(psycopg.errors.RaiseException,match='three retained'):ix.create(conn,cfg,'fourth','two')


def test_idempotent_create_secret_rotation_and_changed_descriptor(conn,managed,monkeypatch):
    ix,cfg,save=managed
    generation=ix.create(conn,cfg,'one','two')
    rotated=replace(cfg,embedding_profiles={**cfg.embedding_profiles,'two':replace(cfg.embedding_profiles['two'],credential_env='ROTATED')})
    assert ix.create(conn,rotated,'one','two').id==generation.id
    changed=replace(cfg,embedding_profiles={**cfg.embedding_profiles,'two':cfg.embedding_profiles['other']})
    with pytest.raises(providers.ProviderError,match='differs'):ix.query_vector(generation,changed,'query')
    with pytest.raises(psycopg.errors.RaiseException,match='identity mismatch'):ix.create(conn,changed,'one','two')
    assert ix.active(conn,cfg) is None


def test_status_is_offline_and_bound_query_pins_retained_generation(conn,managed,monkeypatch):
    ix,cfg,save=managed
    save();old=ix.create(conn,cfg,'old','two');new=ix.create(conn,cfg,'new','three')
    for name in ('old','new'):ix.build(conn,cfg,name,allow_corpus=True)
    ix.activate(conn,cfg,'old');bound=ix.query_vector(ix.active(conn,cfg),cfg,'quasar')
    ix.activate(conn,cfg,'new')
    def forbidden(*a,**kw):raise AssertionError('offline inspection called provider')
    monkeypatch.setattr(providers,'verify_identity',forbidden)
    monkeypatch.setattr(providers,'embed_profile',forbidden)
    assert ix.status(conn,cfg,'old')['remaining']==0
    assert not ix.status(conn,cfg,'old')['active']
    assert len(ix.candidates(conn,bound,'quasar'))==1
    missing=replace(cfg,embedding_profiles={})
    assert ix.active(conn,missing).id==new.id
    with pytest.raises(providers.ProviderError):ix.query_vector(ix.active(conn,missing),missing,'query')


@pytest.mark.parametrize('code',['transient','model_missing','identity_mismatch'])
def test_provider_failure_leaves_vectors_pointer_and_prior_work_intact(conn,managed,monkeypatch,code):
    ix,cfg,save=managed
    doc,_=save();generation=ix.create(conn,cfg,'one','two')
    def unavailable(*a,**kw):raise providers.ProviderError(code,code=='transient','safe failure')
    monkeypatch.setattr(providers,'embed_profile',unavailable)
    with pytest.raises(providers.ProviderError) as error:ix.build(conn,cfg,'one',allow_corpus=True)
    assert error.value.code==code
    assert ix.active(conn,cfg) is None
    assert ix.status(conn,cfg,'one')['remaining']==1
    assert conn.execute('SELECT title FROM documents WHERE id=%s',(doc,)).fetchone()['title']=='Original'


def test_concurrent_metadata_edit_during_inference_rejects_stale_batch(conn,managed,monkeypatch):
    ix,cfg,save=managed
    doc,_=save();ix.create(conn,cfg,'one','two');conn.commit()
    def concurrent(texts,profile):
        with db.connect(cfg) as writer:
            writer.execute("UPDATE documents SET project_scope='unknown' WHERE id=%s",(doc,))
        return [[1.0,0.0] for _ in texts]
    monkeypatch.setattr(providers,'embed_profile',concurrent)
    with pytest.raises(psycopg.errors.RaiseException,match='source or vector'):ix.build(conn,cfg,'one',allow_corpus=True)
    assert ix.status(conn,cfg,'one')['remaining']==1
    assert conn.execute('SELECT count(*) n FROM embedding_vectors').fetchone()['n']==0


def test_scope_repair_invalidates_reads_and_rebuild_restores_current_scope(conn,managed):
    ix,cfg,save=managed
    doc,_=save();ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True);ix.activate(conn,cfg,'one')
    bound=ix.query_vector(ix.active(conn,cfg),cfg,'quasar')
    conn.execute("UPDATE documents SET project_scope='unknown' WHERE id=%s",(doc,))
    assert ix.candidates(conn,bound,'quasar')==[]
    assert ix.status(conn,cfg,'one')['remaining']==1
    ix.build(conn,cfg,'one',allow_corpus=True)
    assert len(ix.candidates(conn,bound,'quasar',scopes=['unknown']))==1
    assert ix.candidates(conn,bound,'quasar',scopes=['global'])==[]


def test_activation_waits_for_old_client_writer_then_refuses_incomplete(conn,managed):
    ix,cfg,save=managed
    save();ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True);conn.commit()
    writer=db.connect(cfg)
    writer.execute("INSERT INTO documents(title,body,slug,domain,dtype) VALUES('Concurrent','new','concurrent','general','reference') RETURNING id")
    new_doc=writer.execute("SELECT id FROM documents WHERE slug='concurrent'").fetchone()['id']
    writer.execute("INSERT INTO chunks(document_id,idx,content) VALUES(%s,0,'new source')",(new_doc,))
    started=threading.Event()
    def switch():
        with db.connect(cfg) as other:
            started.set()
            return ix.activate(other,cfg,'one')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(switch);assert started.wait(1)
        time.sleep(.1)
        assert not future.done()
        writer.commit();writer.close()
        with pytest.raises(ValueError,match='coverage'):future.result(timeout=4)
    assert ix.active(conn,cfg) is None


def test_concurrent_builders_write_each_source_once(conn,managed,monkeypatch):
    ix,cfg,save=managed
    save();ix.create(conn,cfg,'one','two');conn.commit()
    barrier=threading.Barrier(2)
    def infer(texts,profile):
        barrier.wait(timeout=3)
        return [[1.0,0.0] for _ in texts]
    monkeypatch.setattr(providers,'embed_profile',infer)
    def build():
        with db.connect(cfg) as own:return ix.build(own,cfg,'one',allow_corpus=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:build(),range(2)))
    assert sorted(r['written'] for r in results)==[0,1]
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_build'").fetchone()['n']==1


def test_simultaneous_switches_compare_original_pointer_and_only_one_wins(conn,managed,monkeypatch):
    ix,cfg,save=managed
    save()
    first=ix.create(conn,cfg,'first','two')
    for name,profile in [('second','three'),('third','other')]:ix.create(conn,cfg,name,profile)
    for name in ('first','second','third'):ix.build(conn,cfg,name,allow_corpus=True)
    ix.activate(conn,cfg,'first');conn.commit()
    barrier=threading.Barrier(2)
    monkeypatch.setattr(providers,'verify_identity',lambda p:(barrier.wait(timeout=3),p.identity)[1])
    def switch(name):
        try:
            with db.connect(cfg) as own:return ix.activate(own,cfg,name,expected_active=first).name
        except ValueError:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(switch,['second','third']))
    assert results.count('conflict')==1
    assert ix.active(conn,cfg).name in ('second','third')
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_activate'").fetchone()['n']==2


def test_empty_corpus_selection_and_archived_chunk_coverage(conn,managed):
    ix,cfg,save=managed
    ix.create(conn,cfg,'one','two');ix.activate(conn,cfg,'one')
    assert ix.status(conn,cfg,'one')['remaining']==0
    doc,_=save()
    conn.execute("UPDATE documents SET status='archived' WHERE id=%s",(doc,))
    with pytest.raises(ValueError,match='coverage'):ix.activate(conn,cfg,'one')
    assert ix.status(conn,cfg,'one')['remaining']==1
    ix.build(conn,cfg,'one',allow_corpus=True)
    ix.activate(conn,cfg,'one')


@pytest.mark.parametrize('failure', ['wrong_dimension', 'unsupported'])
def test_empty_generation_cannot_activate_without_embedding_capability(conn,managed,monkeypatch,failure):
    ix,cfg,_=managed
    ix.create(conn,cfg,'empty','two')
    monkeypatch.setattr(providers,'verify_identity',REAL_VERIFY)
    monkeypatch.setattr(providers,'embed_profile',REAL_EMBED)
    def handle(request):
        if request.url.path=='/api/tags':
            return httpx.Response(200,json={'models':[{'name':'two:latest','digest':'a'*64}]})
        if failure=='unsupported':return httpx.Response(404)
        return httpx.Response(200,json={'embeddings':[[1.,0.,0.]]})
    client=httpx.Client
    monkeypatch.setattr(providers,'_http_client',lambda **kwargs:client(transport=httpx.MockTransport(handle),**kwargs))
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    with pytest.raises(providers.ProviderError):ix.activate(conn,cfg,'empty')
    assert ix.active(conn,cfg) is None
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before


def test_new_generation_ddl_honors_stricter_memory_and_restores_gucs(conn,managed):
    ix,cfg,_=managed
    conn.execute("SET LOCAL maintenance_work_mem='2MB'")
    before=conn.execute('SHOW max_parallel_maintenance_workers').fetchone()['max_parallel_maintenance_workers']
    ix.create(conn,cfg,'one','two')
    assert conn.execute('SHOW maintenance_work_mem').fetchone()['maintenance_work_mem']=='2MB'
    assert conn.execute('SHOW max_parallel_maintenance_workers').fetchone()['max_parallel_maintenance_workers']==before


@pytest.mark.parametrize('role',['reader','writer','admin'])
def test_sql_and_python_lifecycle_owner_only(conn,managed,role):
    ix,cfg,save=managed
    generation=ix.create(conn,cfg,'one','two');conn.commit()
    with db.connect(cfg,role=role) as scoped:
        with pytest.raises(PermissionError):ix.status(scoped,cfg)
        for operation,args in [('create_embedding_generation',('x','two','a'*64,json.dumps(cfg.embedding_profiles['two'].descriptor))),
                                ('select_embedding_generation',(generation.id,None,'activate'))]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege),scoped.transaction():
                placeholders=','.join(['%s']*len(args));scoped.execute(f'SELECT public.{operation}({placeholders})',args)


def test_service_rls_and_gateway_recheck_write_scope(conn,managed):
    ix,cfg,save=managed
    allowed,allowed_chunk=save();denied,denied_chunk=save('Denied','private fact','unknown')
    generation=ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True);ix.activate(conn,cfg,'one');conn.commit()
    with db.connect(cfg,role='writer') as scoped:
        scoped.execute("SELECT set_config('rag_service.active','1',true),set_config('rag_service.read_domains','[\"general\"]',true),set_config('rag_service.read_projects','[\"global\"]',true),set_config('rag_service.write_domains','[\"general\"]',true),set_config('rag_service.write_projects','[\"global\"]',true)")
        assert len(scoped.execute('SELECT * FROM embedding_vectors').fetchall())==1
        hits=ix.candidates(scoped,ix.query_vector(generation,cfg,'quasar'),'quasar')
        assert {r['document_id'] for r in hits}=={allowed}
        with pytest.raises(psycopg.errors.InsufficientPrivilege),scoped.transaction():
            scoped.execute("SELECT put_embedding_vectors(%s,%s::uuid[],%s,%s,'cli')",(generation.id,[denied_chunk],['a'*64],['[1,0]']))
        with pytest.raises(psycopg.errors.InsufficientPrivilege),scoped.transaction():
            scoped.execute("UPDATE embedding_vectors SET source_hash=%s",('a'*64,))


@pytest.mark.parametrize('vector',['[0,0]','[1,0,0]','[NaN,0]','[Infinity,1]'])
def test_gateway_rejects_invalid_vectors_with_current_hash(conn,managed,vector):
    ix,cfg,save=managed
    _,chunk=save();generation=ix.create(conn,cfg,'one','two')
    hash=conn.execute('SELECT embedding_source_hash(d.title,d.project_scope,c.content) hash FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=%s',(chunk,)).fetchone()['hash']
    with pytest.raises(psycopg.Error),conn.transaction():
        conn.execute("SELECT put_embedding_vectors(%s,%s::uuid[],%s,%s,'cli')",(generation.id,[chunk],[hash],[vector]))
    assert conn.execute('SELECT count(*) n FROM embedding_vectors').fetchone()['n']==0


def test_actual_provider_identity_drift_aborts_without_mixed_vectors(conn,managed,monkeypatch):
    ix,cfg,save=managed
    save();state={'digest':'a'*64};calls=[]
    def handler(request):
        calls.append(request.method)
        if request.url.path=='/api/tags':return httpx.Response(200,json={'models':[{'name':'two:latest','digest':state['digest']}]})
        state['digest']='b'*64
        return httpx.Response(200,json={'embeddings':[[1,0]]})
    monkeypatch.setattr(providers,'verify_identity',REAL_VERIFY);monkeypatch.setattr(providers,'embed_profile',REAL_EMBED)
    client=httpx.Client
    monkeypatch.setattr(providers,'_http_client',lambda **kwargs:client(transport=httpx.MockTransport(handler),**kwargs))
    ix.create(conn,cfg,'one','two')
    with pytest.raises(providers.ProviderError) as error:ix.build(conn,cfg,'one',allow_corpus=True)
    assert error.value.code=='identity_mismatch' and calls==['GET','GET','POST','GET']
    assert ix.status(conn,cfg,'one')['indexed']==0


def test_large_generation_ann_and_filters_preserve_second_document(conn,managed,monkeypatch):
    ix,cfg,save=managed
    doc,chunk=save('Crowded','crowded fact');second,_=save('Second','nearest fact')
    conn.execute("INSERT INTO chunks(document_id,idx,content) SELECT %s,n,'crowded fact' FROM generate_series(1,4100) n",(doc,))
    generation=ix.create(conn,cfg,'one','two')
    monkeypatch.setattr(providers,'embed_profile',lambda texts,p:[[1,.2] if 'crowded' in t else [1,0] for t in texts])
    # All vectors pass the real audited gateway in finite pages.
    while ix.build(conn,cfg,'one',limit=32,allow_corpus=True)['remaining']:pass
    ix.activate(conn,cfg,'one')
    rows=ix.candidates(conn,ix.query_vector(generation,cfg,'quasar'),'quasar',scopes=['global'])
    assert {r['document_id'] for r in rows}=={doc,second}
    assert len(rows)<=3


def test_caller_rollback_preserves_original_rows_and_removes_derived_work(conn,managed):
    ix,cfg,save=managed
    save();conn.commit()
    original=conn.execute('SELECT row_to_json(c) data FROM chunks c ORDER BY id').fetchall()
    ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True);ix.activate(conn,cfg,'one')
    conn.rollback()
    assert conn.execute('SELECT row_to_json(c) data FROM chunks c ORDER BY id').fetchall()==original
    assert ix.active(conn,cfg) is None
    assert ix.status(conn,cfg)==[]


def test_final_projection_rechecks_source_and_explicit_scope_after_semantic_stage(conn,managed,monkeypatch):
    ix,cfg,save=managed
    doc,_=save();generation=ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True);conn.commit()
    original=ix._neighbors
    def race(*args,**kwargs):
        rows=original(*args,**kwargs)
        with db.connect(cfg) as writer:writer.execute("UPDATE documents SET project_scope='unknown' WHERE id=%s",(doc,))
        return rows
    monkeypatch.setattr(ix,'_neighbors',race)
    assert ix.candidates(conn,ix.query_vector(generation,cfg,'quasar'),'quasar',scopes=['global'])==[]


def test_sql_budget_failure_warns_and_restores_settings_without_losing_prior_work(conn,managed,monkeypatch):
    ix,cfg,save=managed
    doc,_=save();generation=ix.create(conn,cfg,'one','two');ix.build(conn,cfg,'one',allow_corpus=True)
    conn.execute("SET LOCAL statement_timeout='100ms'")
    def slow(conn,*args,**kwargs):return conn.execute('SELECT pg_sleep(.3)').fetchall()
    monkeypatch.setattr(ix,'_neighbors',slow)
    warnings=[]
    hits=ix.candidates(conn,ix.query_vector(generation,cfg,'original'),'original',warnings=warnings)
    assert hits and warnings==['managed vector search exceeded its SQL budget; full-text search only']
    assert conn.execute('SHOW statement_timeout').fetchone()['statement_timeout']=='100ms'
    assert conn.execute('SELECT title FROM documents WHERE id=%s',(doc,)).fetchone()['title']=='Original'


def test_schema026_legacy_detection_and_no_implicit_selection(conn,managed):
    ix,cfg,_=managed
    with conn.transaction():
        conn.execute('ALTER TABLE embedding_selection RENAME TO unselected_generation_fixture')
        assert not ix.available(conn) and ix.active(conn,cfg) is None
        conn.execute('ALTER TABLE unselected_generation_fixture RENAME TO embedding_selection')


def test_service_context_and_client_mode_cannot_run_global_lifecycle(conn,managed):
    ix,cfg,_=managed
    with pytest.raises(PermissionError):ix.create(conn,replace(cfg,service_mode='client'),'one','two')
    from agentic_rag.service.context import CURRENT
    token=CURRENT.set(object())
    try:
        with pytest.raises(PermissionError):ix.create(conn,cfg,'one','two')
    finally:CURRENT.reset(token)


def test_custom_default_acl_cannot_bypass_derived_gateway(conn,managed):
    ix,cfg,_=managed
    # Simulate a DBA's inherited group grants; only new objects are hardened.
    with conn.transaction():
        conn.execute('CREATE ROLE managed_index_acl_fixture')
        conn.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO managed_index_acl_fixture')
        conn.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO managed_index_acl_fixture')
        conn.execute('DROP TABLE embedding_vectors,embedding_selection,embedding_generations CASCADE')
        conn.execute('DROP FUNCTION embedding_source_hash(text,text,text),embedding_lifecycle_owner(),create_embedding_generation(text,text,text,jsonb),put_embedding_vectors(uuid,uuid[],text[],text[],text),select_embedding_generation(uuid,uuid,text) CASCADE')
        conn.execute((db.SQL_DIR/'027_provider_indexes.sql').read_text())
        for table in ('embedding_generations','embedding_selection','embedding_vectors'):
            assert not conn.execute('SELECT has_table_privilege(%s,%s,%s) ok',('managed_index_acl_fixture',table,'INSERT,UPDATE,DELETE')).fetchone()['ok']
        for function in ('create_embedding_generation(text,text,text,jsonb)','select_embedding_generation(uuid,uuid,text)','put_embedding_vectors(uuid,uuid[],text[],text[],text)'):
            assert not conn.execute('SELECT has_function_privilege(%s,%s,%s) ok',('managed_index_acl_fixture',function,'EXECUTE')).fetchone()['ok']
        # Roll back role/default privilege changes, as well as the test DDL.
        raise psycopg.Rollback


def test_server_background_build_yields_to_foreground_work(conn,managed):
    ix,cfg,save=managed
    save();ix.create(conn,cfg,'one','two')
    from agentic_rag.service.priority import foreground
    from agentic_rag.service.engine import ResourcePressure
    cfg=replace(cfg,service_mode='server')
    with foreground(cfg):
        with pytest.raises(ResourcePressure):ix.build(conn,cfg,'one',allow_corpus=True)
    assert ix.status(conn,cfg,'one')['indexed']==0


def test_server_embedding_uses_shared_model_admission_and_background_deadline(conn,managed,monkeypatch):
    ix,cfg,save=managed
    save();generation=ix.create(conn,cfg,'one','two');cfg=replace(cfg,service_mode='server')
    from agentic_rag.service.priority import MODEL_LOCK
    observed=[]
    def infer(texts,profile):
        with db.connect(cfg) as competing:
            assert not competing.execute('SELECT pg_try_advisory_xact_lock(%s) ok',(MODEL_LOCK,)).fetchone()['ok']
        observed.append(profile.timeout)
        return [[1,0] for _ in texts]
    monkeypatch.setattr(providers,'embed_profile',infer)
    ix.build(conn,cfg,'one',allow_corpus=True)
    assert observed==[10.0]
    ix.query_vector(generation,cfg,'quasar')
    assert observed==[10.0,30.0]


def test_additive_generation_schema_exists_without_relabeling_legacy(conn):
    # Missing sidecars or importing historical untagged vectors breaks opt-in safety.
    assert conn.execute("SELECT to_regclass('public.embedding_generations') AS t").fetchone()['t'] is not None
    assert conn.execute('SELECT count(*) n FROM embedding_generations').fetchone()['n'] == 0
    assert conn.execute('SELECT generation_id FROM embedding_selection').fetchone() is None
