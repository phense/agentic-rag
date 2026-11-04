"""Optional metadata narrows candidates while truth and authority stay mandatory."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import pytest
from agentic_rag import store,search,graph,thematic,context,domains,metadata,query_cache,embed
from agentic_rag.store import EdgeSpec
from test_metadata_filters import leaf
from test_provider_indexes import managed

@pytest.fixture
def typed(conn,cfg,monkeypatch):
    domains.seed_defaults(conn)
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    return replace(cfg,metadata_fields={'team':'string'})

def put(conn,cfg,name,team='yes',body='Provider outage original.',**kw):
    return store.save_document(conn,cfg,title=name,slug=name,body=body,domain='general',dtype='lesson',
        project='/synthetic/metadata',metadata={'team':team},**kw)


def test_nonmatching_replacement_still_supersedes_matching_old(conn,typed):
    now=datetime.now(timezone.utc)
    old=store.save_assertion(conn,typed,entity='deployment',attribute='port',value='Metadata blue',
        event_at=(now-timedelta(days=2)).isoformat(),domain='general',project='/synthetic/metadata',
        evidence={'source_id':'blue','role':'user','quote':'Metadata blue'})
    new=store.save_assertion(conn,typed,entity='deployment',attribute='port',value='Metadata red',
        event_at=(now-timedelta(days=1)).isoformat(),relation='replacement',domain='general',project='/synthetic/metadata',
        evidence={'source_id':'red','role':'user','quote':'Metadata red'})
    slug=conn.execute('SELECT slug FROM documents WHERE id=%s',(old.doc_id,)).fetchone()['slug']
    chosen=leaf('slug','eq',slug)
    hits,_=search.search(conn,typed,'Metadata',strategy='lexical',project='/synthetic/metadata',filter=chosen)
    assert hits==[]
    historical,_=search.search(conn,typed,'Metadata',strategy='lexical',project='/synthetic/metadata',history=True,filter=chosen)
    assert [h.document_id for h in historical]==[old.doc_id]
    assert new.doc_id!=old.doc_id


def test_graph_cannot_cross_nonmatching_bridge(conn,typed):
    c=put(conn,typed,'end')
    b=put(conn,typed,'bridge',team='no',edges=[EdgeSpec('references','end')])
    a=put(conn,typed,'start',edges=[EdgeSpec('references','bridge')])
    assert graph.path(conn,a.doc_id,c.doc_id,project='/synthetic/metadata')
    chosen=leaf('app.team','eq','yes')
    assert graph.path(conn,a.doc_id,c.doc_id,project='/synthetic/metadata',filter=chosen,cfg=typed)==[]
    assert graph.neighbors(conn,a.doc_id,depth=2,project='/synthetic/metadata',filter=chosen,cfg=typed)==[]
    assert graph.timeline(conn,a.doc_id,filter=chosen,cfg=typed)==[]


def test_filtered_summary_context_and_counts_use_only_matching_originals(conn,typed):
    good=put(conn,typed,'allowed')
    bad=put(conn,typed,'hidden',team='no',body='Provider outage forbidden mixed text.')
    store.refresh_summaries(conn,typed,'provider-outages',project='/synthetic/metadata')
    before=conn.execute('SELECT entries,revision,generated_at FROM thematic_summaries').fetchall()
    chosen=leaf('app.team','eq','yes')
    packet=thematic.read(conn,typed,'provider-outages',project='/synthetic/metadata',filter=chosen)
    assert [r['document_id'] for r in packet['entries']]==[good.doc_id]
    assert 'forbidden' not in packet['context']
    ctx=context.build(conn,typed,project='/synthetic/metadata',filter=chosen)
    assert ctx['document_ids']==[good.doc_id] and 'forbidden' not in ctx['text']
    assert ctx['profile_status']=='filtered-originals' and ctx['warnings']
    assert conn.execute('SELECT entries,revision,generated_at FROM thematic_summaries').fetchall()==before
    result=domains.list_domains(conn,cfg=typed,project='/synthetic/metadata',filter=chosen)
    assert sum(r.docs for r in result)==1


@pytest.mark.parametrize('planned,contextual',[(False,False),(False,True),(True,True)])
def test_filtered_vectors_keep_far_matching_original_before_ann_limit(conn,typed,monkeypatch,planned,contextual):
    def vectors(texts,cfg):return [[.7,.7]+[0.0]*1022 if 'Far' in t else [1.0]+[0.0]*1023 for t in texts]
    monkeypatch.setattr(store,'try_embed_texts',vectors);monkeypatch.setattr(search,'try_embed_texts',vectors)
    monkeypatch.setattr(embed,'try_embed_texts',vectors);monkeypatch.setattr(query_cache,'model_digest',lambda cfg:'a'*64)
    typed=replace(typed,retrieval_planned_vectors=planned)
    # 270 closer chunks of nonmatching originals must never fill the ANN pool.
    for i in range(270):put(conn,typed,'near'+str(i),team='no',body='Near neutral observation.')
    good_ids={put(conn,typed,'far'+str(i),body='Far independent observation.').doc_id for i in range(300)}
    good=type('Saved',(),{'doc_id':sorted(good_ids)[0]})()
    if contextual:
        row=conn.execute('SELECT title,body,domain,dtype FROM documents WHERE id=%s',(good.doc_id,)).fetchone()
        store.save_document(conn,typed,**row,doc_id=good.doc_id,index_context=True)
    hits,warnings=search.search(conn,typed,'quasar',project='/synthetic/metadata',strategy='hybrid' if not contextual else 'auto',
        context_mode='auto' if contextual else 'off',rerank_mode='off',filter=leaf('app.team','eq','yes'))
    assert len(hits)==8 and {h.document_id for h in hits}<=good_ids and not warnings


def test_managed_vectors_apply_metadata_before_candidate_limits(conn,managed):
    ix,cfg,save=managed;cfg=replace(cfg,metadata_fields={'team':'string'})
    for title,label in [('One','no'),('Two','yes')]:
        doc,chunk=save(title)
        conn.execute('UPDATE documents SET meta=%s WHERE id=%s',(json.dumps({'application':{'version':1,'values':{'team':label}}}),doc))
        if label=='yes':target=str(doc)
    ix.create(conn,cfg,'typed','two');ix.build(conn,cfg,'typed',allow_corpus=True);ix.activate(conn,cfg,'typed')
    hits,warnings=search.search(conn,cfg,'quasar',rerank_mode='off',filter=leaf('app.team','eq','yes'))
    assert [h.document_id for h in hits]==[target] and warnings==[]


def test_filtered_timeout_is_explicit_and_restores_transaction(conn,typed):
    put(conn,typed,'allowed')
    # Force only the optional matcher to exceed the caller's shorter deadline.
    conn.execute('''CREATE OR REPLACE FUNCTION public.rag_metadata_document(p_id uuid,p_filter jsonb) RETURNS boolean
        LANGUAGE plpgsql STABLE AS $$ BEGIN PERFORM pg_sleep(.15);RETURN true;END $$''')
    conn.execute("SET LOCAL statement_timeout='50ms'")
    with pytest.raises(metadata.MetadataError,match='filter_budget'):
        search.search(conn,typed,'Provider',strategy='lexical',filter=leaf('app.team','eq','yes'))
    assert conn.execute('SHOW statement_timeout').fetchone()['statement_timeout']=='50ms'
    assert conn.execute('SELECT 1 n').fetchone()['n']==1


def test_real_child_research_preserves_filter_and_original_spans(conn,typed):
    from agentic_rag import research
    good=put(conn,typed,'allowed',body='Provider outage unique allowed original.')
    bad=put(conn,typed,'excluded',team='no',body='Provider outage forbidden original.')
    packet=research.research(typed,'Provider outage',project='/synthetic/metadata',strategy='lexical',filter=leaf('app.team','eq','yes'))
    assert packet['evidence'],packet
    assert {r['document_id'] for r in packet['evidence']}=={good.doc_id}
    assert 'forbidden' not in json.dumps(packet)
    for row in packet['evidence']:
        text=conn.execute('SELECT content FROM chunks WHERE id=%s',(row['chunk_id'],)).fetchone()['content']
        assert text[row['start']:row['end']]==row['text']


def test_real_cli_schema_save_and_filter_file(conn,cfg,tmp_path,monkeypatch,capsys):
    from agentic_rag.cli import main
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    domains.seed_defaults(conn)
    config=tmp_path/'metadata.toml';config.write_text(f'[db]\nname="{cfg.db_name}"\n[ollama]\nurl="http://localhost:1"\n[metadata.fields]\nteam="string"\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG',str(config))
    assert main(['metadata','schema'])==0
    assert json.loads(capsys.readouterr().out)['application_fields']=={'team':'string'}
    assert main(['save','--title','Typed CLI','--body','quasar original','--dtype','memory','--domain','general','--scope','global','--metadata-json','{"team":"yes"}'])==0
    capsys.readouterr()
    chosen=tmp_path/'filter.json';chosen.write_text(json.dumps(leaf('app.team','eq','yes')))
    assert main(['search','quasar','--strategy','lexical','--rerank','off','--filter-file',str(chosen),'--json'])==0
    packet=json.loads(capsys.readouterr().out)
    assert [r['slug'] for r in packet['results']]==['typed-cli']
    chosen.write_text('{"version":1,"version":1,"where":{}}')
    assert main(['search','quasar','--filter-file',str(chosen)])!=0


def test_audit_failure_rolls_back_metadata_text_and_chunks(conn,typed):
    import psycopg
    good=put(conn,typed,'allowed')
    before=conn.execute('SELECT body,meta FROM documents WHERE id=%s',(good.doc_id,)).fetchone()
    chunks=conn.execute('SELECT id,content FROM chunks WHERE document_id=%s',(good.doc_id,)).fetchall()
    conn.execute("CREATE FUNCTION deny_metadata_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected audit failure';END $$")
    conn.execute('CREATE TRIGGER deny_metadata BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION deny_metadata_audit()')
    conn.commit()
    try:
        with pytest.raises(psycopg.errors.RaiseException,match='injected audit failure'):
            store.save_document(conn,typed,title='allowed',body='Changed original',domain='general',dtype='lesson',doc_id=good.doc_id,metadata={'team':'other'})
        assert conn.execute('SELECT body,meta FROM documents WHERE id=%s',(good.doc_id,)).fetchone()==before
        assert conn.execute('SELECT id,content FROM chunks WHERE document_id=%s',(good.doc_id,)).fetchall()==chunks
    finally:
        conn.execute('DROP TRIGGER deny_metadata ON audit_log');conn.execute('DROP FUNCTION deny_metadata_audit()');conn.commit()
