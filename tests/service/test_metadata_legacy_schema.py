"""Current readers must work before039; OR NULL cannot hide a missing function."""
from dataclasses import replace
from datetime import datetime, timezone
import json

import psycopg
import pytest

from agentic_rag import db, entities, graph, indexes, metadata, providers, research, search, thematic
from agentic_rag.benchmark import corrections
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.research_exploration import entity_candidates
from .test_metadata_upgrade import archive
from .test_feedback_upgrade import run_code

SEED = r'''
from agentic_rag import store
from agentic_rag.store import EdgeSpec
store.try_embed_texts=lambda *a,**k:None
db.init_db(cfg)
with db.connect(cfg) as conn:
 end=store.save_document(conn,cfg,title='Legacy neighbor',slug='legacy-neighbor',body='Separate original neighbor.',domain='general',dtype='memory',project='/projects/alpha')
 start=store.save_document(conn,cfg,title='Legacy selector',slug='legacy-selector',body='Provider outage original anchor.',domain='general',dtype='memory',project='/projects/alpha',edges=[EdgeSpec('references','legacy-neighbor',evidence='Original explicit relation')])
 old=store.save_assertion(conn,cfg,entity='lyra',attribute='port',value='8765',domain='general',project='/projects/alpha',event_at='2026-01-01T00:00:00Z',evidence={'namespace':'legacy73','source_id':'old','role':'user','quote':'lyra port 8765','complete':True})
 fact=store.save_assertion(conn,cfg,entity='lyra',attribute='port',value='8766',domain='general',project='/projects/alpha',relation='replacement',event_at='2026-02-01T00:00:00Z',evidence={'namespace':'legacy73','source_id':'new','role':'user','quote':'lyra port 8766','complete':True})
 for item in [old,fact]:store.review_claim(conn,item.doc_id,state='confirmed',reason='Synthetic original inspected')
 alias=store.save_entity_alias(conn,cfg,alias='lyra-retired',target='lyra',domain='general',project='/projects/alpha',effective_at='2026-03-01T00:00:00Z',confirm=True,evidence={'namespace':'legacy73','source_id':'alias','role':'user','quote':'lyra-retired is another name for lyra.','complete':True})
print(json.dumps({'start':start.doc_id,'end':end.doc_id,'old':old.doc_id,'fact':fact.doc_id,'alias':alias['document_id']}))
'''


@pytest.fixture(scope='module')
def archived(tmp_path_factory):
    source=archive(tmp_path_factory.mktemp('metadata-legacy029'))
    with isolated_database(Config(),initialize=False) as cfg:
        ids=run_code(source,cfg,SEED)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM schema_migrations').fetchone()['n']==38
            assert conn.execute("SELECT to_regprocedure('public.rag_metadata_document(uuid,jsonb)') missing").fetchone()['missing'] is None
        yield cfg,ids


class ObservedConnection:
    """Observe actual server failures even when an optional reader catches them."""
    def __init__(self,conn):self.conn,self.failures=conn,[]
    def __getattr__(self,name):return getattr(self.conn,name)
    def execute(self,*args,**kwargs):
        try:return self.conn.execute(*args,**kwargs)
        except psycopg.Error as exc:
            self.failures.append({'sqlstate':exc.sqlstate,'message':str(exc).splitlines()[0]})
            print('LEGACY_SQL_FAILURE',json.dumps(self.failures[-1]))
            raise


@pytest.fixture
def legacy(archived):
    cfg,ids=archived
    with db.connect(cfg) as conn:
        yield ObservedConnection(conn),cfg,ids


@pytest.mark.parametrize('operation',['identity','entity','entity_candidates','timeline','neighbors','expansion','theme','research','export'])
def test_archived029_no_filter_preserves_original_reads(legacy,tmp_path,operation):
    # Mutation: a no-filter query mentions039 even behind `NULL OR ...`.
    conn,cfg,ids=legacy
    selected={'domain':'general','project':'/projects/alpha'}
    at=datetime.now(timezone.utc)
    if operation=='identity':
        hits,_=search.search(conn,cfg,ids['start'],strategy='auto',rerank_mode='off',**selected)
        assert [h.document_id for h in hits]==[ids['start']]
    elif operation=='entity':
        packet=entities.read(conn,'lyra-retired',**selected)
        assert packet['status']=='resolved' and [f['document_id'] for f in packet['facts']]==[ids['fact']]
    elif operation=='entity_candidates':
        rows=entity_candidates(conn,'lyra-retired port',domain='general',scopes=['/projects/alpha'],at=at,history=False)
        assert [r['name'] for r in rows]==['lyra-retired']
    elif operation=='timeline':
        assert [(e.src_slug,e.dst_slug) for e in graph.timeline(conn,ids['start'])]==[('legacy-selector','legacy-neighbor')]
    elif operation=='neighbors':
        rows=graph.research_neighbors(conn,ids['start'],domain='general',scopes=['/projects/alpha'],at=at,history=False)
        assert [str(r['id']) for r in rows]==[ids['end']]
    elif operation=='expansion':
        hits,_=search.search(conn,cfg,'Provider outage',strategy='lexical',rerank_mode='off',graph_depth=1,**selected)
        assert {h.document_id for h in hits}=={ids['start'],ids['end']}
    elif operation=='theme':
        _,rows,_=thematic._state(conn,'provider-outages',['/projects/alpha'],'general',False,'synthetic-key')
        assert [str(r['document_id']) for r in rows]==[ids['start']]
        assert thematic.read(conn,cfg,'provider-outages',**selected)['status']!='unavailable'
    elif operation=='research':
        packet=research.research(cfg,'lyra-retired port',strategy='lexical',**selected)
        assert ids['fact'] in {e['document_id'] for e in packet['evidence']}
        assert not any('UndefinedFunction' in w for w in packet['warnings'])
    else:
        path=tmp_path/'legacy-corrections.json'
        report=corrections.export_confirmed_corrections(cfg,output_path=path,**selected)
        assert report['cases']==1
        assert json.loads(path.read_text())['cases'][0]['document_id']==ids['fact']
    assert conn.failures==[]


@pytest.mark.parametrize('operation',['search','entity','timeline','theme','research','export'])
def test_archived029_explicit_filter_is_refused_before039(legacy,tmp_path,operation):
    conn,cfg,ids=legacy
    selected={'domain':'general','project':'/projects/alpha'}
    chosen={'version':1,'where':{'field':'dtype','op':'eq','value':'memory'}}
    with pytest.raises(metadata.MetadataError,match='^unsupported_filter$'):
        if operation=='search':search.search(conn,cfg,'Provider',filter=chosen,**selected)
        elif operation=='entity':entities.read(conn,'lyra',filter=chosen,cfg=cfg,**selected)
        elif operation=='timeline':graph.timeline(conn,ids['start'],filter=chosen,cfg=cfg)
        elif operation=='theme':thematic.read(conn,cfg,'provider-outages',filter=chosen,**selected)
        elif operation=='research':research.research(cfg,'lyra port',filter=chosen,**selected)
        else:corrections.export_confirmed_corrections(cfg,output_path=tmp_path/'refused.json',filter=chosen,**selected)
    assert conn.execute('SELECT 1 n').fetchone()['n']==1


def test_archived029_managed_projection_keeps_originals(legacy,monkeypatch):
    conn,cfg,ids=legacy
    profile=providers.EmbeddingProfile(provider='ollama',model='synthetic',revision='a'*64,url='http://127.0.0.1:1',dimensions=2)
    cfg=replace(cfg,embedding_profiles={'two':profile})
    monkeypatch.setattr(providers,'verify_identity',lambda p:p.identity)
    monkeypatch.setattr(providers,'embed_profile',lambda texts,p:[[1.0,0.0] for _ in texts])
    indexes.create(conn,cfg,'legacy-two','two')
    indexes.build(conn,cfg,'legacy-two',allow_corpus=True)
    indexes.activate(conn,cfg,'legacy-two')
    bound=indexes.query_vector(indexes.active(conn,cfg),cfg,'quasar')
    hits=indexes.candidates(conn,bound,'quasar',domain='general',scopes=['/projects/alpha'])
    assert {str(h['document_id']) for h in hits}=={ids['start'],ids['end'],ids['fact'],ids['alias']}
    assert conn.failures==[]
