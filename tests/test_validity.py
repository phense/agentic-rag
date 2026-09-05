from datetime import datetime, timezone

import pytest

from agentic_rag import store, validity
from agentic_rag.domains import seed_defaults


def put(conn, cfg, value, when='2026-01-01T00:00:00Z', **kw):
    return store.save_assertion(conn, cfg, entity='server', attribute='port', value=value,
        event_at=when, evidence={'source_id': 'source-' + value + when, 'role': 'user',
        'quote': f'server port {value} at {when}', 'event_at': when},
        project=kw.pop('project', '/synthetic/a'), domain='general', **kw)


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def eligible(conn, at=None, history=False):
    return [r['value'] for r in conn.execute(
        'SELECT value FROM fact_assertions a WHERE assertion_eligible(a.document_id,%s,%s) ORDER BY value',
        (validity.parse_time(at) if at else datetime.now(timezone.utc), history)).fetchall()]


def test_replacement_is_event_ordered_and_expiry_does_not_revive(conn, cfg):
    new = put(conn, cfg, '8000', '2026-02-01T00:00:00Z', relation='replacement', expires_at='2026-03-01T00:00:00Z')
    old = put(conn, cfg, '7000')
    assert eligible(conn, '2026-01-15T00:00:00Z') == ['7000']
    assert eligible(conn, '2026-02-15T00:00:00Z') == ['8000']
    assert eligible(conn, '2026-04-01T00:00:00Z') == []
    assert eligible(conn, history=True) == ['7000', '8000']
    assert conn.execute("SELECT 1 FROM edges WHERE src_id=%s AND dst_id=%s AND predicate='supersedes'", (new.doc_id, old.doc_id)).fetchone()


def test_scope_extensions_conflicts_and_duplicate(conn, cfg):
    one = put(conn, cfg, '7000')
    assert put(conn, cfg, '7000').doc_id == one.doc_id
    put(conn, cfg, '8000', project='/synthetic/b', relation='replacement')
    put(conn, cfg, '9000', relation='replacement')
    put(conn, cfg, 'extra', '2026-02-01T00:00:00Z', relation='extension')
    assert eligible(conn) == ['7000', '8000', 'extra']
    row = conn.execute("SELECT disposition FROM fact_assertions WHERE value='9000'").fetchone()
    assert row['disposition'] == 'review'
    assert len(eligible(conn, history=True)) == 4


def test_untrusted_or_undated_evidence_cannot_replace(conn, cfg):
    put(conn, cfg, '7000')
    result = store.save_assertion(conn, cfg, entity='server', attribute='port', value='9000',
        event_at=None, evidence={'source_id':'s','role':'assistant','quote':'maybe 9000'},
        project='/synthetic/a', domain='general', relation='replacement')
    assert result.disposition == 'review'
    assert eligible(conn) == ['7000']


def test_immutable_and_transaction_rollback(conn, cfg):
    result = put(conn, cfg, '7000')
    with pytest.raises(ValueError, match='immutable'):
        store.save_document(conn, cfg, title='changed', body='changed', domain='general', dtype='memory', doc_id=result.doc_id)
    with pytest.raises(ValueError, match='immutable'):
        store.set_project_scope(conn, result.doc_id, project='/synthetic/b')
    put(conn, cfg, '8000', '2026-02-01T00:00:00Z', relation='replacement', commit=False)
    conn.rollback()
    assert eligible(conn) == ['7000']
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n'] == 1


def test_timezone_required():
    with pytest.raises(ValueError, match='timezone'):
        validity.parse_time('2026-01-01T00:00:00')


def test_mining_evidence_matches_consumed_record(tmp_path):
    import json
    from agentic_rag.mining_window import read_window
    from agentic_rag.mining import ground_assertions
    p=tmp_path/'session.jsonl'
    p.write_text(json.dumps({'uuid':'e1','timestamp':'2026-01-01T00:00:00Z','message':{'role':'user','content':'server port is now 8000'}})+'\n')
    window=read_window(p, per_block=1000)
    ev=window.events[0]
    item={'entity':'server','attribute':'port','value':'8000','domain':'general','relation':'replacement',
          'source_id':ev['source_id'],'quote':'server port is now 8000','event_at':ev['timestamp'],'expires_at':None}
    good=ground_assertions([item],window.events)[0]
    assert good['evidence']['role']=='user'
    assert good['event_at']=='2026-01-01T00:00:00Z'
    assert ground_assertions([{**item,'quote':'fabricated 9000'}],window.events)==[]
    fragment=read_window(p,per_block=10)
    assert ground_assertions([item],fragment.events)==[]


def test_reader_cli_mcp_and_graph_share_validity(conn,cfg,hook_env,capsys,monkeypatch):
    import json
    import psycopg
    from agentic_rag import cli,db,graph,mcp_server,search
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    old=put(conn,cfg,'7000')
    new=put(conn,cfg,'8000','2026-02-01T00:00:00Z',relation='replacement')
    with db.connect(cfg,role='reader') as reader:
        hits,_=search.search(reader,cfg,'server',project='/synthetic/a')
        assert [h.document_id for h in hits]==[new.doc_id]
        assert graph.path(reader,old.doc_id,new.doc_id,project='/synthetic/a')==[]
        assert len(graph.path(reader,old.doc_id,new.doc_id,history=True))==2
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute('UPDATE fact_assertions SET value=%s',('hacked',))
        reader.rollback()
    assert len(mcp_server.memory_search('server',project='/synthetic/a',history=True)['results'])==2
    assert cli.main(['search','server','--project','/synthetic/a','--as-of','2026-01-15T00:00:00Z','--json'])==0
    assert json.loads(capsys.readouterr().out)['results'][0]['document_id']==old.doc_id
    assert cli.main(['assert','--entity','other','--attribute','setting','--value','enabled','--domain','general',
        '--source-id','manual-1','--quote','enabled','--project','/synthetic/a','--event-at','2026-01-01T00:00:00Z'])==0
    assert json.loads(capsys.readouterr().out)['disposition']=='accepted'
    assert 'memory_assert' not in mcp_server.tool_names(True)
    assert 'memory_assert' in mcp_server.tool_names(False)


def test_curation_keeps_atomic_facts_and_reactivation_epoch(conn,cfg,monkeypatch):
    from agentic_rag import curation
    one=put(conn,cfg,'7000')
    two=put(conn,cfg,'7000','2026-02-01T00:00:00Z',relation='replacement')
    assert curation._merge_exact_duplicates(conn,10)==0
    legacy=store.save_document(conn,cfg,title='legacy',body='old',domain='general',dtype='memory',project='/synthetic/a')
    store.save_document(conn,cfg,title='contra',body='other',domain='general',dtype='lesson',project='/synthetic/a',actor='mining',edges=[store.EdgeSpec('contradicts',legacy.slug,evidence='other')])
    assert len(curation._refute_candidates(conn,10))==1
    store.save_document(conn,cfg,title='legacy',body='old',domain='general',dtype='memory',doc_id=legacy.doc_id,status='archived')
    store.save_document(conn,cfg,title='legacy',body='confirmed',domain='general',dtype='memory',doc_id=legacy.doc_id,status='active')
    assert curation._refute_candidates(conn,10)==[]
    store.save_document(conn,cfg,title='new contra',body='new evidence',domain='general',dtype='lesson',project='/synthetic/a',actor='mining',edges=[store.EdgeSpec('contradicts',legacy.slug,evidence='new evidence')])
    assert len(curation._refute_candidates(conn,10))==1


def test_mined_assertion_rollback_and_accepted_replay(conn,cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining
    from agentic_rag.mining_window import read_window
    p=tmp_path/'source.jsonl'
    p.write_text(json.dumps({'uuid':'u1','timestamp':'2026-01-01T00:00:00Z','message':{'role':'user','content':'server port now 7000'}})+'\n')
    event=read_window(p).events[0]
    calls=[]
    def model(*a,**kw):
        calls.append(1)
        return {'assertions':[{'entity':'server','attribute':'port','value':'7000','domain':'general',
            'source_id':event['source_id'],'quote':'server port now 7000','event_at':event['timestamp'],
            'expires_at':None,'relation':'replacement'}]}
    monkeypatch.setattr(mining,'run_structured',model)
    original=store.save_assertion
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('failure after assertion effects')
    monkeypatch.setattr(store,'save_assertion',fail)
    args=dict(session_id='s1',transcript_path=str(p),last_uuid=None,project='/synthetic/a')
    with pytest.raises(RuntimeError): mining.mine_session(conn,cfg,**args)
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n']==0
    monkeypatch.setattr(store,'save_assertion',original)
    assert mining.mine_session(conn,cfg,**args).saved==1
    assert mining.mine_session(conn,cfg,**args).saved==1
    assert len(calls)==1
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n']==1


def test_question_is_not_replacement_authority(conn,cfg):
    from agentic_rag.mining import ground_assertions
    put(conn,cfg,'7000')
    event={'source_id':'e-question','role':'user','timestamp':'2026-02-01T00:00:00Z',
           'text':'should we use server port 9000?','offset':0}
    items=ground_assertions([{'entity':'server','attribute':'port','value':'9000','domain':'general',
        'source_id':event['source_id'],'quote':event['text'],'event_at':event['timestamp'],
        'expires_at':None,'relation':'replacement'}],[event])
    result=store.save_assertion(conn,cfg,**items[0],project='/synthetic/a',actor='mining')
    assert result.disposition=='review'
    assert eligible(conn)==['7000']


def test_duplicate_retains_independent_source_evidence(conn,cfg):
    one=put(conn,cfg,'7000')
    args=dict(entity='server',attribute='port',value='7000',domain='general',
        event_at='2026-01-01T00:00:00Z',project='/synthetic/a',
        evidence={'source_id':'independent-source','role':'user','quote':'confirmed 7000'})
    assert store.save_assertion(conn,cfg,**args).doc_id==one.doc_id
    store.save_assertion(conn,cfg,**args)
    evidence=store.get_document(conn,one.doc_id)['assertion']['sources']
    assert len(evidence)==2


def test_concurrent_reactivation_invalidates_selected_contradiction(conn,cfg,monkeypatch):
    from agentic_rag import curation,db
    legacy=store.save_document(conn,cfg,title='legacy',body='old',domain='general',dtype='memory',project='/synthetic/a')
    store.save_document(conn,cfg,title='contra',body='other',domain='general',dtype='lesson',project='/synthetic/a',actor='mining',edges=[store.EdgeSpec('contradicts',legacy.slug,evidence='other')])
    def model(*a,**kw):
        with db.connect(cfg,role='writer') as other:
            for status in ('archived','active'):
                store.save_document(other,cfg,title='legacy',body='confirmed',domain='general',dtype='memory',doc_id=legacy.doc_id,status=status)
        return {'refute':True,'reason':'old evidence','quote':'other'}
    monkeypatch.setattr(curation,'run_structured',model)
    assert curation._review_refutes(conn,cfg,10,None)==(0,0)
    assert store.get_document(conn,legacy.doc_id)['status']=='active'
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='refute_review'").fetchone()['n']==0


def test_expired_candidates_do_not_exhaust_limit_or_graph_hops(conn,cfg,monkeypatch):
    from agentic_rag import search,graph
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    for i in range(55):
        store.save_assertion(conn,cfg,entity='server',attribute=f'expired{i}',value='stale',domain='general',
            event_at='2026-01-01T00:00:00Z',expires_at='2026-02-01T00:00:00Z',project='/synthetic/a',
            evidence={'source_id':str(i),'role':'user','quote':'stale'})
    live=put(conn,cfg,'8000')
    assert [h.document_id for h in search.search(conn,cfg,'server',k=1,project='/synthetic/a')[0]]==[live.doc_id]
    stale=conn.execute("SELECT d.id,d.slug FROM fact_assertions a JOIN documents d ON d.id=a.document_id WHERE a.attribute='expired0'").fetchone()
    a=store.save_document(conn,cfg,title='A',body='A',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',stale['slug'])])
    b=store.save_document(conn,cfg,title='B',body='B',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',stale['slug'])])
    assert graph.path(conn,a.doc_id,b.doc_id,project='/synthetic/a')==[]
    assert len(graph.path(conn,a.doc_id,b.doc_id))==3  # deliberate unselected history


def test_source_to_reader_and_startup_preserves_pin_and_other_attribute(conn,cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining,search,pins,db
    from agentic_rag.hooks.session_start import build_context
    from agentic_rag.mining_window import read_window
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    pin=pins.add_pin(conn,body='Exact standing rule',scope='/synthetic/a')
    results=[]
    for i,(value,when,relation) in enumerate([('8000','2026-02-01T00:00:00Z','replacement'),('7000','2026-01-01T00:00:00Z','assertion')]):
        text=f'server port is now {value}'
        p=tmp_path/f'{i}.jsonl';p.write_text(json.dumps({'uuid':str(i),'timestamp':when,'message':{'role':'user','content':text}})+'\n')
        ev=read_window(p).events[0]
        monkeypatch.setattr(mining,'run_structured',lambda *a,**kw:{'assertions':[{'entity':'server','attribute':'port','value':value,'domain':'general','source_id':ev['source_id'],'quote':text,'event_at':when,'expires_at':None,'relation':relation}]})
        results.append(mining.mine_session(conn,cfg,session_id=f'integration{i}',transcript_path=str(p),last_uuid=None,project='/synthetic/a'))
    other=store.save_assertion(conn,cfg,entity='server',attribute='tls',value='enabled',domain='general',event_at='2026-01-01T00:00:00Z',project='/synthetic/a',evidence={'source_id':'tls','role':'user','quote':'enabled'})
    with db.connect(cfg,role='reader') as reader:
        current=search.search(reader,cfg,'server port',project='/synthetic/a')[0]
        historical=search.search(reader,cfg,'server port',project='/synthetic/a',as_of='2026-01-15T00:00:00Z')[0]
        assert [store.get_document(reader,h.document_id)['body'] for h in current]==['8000']
        assert [store.get_document(reader,h.document_id)['body'] for h in historical]==['7000']
        context=build_context(reader,cfg,'/synthetic/a')
        assert current[0].slug in context and historical[0].slug not in context
        assert other.slug in context and 'Exact standing rule' in context
        assert store.get_document(reader,current[0].document_id)['assertion']['sources'][0]['evidence']['source_id']


def test_replacement_failure_preserves_all_effect_counts(conn,cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining
    from agentic_rag.mining_window import read_window
    put(conn,cfg,'7000')
    def counts():
        return {t:conn.execute(f'SELECT count(*) n FROM {t}').fetchone()['n'] for t in ('documents','fact_assertions','assertion_sources','edges','audit_log')}
    p=tmp_path/'replacement.jsonl';p.write_text(json.dumps({'uuid':'new','timestamp':'2026-02-01T00:00:00Z','message':{'role':'user','content':'server port is now 8000'}})+'\n')
    ev=read_window(p).events[0];calls=[]
    def model(*a,**kw):
        calls.append(1)
        return {'assertions':[{'entity':'server','attribute':'port','value':'8000','domain':'general','source_id':ev['source_id'],'quote':'server port is now 8000','event_at':ev['timestamp'],'expires_at':None,'relation':'replacement'}]}
    monkeypatch.setattr(mining,'run_structured',model)
    before=counts();original=store.save_assertion
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('crash after replacement')
    monkeypatch.setattr(store,'save_assertion',fail)
    args=dict(session_id='replace',transcript_path=str(p),last_uuid=None,project='/synthetic/a')
    with pytest.raises(RuntimeError):mining.mine_session(conn,cfg,**args)
    after=counts();assert after=={**before,'audit_log':before['audit_log']+1}  # durable acceptance only
    assert eligible(conn)==['7000']
    assert conn.execute('SELECT result FROM mining_batches').fetchone()['result'] is None
    monkeypatch.setattr(store,'save_assertion',original)
    mining.mine_session(conn,cfg,**args);applied=counts()
    assert eligible(conn)==['8000']
    mining.mine_session(conn,cfg,**args)
    assert counts()==applied and calls==[1]


def test_concurrent_same_key_writers_do_not_silently_replace(conn,cfg):
    from concurrent.futures import ThreadPoolExecutor
    from agentic_rag import db
    def write(value):
        with db.connect(cfg,role='writer') as other:
            return put(other,cfg,value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(write,['7000','8000']))
    assert sorted(r.disposition for r in outcomes)==['accepted','review']
    assert len(eligible(conn))==1


def test_clipped_question_prefix_is_not_a_declaration(conn,cfg,tmp_path):
    import json
    from agentic_rag.mining_window import read_window
    from agentic_rag.mining import ground_assertions
    p=tmp_path/'question.jsonl';p.write_text(json.dumps({'uuid':'q','timestamp':'2026-02-01T00:00:00Z','message':{'role':'user','content':'server port is now 9000?'}})+'\n')
    window=read_window(p,per_block=len('[user] server port is now 9000'))
    ev=window.events[0]
    item={'entity':'server','attribute':'port','value':'9000','domain':'general',
          'source_id':ev['source_id'],'quote':'server port is now 9000','event_at':ev['timestamp'],
          'expires_at':None,'relation':'replacement'}
    grounded=ground_assertions([item],window.events)[0]
    assert grounded['evidence']['grounding']=='review'
