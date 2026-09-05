import pytest
from agentic_rag import store,search
from agentic_rag.domains import seed_defaults

@pytest.fixture(autouse=True)
def setup(conn,monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)

def save(conn,cfg,title,body):
    return store.save_document(conn,cfg,title=title,body=body,domain='general',dtype='memory',project='/synthetic/a')

def test_diversity_and_late_span_with_stable_citation(conn,cfg):
    crowded=save(conn,cfg,'A repeated','\n\n'.join('## Part '+str(i)+'\n'+'Zebra repair. '*100 for i in range(60)))
    second=save(conn,cfg,'B answer','Zebra repair requires restart.')
    hits,_=search.search(conn,cfg,'Zebra repair',k=2,project='/synthetic/a')
    assert {h.document_id for h in hits}=={crowded.doc_id,second.doc_id}
    late=save(conn,cfg,'Late',('padding '*180)+'UniqueError42 repair uses switch 8172.')
    hits,_=search.search(conn,cfg,'UniqueError42',project='/synthetic/a')
    hit=next(h for h in hits if h.document_id==late.doc_id)
    assert 'UniqueError42' in hit.snippet and hit.snippet_start>400
    text=conn.execute('SELECT content FROM chunks WHERE id=%s',(hit.chunk_id,)).fetchone()['content']
    assert text[hit.snippet_start:hit.snippet_end]==hit.snippet
    assert hit.citation==f'{hit.document_id}#{hit.chunk_id}:{hit.snippet_start}-{hit.snippet_end}'


def test_extra_chunk_retained_only_for_distinct_terms(conn,cfg):
    doc=save(conn,cfg,'Multi','alpha '*650+'\n\n'+'beta '*850)
    hits,_=search.search(conn,cfg,'alpha OR beta',k=3,project='/synthetic/a')
    assert len(hits)==2 and all(h.document_id==doc.doc_id for h in hits)
    assert any('alpha' in h.snippet for h in hits) and any('beta' in h.snippet for h in hits)


def test_reranker_failure_and_embedding_fallback(conn,cfg):
    save(conn,cfg,'One','zebra repair');save(conn,cfg,'Two','zebra repair alternate')
    baseline,_=search.search(conn,cfg,'zebra repair')
    def failed(hits):raise RuntimeError('local reranker down')
    actual,warnings=search.search(conn,cfg,'zebra repair',reranker=failed)
    assert [h.citation for h in actual]==[h.citation for h in baseline]
    assert any('reranker' in w for w in warnings)
    assert any('full-text' in w for w in warnings)


def test_bounded_multihop_respects_scope_and_evidence(conn,cfg):
    leaf=save(conn,cfg,'Leaf','Destination is rack 8172.')
    middle=store.save_document(conn,cfg,title='Middle',body='Topology intermediate',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',leaf.slug,evidence='topology source')])
    root=store.save_document(conn,cfg,title='Root',body='Zebra topology entry',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',middle.slug,evidence='topology source')])
    hits,_=search.search(conn,cfg,'Zebra',k=4,project='/synthetic/a',graph_depth=2)
    assert {h.document_id for h in hits}=={root.doc_id,middle.doc_id,leaf.doc_id}
    assert next(h for h in hits if h.document_id==leaf.doc_id).graph_depth==2
    store.set_project_scope(conn,middle.doc_id,project='/synthetic/b')
    hits,_=search.search(conn,cfg,'Zebra',k=4,project='/synthetic/a',graph_depth=2)
    assert [h.document_id for h in hits]==[root.doc_id]


def test_exact_symbols_and_untrusted_reranker_payload(conn,cfg):
    from dataclasses import replace
    doc=save(conn,cfg,'Exact','Namespace::Error42 needs repair.')
    assert search.search(conn,cfg,'Namespace::Error42')[0]
    assert search.search(conn,cfg,'Namespace::Error420')[0]==[]
    def mutate(hits):return [replace(h,document_id='outside') for h in hits]
    hits,warnings=search.search(conn,cfg,'repair',reranker=mutate)
    assert hits[0].document_id==doc.doc_id and any('reranker' in w for w in warnings)


def test_ties_are_repeatable_and_german_fts_remains(conn,cfg):
    for title in ('Beta','Alpha'):save(conn,cfg,title,'Der Server benötigt einen Neustart nach dem Fehler.')
    first=search.search(conn,cfg,'Server Neustart')[0]
    second=search.search(conn,cfg,'Server Neustart')[0]
    assert [h.citation for h in first]==[h.citation for h in second]
    assert len(first)==2


def test_graph_walks_existing_nonseed_hit_without_duplicate_results(conn,cfg):
    leaf=save(conn,cfg,'Leaf','Hidden rack 2189.')
    middle=store.save_document(conn,cfg,title='Z middle',body='Zebra bridge',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',leaf.slug,evidence='diagram')])
    root=store.save_document(conn,cfg,title='A root',body='Zebra entry',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',middle.slug,evidence='diagram')])
    save(conn,cfg,'B distractor','Zebra unrelated one')
    save(conn,cfg,'C distractor','Zebra unrelated two')
    hits,_=search.search(conn,cfg,'Zebra',k=8,project='/synthetic/a',graph_depth=2,
                         reranker=lambda items:sorted(items,key=lambda h:h.title))
    ids=[h.document_id for h in hits]
    assert leaf.doc_id in ids
    assert len(ids)==len(set(ids))


def test_exact_error_takes_precedence_over_generic_span_matches():
    from agentic_rag.retrieval import evidence_span
    content='repair diagnostic restart switch '+('padding '*150)+'UniqueError42'
    snippet,start,end=evidence_span(content,'repair diagnostic restart switch UniqueError42')
    assert 'UniqueError42' in snippet
    assert content[start:end]==snippet


def test_graph_refuted_bridge_blocks_current_walk_but_history_is_explicit(conn,cfg):
    from agentic_rag import evidence
    leaf=save(conn,cfg,'Leaf','Destination hidden 8821.')
    body='This bridge links the topology.'
    middle=store.save_claim(conn,cfg,title='Bridge',body=body,domain='general',dtype='memory',project='/synthetic/a',claim_kind='stated',
        evidence=[{'namespace':'synthetic','source_id':'bridge','role':'user','quote':body,'complete':True}],
        edges=[store.EdgeSpec('references',leaf.slug,evidence='diagram')])
    root=store.save_document(conn,cfg,title='Root',body='Zebra start',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',middle.slug,evidence='diagram')])
    def ids(**kwargs):return {h.document_id for h in search.search(conn,cfg,'Zebra',graph_depth=2,project='/synthetic/a',**kwargs)[0]}
    assert ids()=={root.doc_id,middle.doc_id,leaf.doc_id}
    store.set_source_state(conn,evidence.sources(conn,middle.doc_id)[0]['source_key'],state='refuted',reason='synthetic correction')
    assert ids()=={root.doc_id}
    assert ids(history=True)=={root.doc_id,middle.doc_id,leaf.doc_id}


def test_graph_edge_evidence_time_and_expired_assertion_before_limit(conn,cfg):
    expired=store.save_assertion(conn,cfg,entity='rack',attribute='id',value='7318',domain='general',project='/synthetic/a',event_at='2025-01-01T00:00:00Z',expires_at='2025-02-01T00:00:00Z',
        evidence={'source_id':'expired','role':'user','quote':'rack7318','event_at':'2025-01-01T00:00:00Z'})
    good=save(conn,cfg,'Z eligible','Good hidden destination')
    edges=[store.EdgeSpec('references',expired.slug,evidence='old source'),store.EdgeSpec('references',good.slug,evidence='diagram')]
    for i in range(10):
        missing=save(conn,cfg,f'A no evidence {i}','Untrusted neighboring destination '+str(i))
        edges.append(store.EdgeSpec('references',missing.slug))
    root=store.save_document(conn,cfg,title='Root',body='Zebra start',domain='general',dtype='memory',project='/synthetic/a',edges=edges)
    def ids(**kw):return {h.document_id for h in search.search(conn,cfg,'Zebra',graph_depth=2,project='/synthetic/a',**kw)[0]}
    assert ids()=={root.doc_id,good.doc_id}
    # Owner-only fixture clock control in agentic_rag_test; no production edge mutation.
    conn.execute("UPDATE edges SET valid_from='2025-01-01', valid_to='2025-02-01' WHERE src_id=%s",(root.doc_id,))
    assert ids()=={root.doc_id}
    assert ids(as_of='2025-01-15T00:00:00Z')=={root.doc_id,good.doc_id,expired.doc_id}
    assert ids(history=True)=={root.doc_id,good.doc_id,expired.doc_id}


def test_graph_has_seed_edge_discovery_and_final_result_budgets(conn,cfg):
    roots=[]
    for i in range(4):
        edges=[]
        for j in range(10):
            leaf=save(conn,cfg,f'Leaf {i} {j}',f'Hidden destination {i} {j}')
            edges.append(store.EdgeSpec('references',leaf.slug,evidence='diagram'))
        roots.append(store.save_document(conn,cfg,title=f'Root {i}',body=f'Zebra entry {i}',domain='general',dtype='memory',project='/synthetic/a',edges=edges))
    hits,_=search.search(conn,cfg,'Zebra',k=100,graph_depth=2,project='/synthetic/a')
    expanded=[h for h in hits if h.graph_depth]
    assert len(expanded)==20 and len(hits)==24
    assert max(sum(h.title.startswith(f'Leaf {i} ') for h in expanded) for i in range(4))<=8
    assert len(search.search(conn,cfg,'Zebra',k=2,graph_depth=2,project='/synthetic/a')[0])==2


def test_vector_only_pool_diversity_and_reader_privileges(conn,cfg,monkeypatch):
    from agentic_rag import db
    # Controlled nonzero vectors distinguish near duplicate chunks from the second
    # source; query words never occur in documents, so FTS cannot rescue this case.
    def vectors(texts,*args):
        return [[0.9,0.1]+[0.0]*1022 if 'cobalt' in text else [1.0]+[0.0]*1023 for text in texts]
    monkeypatch.setattr(store,'try_embed_texts',vectors)
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:[[1.0]+[0.0]*1023])
    crowd=save(conn,cfg,'Crowd','\n\n'.join('## Part '+str(i)+'\n'+'repeated content. '*100 for i in range(65)))
    other=save(conn,cfg,'Second','Independent cobalt destination.')
    with db.connect(cfg,role='reader') as reader:
        hits,_=search.search(reader,cfg,'semanticquerynotindocuments',k=2,project='/synthetic/a')
        assert {h.document_id for h in hits}=={crowd.doc_id,other.doc_id}
        # Function-local ANN tuning must not leak into the reader session.
        assert reader.execute('SHOW hnsw.ef_search').fetchone()['hnsw.ef_search']=='40'
