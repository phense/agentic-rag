"""Catch premature ANN limits that hide a second eligible source."""
import pytest
from agentic_rag import db, domains, search, store, vector_plan
from agentic_rag.embed import vec_literal


def test_small_eligible_vector_set_retains_second_document_after_crowded_chunks(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general')
    def vectors(texts,cfg):
        return [[.99,.1]+[0.0]*1022 if 'secondary-marker' in text
                else [1.0]+[0.0]*1023 for text in texts]
    monkeypatch.setattr(store,'try_embed_texts',vectors)
    monkeypatch.setattr(search,'try_embed_texts',vectors)
    crowded=store.save_document(conn,cfg,title='Crowded vector source',
        body=('crowded-marker neutral background. '*50000),domain='general',dtype='reference',project='/synthetic/filter-a')
    second=store.save_document(conn,cfg,title='Second vector source',body='secondary-marker independent fact.',
        domain='general',dtype='reference',project='/synthetic/filter-a')
    assert conn.execute('SELECT count(*) n FROM chunks WHERE document_id=%s',(crowded.doc_id,)).fetchone()['n']>256
    hits,warnings=search.search(conn,cfg,'quasar',project='/synthetic/filter-a',k=2,rerank_mode='off')
    assert not warnings
    assert {h.document_id for h in hits}=={crowded.doc_id,second.doc_id}


def test_zero_vectors_do_not_become_cosine_neighbors(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:[[0.0]*1024 for _ in texts])
    store.save_document(conn,cfg,title='Zero vector',body='No directional representation.',domain='general',dtype='reference',scope='global')
    vector=vec_literal([1.0]+[0.0]*1023)
    assert conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec)',(vector,)).fetchall()==[]


def test_zero_query_has_no_cosine_neighbors(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    store.save_document(conn,cfg,title='Nonzero vector',body='Directional representation.',domain='general',dtype='reference',scope='global')
    assert conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec)',(vec_literal([0.0]*1024),)).fetchall()==[]


@pytest.fixture
def vectors(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general');domains.add_domain(conn,'rare')
    def embed(texts,cfg):return [[1.0,.2]+[0.0]*1022 for _ in texts]
    monkeypatch.setattr(store,'try_embed_texts',embed)
    monkeypatch.setattr(search,'try_embed_texts',embed)
    def save(title='Eligible',**kw):
        fields=dict(title=title,body='Independent original directional fact.',domain='general',dtype='reference',project='/synthetic/filter-a')
        fields.update(kw)
        return store.save_document(conn,cfg,**fields)
    return save


def params():
    return ('quasar',vec_literal([1.0]+[0.0]*1023),'general',150,
            ['/synthetic/filter-a','global'],'2026-01-01T00:00:00Z',False,None)


def settings(c):
    c.execute("SELECT '[1]'::halfvec")
    return {r['name']:r['setting'] for r in c.execute("SELECT name,setting FROM pg_settings WHERE name IN ('statement_timeout','hnsw.ef_search','hnsw.iterative_scan','hnsw.max_scan_tuples','hnsw.scan_mem_multiplier')")}


def test_eligible_raw_candidates_reject_foreign_domain_scope_archived_and_unknown(vectors,conn,cfg):
    good=vectors('Good')
    vectors('Wrong project',project='/synthetic/filter-b')
    vectors('Wrong domain',domain='rare')
    vectors('Archived',status='archived')
    vectors('Unknown',project=None,scope='unknown')
    with db.connect(cfg,role='reader') as reader:
        rows=vector_plan.candidates(reader,params())
        assert {str(r['document_id']) for r in rows}=={good.doc_id}
        from scripts.verify_contextual_indexing import citation_check
        hits,_=search.search(reader,cfg,'quasar',project='/synthetic/filter-a',domain='general',rerank_mode='off')
        assert {h.document_id for h in hits}=={good.doc_id}
        citation_check(reader,hits)


def test_expired_assertion_is_filtered_current_and_available_as_of(vectors,conn,cfg):
    saved=store.save_assertion(conn,cfg,entity='service',attribute='port',value='8172',domain='general',project='/synthetic/filter-a',
        event_at='2025-01-01T00:00:00Z',expires_at='2025-02-01T00:00:00Z',
        evidence={'source_id':'expiry','role':'user','quote':'port8172','event_at':'2025-01-01T00:00:00Z'})
    current=list(params())
    assert vector_plan.candidates(conn,tuple(current))==[]
    current[5]='2025-01-15T00:00:00Z'
    assert {str(r['document_id']) for r in vector_plan.candidates(conn,tuple(current))}=={saved.doc_id}


def test_withdrawn_claim_source_does_not_enter_planned_pool(vectors,conn,cfg):
    from agentic_rag import evidence
    body='An explicit service fact.'
    saved=store.save_claim(conn,cfg,title='Claim',body=body,domain='general',dtype='memory',claim_kind='stated',project='/synthetic/filter-a',
        evidence=[{'namespace':'synthetic','source_id':'claim','role':'user','quote':body,'complete':True}])
    assert {str(r['document_id']) for r in vector_plan.candidates(conn,params())}=={saved.doc_id}
    store.set_source_state(conn,evidence.sources(conn,saved.doc_id)[0]['source_key'],state='refuted',reason='Synthetic withdrawal')
    assert vector_plan.candidates(conn,params())==[]


def test_context_pool_rejects_stale_source_and_wrong_model(vectors,conn,cfg,monkeypatch):
    from agentic_rag import embed,query_cache
    saved=vectors()
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    doc=conn.execute('SELECT title,body,domain,dtype FROM documents WHERE id=%s',(saved.doc_id,)).fetchone()
    store.save_document(conn,cfg,**doc,doc_id=saved.doc_id,index_context=True)
    args=(vec_literal([1.0]+[0.0]*1023),'general',['/synthetic/filter-a'],'2026-01-01',False,'a'*64,True)
    assert conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s)',args).fetchall()
    bad=list(args);bad[5]='b'*64
    assert conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s)',tuple(bad)).fetchall()==[]
    store.set_project_scope(conn,saved.doc_id,project='/synthetic/filter-b')
    moved=list(args);moved[2]=['/synthetic/filter-b']
    assert conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s)',tuple(moved)).fetchall()==[]


@pytest.mark.parametrize('timeout',['40ms','1s','1min','0'])
def test_success_restores_real_caller_budgets_and_neighbor_connection(vectors,conn,cfg,timeout):
    vectors()
    with db.connect(cfg,role='reader') as reader,db.connect(cfg,role='reader') as neighbor:
        reader.execute('SELECT set_config(%s,%s,true)',('statement_timeout',timeout))
        reader.execute("SET LOCAL hnsw.max_scan_tuples=1000")
        original=settings(reader);other=settings(neighbor)
        assert vector_plan.candidates(reader,params())
        assert settings(reader)==original and settings(neighbor)==other


@pytest.mark.parametrize('autocommit',[False,True])
def test_idle_connection_keeps_setting_contract(vectors,cfg,autocommit):
    vectors()
    with db.connect(cfg,role='reader') as reader:
        reader.autocommit=autocommit
        original=settings(reader)
        if not autocommit:reader.commit()
        assert vector_plan.candidates(reader,params())
        assert settings(reader)==original


def test_real_timeout_rolls_back_only_planner_savepoint(vectors,conn,cfg):
    import psycopg
    vectors()
    with db.connect(cfg,role='writer') as writer,db.connect(cfg) as blocker:
        pending=store.save_document(writer,cfg,title='Pending caller write',body='Private synthetic pending fact.',domain='general',dtype='reference',project='/synthetic/filter-a',commit=False)
        writer.execute("SET LOCAL statement_timeout='40ms'")
        original=settings(writer)
        # Block the planned SQL function itself, not tables already locked by the caller.
        blocker.execute('LOCK TABLE claim_evidence IN ACCESS EXCLUSIVE MODE NOWAIT')
        with pytest.raises(psycopg.errors.QueryCanceled):vector_plan.candidates(writer,params())
        assert settings(writer)==original
        assert writer.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone()
        blocker.rollback()
        assert vector_plan.candidates(writer,params())
        writer.rollback()
    assert conn.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone() is None


def test_external_cancellation_preserves_caller_write_and_settings(vectors,conn,cfg):
    import psycopg,time
    from concurrent.futures import ThreadPoolExecutor
    vectors()
    with db.connect(cfg,role='writer') as writer,db.connect(cfg) as blocker:
        pending=store.save_document(writer,cfg,title='Cancelable caller write',body='Original pending source.',domain='general',dtype='reference',project='/synthetic/filter-a',commit=False)
        original=settings(writer)
        blocker.execute('LOCK TABLE claim_evidence IN ACCESS EXCLUSIVE MODE NOWAIT')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(vector_plan.candidates,writer,params())
            deadline=time.monotonic()+1.5
            while time.monotonic()<deadline:
                row=blocker.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',(writer.info.backend_pid,)).fetchone()
                if row and row['wait_event_type']=='Lock':break
                time.sleep(.01)
            else:pytest.fail('candidate statement did not reach the controlled lock')
            writer.cancel()
            with pytest.raises(psycopg.errors.QueryCanceled):future.result(timeout=3)
        assert settings(writer)==original
        assert writer.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone()
        blocker.rollback()
        assert vector_plan.candidates(writer,params())
        writer.rollback()
    assert conn.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone() is None


def test_autocommit_timeout_leaves_connection_usable(vectors,cfg):
    import psycopg
    vectors()
    with db.connect(cfg,role='reader') as reader,db.connect(cfg) as blocker:
        reader.autocommit=True
        reader.execute("SET statement_timeout='40ms'")
        original=settings(reader)
        blocker.execute('LOCK TABLE claim_evidence IN ACCESS EXCLUSIVE MODE NOWAIT')
        with pytest.raises(psycopg.errors.QueryCanceled):vector_plan.candidates(reader,params())
        assert settings(reader)==original
        blocker.rollback()
        assert vector_plan.candidates(reader,params())


def test_ann_route_remains_bounded_when_exact_threshold_is_exceeded(vectors,conn):
    one=vectors('One');two=vectors('Two')
    vector=vec_literal([1.0]+[0.0]*1023)
    rows=conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s,%s,%s)',
        (vector,'general',['/synthetic/filter-a'],'2026-01-01',False,None,False,1,256)).fetchall()
    ids={str(r['chunk_id']) for r in rows}
    expected={str(r['id']) for r in conn.execute('SELECT id FROM chunks WHERE document_id=ANY(%s::uuid[])',([one.doc_id,two.doc_id],))}
    assert ids==expected


@pytest.mark.parametrize('limit,pool',[(0,256),(4097,256),(1,255),(1,4097),(None,256)])
def test_bad_bounds_are_rejected(vectors,conn,limit,pool):
    import psycopg
    with pytest.raises(psycopg.errors.RaiseException,match='planning bounds'):
        conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,NULL,NULL,now(),false,NULL,false,%s,%s)',
            (vec_literal([1.0]+[0.0]*1023),limit,pool))


@pytest.mark.parametrize('version', ['0.7.4', 'unknown', '0.8.4'])
def test_unsupported_optional_capabilities_keep_working_search(vectors,conn,monkeypatch,version):
    vectors()
    real=vector_plan._planned_settings
    def installed(actual,original):
        if version=='0.8.4':
            original={k:v for k,v in original.items() if k!='hnsw.iterative_scan'}
        planned=real(version,original)
        assert 'hnsw.iterative_scan' not in planned
        return planned
    monkeypatch.setattr(vector_plan,'_planned_settings',installed)
    original=settings(conn)
    assert vector_plan.candidates(conn,params())
    assert settings(conn)==original


def test_real_4096_chunk_boundary_and_exact_tie_order(vectors,conn,cfg):
    # Audited saves, actual chunks and HNSW index; no hand-written vectors or rows.
    from agentic_rag.chunker import chunk_markdown
    paragraph='Directional background. '+('x'*990)+'\n\n'
    body=paragraph*4095
    assert len(chunk_markdown(body))==4095
    crowd=vectors('Boundary crowd',body=body)
    second=vectors('Boundary second')
    vector=vec_literal([1.0]+[0.0]*1023)
    # Reuse the large gateway-created fixture; add one audited chunk at the boundary.
    for total in (4096,4097):
        if total==4097:vectors('Boundary third')
        args=(vector,'general',['/synthetic/filter-a'],'2026-01-01',False,None,False,4096,4096)
        result=conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s,%s,%s)',args).fetchall()
        assert len(result)<=50 and [r['rank'] for r in result]==list(range(1,len(result)+1))
        if total==4097:
            # Prove the retained physical HNSW access path on a genuinely large index.
            # A forced-plan diagnostic is separate from default optimizer measurements.
            import json
            conn.execute('ANALYZE')
            conn.execute('SET LOCAL enable_seqscan=off')
            conn.execute("SET LOCAL hnsw.iterative_scan='strict_order'")
            plan=conn.execute('EXPLAIN (ANALYZE, FORMAT JSON, TIMING OFF) SELECT id FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> %s::halfvec LIMIT 256',(vector,)).fetchone()['QUERY PLAN']
            assert 'idx_chunks_embedding' in json.dumps(plan)
            rows=conn.execute('SELECT * FROM filtered_vector_candidates(%s::halfvec,%s,%s,%s,%s,%s,%s,%s,%s)',args).fetchall()
            assert len(rows)<=50
        if total==4096:
            # Independent exhaustive oracle over every eligible chunk, before ordering.
            oracle=conn.execute("""WITH eligible AS MATERIALIZED (
              SELECT c.id,d.id doc_id,d.slug,c.idx,c.embedding FROM chunks c JOIN documents d ON d.id=c.document_id
              WHERE d.project_scope='/synthetic/filter-a' AND d.domain='general' AND d.status='active'
                AND assertion_eligible(d.id,'2026-01-01',false) AND c.embedding IS NOT NULL AND l2_norm(c.embedding)>0
            ), distances AS (SELECT e.*,embedding <=> %s::halfvec distance FROM eligible e),
            ranked AS (SELECT t.*,row_number() OVER(PARTITION BY doc_id ORDER BY distance,idx,id) n FROM distances t)
            SELECT id FROM ranked WHERE n<=2 ORDER BY distance,slug,idx,id LIMIT50""".replace('LIMIT50','LIMIT 50'),(vector,)).fetchall()
            assert [r['chunk_id'] for r in result]==[r['id'] for r in oracle]
            assert {str(r['document_id']) for r in conn.execute('SELECT document_id FROM chunks WHERE id=ANY(%s)',([r['chunk_id'] for r in result],))}=={crowd.doc_id,second.doc_id}



def test_discovery_timeout_preserves_pending_audited_caller_write(vectors,conn,cfg,monkeypatch):
    import psycopg
    vectors()
    with db.connect(cfg,role='writer') as writer:
        pending=store.save_document(writer,cfg,title='Discovery pending write',body='Synthetic retained source.',domain='general',dtype='reference',project='/synthetic/filter-a',commit=False)
        writer.execute("SET LOCAL statement_timeout='40ms'")
        original=settings(writer)
        execute=writer.execute
        def slow_discovery(query,*args,**kwargs):
            if isinstance(query,str) and 'to_regprocedure' in query:
                execute('SELECT pg_sleep(1)')  # Real timeout at this new query boundary.
            return execute(query,*args,**kwargs)
        monkeypatch.setattr(writer,'execute',slow_discovery)
        with pytest.raises(psycopg.errors.QueryCanceled):vector_plan.available(writer)
        assert settings(writer)==original
        assert writer.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone()
        monkeypatch.setattr(writer,'execute',execute)
        assert vector_plan.available(writer)
        writer.rollback()
    assert conn.execute('SELECT id FROM documents WHERE id=%s',(pending.doc_id,)).fetchone() is None
