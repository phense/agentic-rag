"""Typed metadata contracts: removing validation or gating after LIMIT must fail."""
import json
from dataclasses import replace
import pytest
from agentic_rag.config import Config, load_config
from agentic_rag import store

REGISTRY = {'team':'string','cost':'number','done':'boolean','day':'date','when':'timestamp','tags':'string[]'}

def leaf(field, op, value):
    return {'version':1,'where':{'field':field,'op':op,'value':value}}

@pytest.mark.parametrize('field,op,value', [('app.cost','eq',True),('app.day','eq','2026-02-30'),
    ('app.when','eq','2026-01-01T00:00:00'),('app.absent','eq','x'),('domain','eq','general'),
    ('app.team','regex','.*'),('app.team','contains','x'*257),('app.tags','has_any',['x',3])])
def test_bad_filter_is_rejected_without_values_in_error(field,op,value):
    from agentic_rag.metadata import normalize, MetadataError
    with pytest.raises(MetadataError) as failure: normalize(leaf(field,op,value),REGISTRY)
    assert str(failure.value)=='invalid_filter'


def test_duplicate_keys_and_empty_groups_are_rejected():
    from agentic_rag.metadata import normalize, MetadataError
    for value in ['{"version":1,"version":1,"where":{"and":[]}}',{'version':1,'where':{'or':[]}},
                  {'version':1,'where':{'field':'dtype','op':'eq','value':'memory','sql':'true'}}]:
        with pytest.raises(MetadataError): normalize(value,REGISTRY)


def test_registry_config_and_schema_are_one_contract(tmp_path):
    from agentic_rag.metadata import schema, normalize
    path=tmp_path/'config.toml';path.write_text('[metadata.fields]\nteam="string"\ncost="number"\n')
    cfg=load_config(path)
    assert cfg.metadata_fields=={'team':'string','cost':'number'}
    assert schema(cfg)['capability']=='typed_metadata1'
    assert schema(cfg)['application_fields']==dict(cfg.metadata_fields)
    assert normalize(leaf('app.when','eq','2026-01-01T01:00:00+01:00'),REGISTRY)['where']['value']=='2026-01-01T00:00:00Z'
    with pytest.raises(TypeError):cfg.metadata_fields['wrong']='number'


def test_audited_save_preserves_reserved_meta_and_merges_registered_labels(conn,cfg,monkeypatch):
    conn.execute("INSERT INTO domains(name) VALUES('general') ON CONFLICT DO NOTHING");conn.commit()
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    cfg=replace(cfg,metadata_fields=REGISTRY)
    saved=store.save_document(conn,cfg,title='Typed',body='typed quasar',domain='general',dtype='memory',
        meta={'reserved':{'keep':True}},metadata={'team':'alpha','cost':3,'done':None})
    store.save_document(conn,cfg,title='Typed',body='typed quasar',domain='general',dtype='memory',
        doc_id=saved.doc_id,metadata={'cost':4})
    meta=conn.execute('SELECT meta FROM documents WHERE id=%s',(saved.doc_id,)).fetchone()['meta']
    assert meta=={'reserved':{'keep':True},'application':{'version':1,'values':{'team':'alpha','cost':4,'done':None}}}
    assert conn.execute('SELECT count(*) n FROM audit_log WHERE document_id=%s',(saved.doc_id,)).fetchone()['n']==2


def test_sql_presence_null_wrong_type_and_not_are_total_booleans(conn,cfg,monkeypatch):
    from agentic_rag.metadata import normalize
    from psycopg.types.json import Jsonb
    conn.execute("INSERT INTO domains(name) VALUES('general') ON CONFLICT DO NOTHING");conn.commit()
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    cfg=replace(cfg,metadata_fields=REGISTRY)
    ids=[]
    for metadata in [{},{'cost':None},{'cost':2},{'cost':3}]:
        ids.append(store.save_document(conn,cfg,title='Truth',body='quasar',domain='general',dtype='memory',metadata=metadata).doc_id)
    for node,expected in [(leaf('app.cost','exists',True),ids[1:]),(leaf('app.cost','is_null',True),ids[1:2]),
                          (leaf('app.cost','ne',2),ids[3:]),
                          ({'version':1,'where':{'not':leaf('app.cost','eq',2)['where']}},[ids[0],ids[1],ids[3]])]:
        result=conn.execute('SELECT id FROM documents d WHERE public.rag_metadata_document(d.id,%s) ORDER BY created_at,id',(Jsonb(normalize(node,REGISTRY)),)).fetchall()
        assert set(str(r['id']) for r in result)==set(expected)


def test_filter_precedes_lexical_candidate_limits_and_default_is_unchanged(conn,cfg,monkeypatch):
    from agentic_rag.search import search
    conn.execute("INSERT INTO domains(name) VALUES('general') ON CONFLICT DO NOTHING");conn.commit()
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    cfg=replace(cfg,metadata_fields=REGISTRY)
    for i in range(55):store.save_document(conn,cfg,title=f'Noise {i}',body='quasar '*12,domain='general',dtype='memory',metadata={'team':'other'})
    target=store.save_document(conn,cfg,title='Wanted',body='quasar',domain='general',dtype='memory',metadata={'team':'wanted'})
    old=search(conn,cfg,'quasar',strategy='lexical',context_mode='off',rerank_mode='off')[0]
    assert old and target.doc_id not in [h.document_id for h in old]
    for mode in ['off','auto']:
        hits,warnings=search(conn,cfg,'quasar',strategy='lexical',context_mode=mode,rerank_mode='off',filter=leaf('app.team','eq','wanted'))
        assert [h.document_id for h in hits]==[target.doc_id]
    assert [h.document_id for h in search(conn,cfg,'quasar',strategy='lexical',context_mode='off',rerank_mode='off')[0]]==[h.document_id for h in old]


def test_direct_sql_matcher_rejects_unbounded_ast(conn):
    # Without the SQL guard a direct caller bypasses every Python bound.
    import psycopg
    from psycopg.types.json import Jsonb
    node={'field':'dtype','op':'eq','value':'memory','type':'string'}
    for _ in range(8):node={'not':node}
    for bad in (node,{'or':[{'field':'dtype','op':'eq','value':'memory','type':'string'}]*65}):
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            with conn.transaction():conn.execute('SELECT public.rag_metadata_match(%s,%s)',(Jsonb({'dtype':'memory'}),Jsonb(bad)))
