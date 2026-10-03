"""Behavior tests: preserve original evidence while adding grounded subject context."""
import pytest
from agentic_rag import db, domains, search, store


@pytest.fixture
def indexed(conn,cfg,monkeypatch):
    from agentic_rag import embed,query_cache
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    fields=dict(title='Orion telemetry',body='Overview.\n\n'+('Background. '*410)+'\n\nThe listener uses port 8766.',domain='general',dtype='reference')
    saved=store.save_document(conn,cfg,**fields,scope='global')
    return saved,dict(fields,doc_id=saved.doc_id,index_context=True)


def test_cli_normal_save_retains_required_argument_exit_code(monkeypatch):
    from agentic_rag import cli
    monkeypatch.setattr(cli,'load_config',lambda:pytest.fail('invalid CLI must fail before loading production config'))
    with pytest.raises(SystemExit) as exc:cli.main(['save','--body','Missing title/domain/type'])
    assert exc.value.code==2


def test_queued_reembedding_retains_contextual_lexical_coverage(indexed,conn,cfg,monkeypatch):
    saved,_=indexed
    monkeypatch.setattr(store,'embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    store.reembed_document(conn,cfg,saved.doc_id)
    hits,_=search.search(conn,cfg,'Orion telemetry port 8766',strategy='lexical',rerank_mode='off',k=1)
    assert hits and 'port 8766' in hits[0].snippet


@pytest.mark.parametrize('bad_vectors',[None,[],[[1.0]],[[float('nan')]*1024],[[True]*1024]])
def test_malformed_inference_keeps_original_and_retryable_progress(indexed,conn,cfg,monkeypatch,bad_vectors):
    from agentic_rag import embed
    saved,kw=indexed
    original=conn.execute('SELECT id,content FROM chunks WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:bad_vectors)
    result=store.save_document(conn,cfg,**kw,index_limit=1)
    assert result.indexed_chunks==0 and result.remaining_chunks==len(original) and result.warnings
    assert conn.execute('SELECT id,content FROM chunks WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()==original
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==0


def test_model_replacement_during_indexing_does_not_mislabel_vectors(indexed,conn,cfg,monkeypatch):
    from agentic_rag import query_cache
    _,kw=indexed
    values=iter(['a'*64,'b'*64])
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:next(values))
    result=store.save_document(conn,cfg,**kw)
    assert result.warnings and result.remaining_chunks>0
    assert conn.execute('SELECT count(*) n FROM chunk_contexts WHERE embedding IS NOT NULL').fetchone()['n']==0


def test_missing_model_identity_does_not_call_inference(indexed,conn,cfg,monkeypatch):
    from agentic_rag import embed,query_cache
    _,kw=indexed
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:None)
    monkeypatch.setattr(embed,'try_embed_texts',lambda *a:pytest.fail('unknown model must not be indexed'))
    result=store.save_document(conn,cfg,**kw)
    assert result.warnings and result.remaining_chunks>0


def test_outer_transaction_can_roll_back_context_and_audit_together(indexed,conn,cfg):
    _,kw=indexed
    store.save_document(conn,cfg,**kw,commit=False)
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==1
    conn.rollback()
    assert conn.execute('SELECT count(*) n FROM chunk_contexts WHERE embedding IS NOT NULL').fetchone()['n']==0
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==0


@pytest.mark.parametrize('limit',[0,33,True,1.5,'8'])
def test_bad_index_budget_rejected_before_index_writes(indexed,conn,cfg,limit):
    _,kw=indexed
    with pytest.raises(ValueError,match='index_limit'):store.save_document(conn,cfg,**kw,index_limit=limit)


def test_reader_cannot_write_context_and_writer_cannot_bypass_gateway_table(indexed,conn,cfg):
    import psycopg
    saved,kw=indexed
    with db.connect(cfg,role='reader') as reader:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):store.save_document(reader,cfg,**kw)
    with db.connect(cfg,role='writer') as writer:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            writer.execute('UPDATE chunk_contexts SET context=%s',('changed',))
    with db.connect(cfg,role='writer') as writer:
        assert store.save_document(writer,cfg,**kw,index_limit=1).indexed_chunks==1
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==1


def test_context_obeys_project_domain_status_and_source_freshness(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general');domains.add_domain(conn,'other')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    fields=dict(title='Orion telemetry',body='Overview.\n\n'+('Background. '*410)+'\n\nPort 8766.',dtype='reference')
    eligible=store.save_document(conn,cfg,**fields,domain='general',project='/scope/a')
    store.save_document(conn,cfg,**fields,domain='general',project='/scope/b')
    store.save_document(conn,cfg,**fields,domain='other',project='/scope/a')
    store.save_document(conn,cfg,**fields,domain='general',project='/scope/a',status='archived')
    def hits():return search.search(conn,cfg,'Orion telemetry port 8766',domain='general',project='/scope/a',strategy='lexical',rerank_mode='off')[0]
    assert {h.document_id for h in hits()}=={eligible.doc_id}
    # Audited scope repair invalidates the fingerprint without deleting canonical chunks.
    store.set_project_scope(conn,eligible.doc_id,project='/scope/b')
    assert hits()==[]
    result=search.search(conn,cfg,'Orion telemetry port 8766',domain='general',project='/scope/b',strategy='lexical',rerank_mode='off')[0]
    assert eligible.doc_id not in {h.document_id for h in result}


def test_current_model_only_is_eligible_for_contextual_vector_candidates(indexed,conn,cfg):
    from agentic_rag.embed import vec_literal
    _,kw=indexed
    store.save_document(conn,cfg,**kw)
    vector=vec_literal([1.0]+[0.0]*1023)
    def candidates(digest):
        return conn.execute('SELECT * FROM contextual_search_candidates(%s,%s::halfvec,NULL,150,NULL,now(),false,%s)',('unmatched',vector,digest)).fetchall()
    assert candidates('a'*64)
    assert candidates('b'*64)==[] and candidates(None)==[]


def test_derived_vector_requires_a_nonnull_valid_model_identity(indexed,conn,cfg):
    import psycopg
    from agentic_rag import contextual,embed
    saved,_=indexed
    row=contextual.source_rows(conn,saved.doc_id)[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute('SELECT put_chunk_contexts(%s,%s,%s,%s,%s,%s)',
            (saved.doc_id,[row['id']],[row['context']],[embed.vec_literal([1.0]+[0.0]*1023)],[row['source_hash']],None))
    conn.rollback()


def test_query_model_replacement_does_not_compare_old_query_to_new_context(indexed,conn,cfg,monkeypatch):
    from agentic_rag import query_cache
    _,kw=indexed
    # Only derived contextual vectors exist; raw save deliberately had no vectors.
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'b'*64)
    store.save_document(conn,cfg,**kw)
    current='a'*64
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:current)
    def replace_model(texts,cfg):
        nonlocal current
        current='b'*64
        return [[1.0]+[0.0]*1023]
    monkeypatch.setattr(search,'try_embed_texts',replace_model)
    hits,_=search.search(conn,cfg,'unmatched',rerank_mode='off')
    assert hits==[]


def test_fenced_headings_never_become_active_section_and_prefix_budget_is_bounded():
    from agentic_rag.contextual import prefixes,PREFIX_CHARS
    rows=[{'content':'# Real report 2025\n\n## Revenue USD millions\n\nUnit source.\n```md\n# Fake '},
          {'content':'section\n```\n'+('Tail. '*300)}]
    header=prefixes(rows,'Title'*100,'/private/project')[1]
    section=header.split('Section: ',1)[1].split('\n',1)[0]
    assert 'Revenue USD millions' in section and 'Fake' not in section
    assert len(header)<=PREFIX_CHARS


def test_contextual_assertions_keep_immutability_and_time_eligibility(conn,cfg,monkeypatch):
    from agentic_rag import contextual,embed,query_cache
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    doc=store.save_assertion(conn,cfg,entity='Orion telemetry',attribute='port',value='8766',
        event_at='2026-01-01T00:00:00Z',expires_at='2026-02-01T00:00:00Z',domain='general',scope='global',
        evidence={'source_id':'orion-event','role':'user','quote':'Orion telemetry port 8766','event_at':'2026-01-01T00:00:00Z'})
    canonical=store.get_document(conn,doc.doc_id)
    store.save_document(conn,cfg,doc_id=doc.doc_id,title=canonical['title'],body=canonical['body'],
        domain=canonical['domain'],dtype=canonical['dtype'],index_context=True)
    assert store.get_document(conn,doc.doc_id)==canonical
    query='Orion telemetry port 8766'
    assert search.search(conn,cfg,query,strategy='lexical',rerank_mode='off',as_of='2026-01-15T00:00:00Z')[0]
    assert search.search(conn,cfg,query,strategy='lexical',rerank_mode='off',as_of='2026-03-01T00:00:00Z')[0]==[]
    assert search.search(conn,cfg,query,strategy='lexical',rerank_mode='off',history=True)[0]
    with pytest.raises(ValueError,match='immutable'):
        store.save_document(conn,cfg,title='Changed',body='Changed',domain='general',dtype='memory',doc_id=doc.doc_id)


def test_lock_conflict_aborts_index_without_losing_retry_progress(indexed,conn,cfg):
    import psycopg
    saved,kw=indexed
    with db.connect(cfg,role='writer') as other:
        other.execute('SELECT id FROM documents WHERE id=%s FOR UPDATE',(saved.doc_id,))
        with pytest.raises(psycopg.errors.LockNotAvailable):store.save_document(conn,cfg,**kw)
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==0
    assert store.save_document(conn,cfg,**kw).remaining_chunks==0


def test_queued_reembed_cannot_bind_new_subject_to_old_fact(indexed,conn,cfg,monkeypatch):
    saved,_=indexed
    def concurrent_correction(texts,cfg):
        with db.connect(cfg,role='writer') as writer:
            store.save_document(writer,cfg,title='Corrected telemetry',body='The listener uses port 8767.',
                domain='general',dtype='reference',doc_id=saved.doc_id)
        return [[1.0]+[0.0]*1023 for _ in texts]
    monkeypatch.setattr(store,'embed_texts',concurrent_correction)
    with pytest.raises(ValueError,match='source changed'):store.reembed_document(conn,cfg,saved.doc_id)
    assert conn.execute('SELECT body FROM documents WHERE id=%s',(saved.doc_id,)).fetchone()['body']=='The listener uses port 8767.'
    raw=conn.execute('SELECT content FROM chunks WHERE document_id=%s',(saved.doc_id,)).fetchall()
    assert all('8766' not in r['content'] for r in raw)
    assert search.search(conn,cfg,'Corrected telemetry port 8766',strategy='lexical',rerank_mode='off')[0]==[]


def test_later_port_fact_retains_document_subject_without_rewriting_evidence(conn,cfg,monkeypatch):
    # Mutation: omit context creation or query only original FTS and this loses the fact.
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    body='Deployment overview.\n\n'+('Unrelated installation background. '*140)+'\n\nThe listener uses port 8766.\n'
    saved=store.save_document(conn,cfg,title='Orion telemetry',body=body,domain='general',dtype='reference',scope='global')
    before=conn.execute('SELECT id,content,embedding::text FROM chunks WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()
    hits,warnings=search.search(conn,cfg,'Orion telemetry port 8766',strategy='lexical',rerank_mode='off',k=1)
    assert hits and 'port 8766' in hits[0].snippet
    assert hits[0].document_id==saved.doc_id
    source=next(r for r in before if str(r['id'])==hits[0].chunk_id)['content']
    assert source[hits[0].snippet_start:hits[0].snippet_end]==hits[0].snippet
    assert 'Orion telemetry' not in source
    assert conn.execute('SELECT id,content,embedding::text FROM chunks WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()==before


def test_index_only_save_is_bounded_resumable_and_preserves_raw_rows(conn,cfg,monkeypatch):
    from agentic_rag import embed,query_cache
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    title='Orion telemetry';body='Overview.\n\n'+('Background deployment text. '*170)+'\n\nPort 8766.\n'
    saved=store.save_document(conn,cfg,title=title,body=body,domain='general',dtype='reference',scope='global')
    raw=conn.execute('SELECT row_to_json(c) AS data FROM chunks c WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()
    doc=conn.execute('SELECT row_to_json(d) AS data FROM documents d WHERE id=%s',(saved.doc_id,)).fetchone()
    audits=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    kwargs=dict(title=title,body=body,domain='general',dtype='reference',doc_id=saved.doc_id,index_context=True,index_limit=1)
    result=store.save_document(conn,cfg,**kwargs)
    assert result.indexed_chunks==1 and result.remaining_chunks==len(raw)-1
    for _ in range(len(raw)-1):store.save_document(conn,cfg,**kwargs)
    result=store.save_document(conn,cfg,**kwargs)
    assert result.indexed_chunks==0 and result.remaining_chunks==0
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==audits+len(raw)
    assert conn.execute('SELECT row_to_json(c) AS data FROM chunks c WHERE document_id=%s ORDER BY idx',(saved.doc_id,)).fetchall()==raw
    assert conn.execute('SELECT row_to_json(d) AS data FROM documents d WHERE id=%s',(saved.doc_id,)).fetchone()==doc


def test_explicit_context_off_preserves_old_lexical_path(conn,cfg,monkeypatch):
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    body='Overview.\n\n'+('Setup background. '*270)+'\n\nThe listener uses port 8766.'
    store.save_document(conn,cfg,title='Orion telemetry',body=body,domain='general',dtype='reference',scope='global')
    hits,_=search.search(conn,cfg,'Orion telemetry port 8766',strategy='lexical',context_mode='off',rerank_mode='off')
    assert hits==[]


def test_cli_index_only_save_uses_existing_audited_gateway(conn,cfg,monkeypatch,capsys):
    import json
    from agentic_rag import cli,embed,query_cache
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    monkeypatch.setattr(cli,'load_config',lambda:cfg)
    saved=store.save_document(conn,cfg,title='Telemetry',body='Port 8766.',domain='general',dtype='reference',scope='global')
    assert cli.main(['save','--index-context',saved.slug,'--index-limit','1'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['indexed_chunks']==1 and result['remaining_chunks']==0
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='index_context'").fetchone()['n']==1


def test_heading_continuation_across_hard_chunk_boundary_is_grounded():
    from agentic_rag.contextual import prefixes
    rows=[{'content':'# Annual report 2025\n\n## Rev'},{'content':'enue USD millions\n\nGrowth was 18.5 percent.'}]
    header=prefixes(rows,'Annual report 2025','global')[1]
    assert 'Revenue USD millions' in header
    assert '2025' in header


def test_change_between_document_and_chunk_reads_cannot_bind_old_subject_to_new_source(conn,cfg,monkeypatch):
    import psycopg
    from agentic_rag import contextual,embed,query_cache
    domains.add_domain(conn,'general')
    monkeypatch.setattr(store,'try_embed_texts',lambda texts,cfg:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    monkeypatch.setattr(embed,'try_embed_texts',lambda texts,cfg:[[1.0]+[0.0]*1023 for _ in texts])
    saved=store.save_document(conn,cfg,title='Old subject',body='Port 8766.',domain='general',dtype='reference',scope='global')
    original=contextual.source_rows;changed=False
    def raced(*a,**kw):
        nonlocal changed
        if not changed:
            changed=True
            with db.connect(cfg,role='writer') as writer:
                store.save_document(writer,cfg,title='Corrected subject',body='Port 8767.',domain='general',dtype='reference',doc_id=saved.doc_id)
        return original(*a,**kw)
    monkeypatch.setattr(contextual,'source_rows',raced)
    with pytest.raises(psycopg.errors.RaiseException,match='source changed'):
        store.save_document(conn,cfg,title='Old subject',body='Port 8766.',domain='general',dtype='reference',doc_id=saved.doc_id,index_context=True)
    doc=conn.execute('SELECT title,body FROM documents WHERE id=%s',(saved.doc_id,)).fetchone()
    assert doc=={'title':'Corrected subject','body':'Port 8767.'}
    assert conn.execute("SELECT count(*) n FROM chunk_contexts WHERE context LIKE '%%Old subject%%'").fetchone()['n']==0
