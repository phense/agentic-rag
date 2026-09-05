import pytest
from agentic_rag import store,evidence
from agentic_rag.domains import seed_defaults

@pytest.fixture(autouse=True)
def setup(conn,monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)

def source(identity='event1',role='user',quote='Server uses TLS.'):
    return {'source_id':identity,'namespace':'session:test','role':role,'quote':quote,'complete':True,'timestamp':'2026-01-01T00:00:00Z'}

def claim(conn,cfg,src=None,kind='stated'):
    return store.save_claim(conn,cfg,title='TLS',body='Server uses TLS.',domain='general',dtype='memory',project='/synthetic/a',claim_kind=kind,evidence=[src or source()])

def test_sources_count_events_not_spans_and_survive_withdrawal(conn,cfg):
    one=claim(conn,cfg)
    assert claim(conn,cfg).doc_id==one.doc_id
    claim(conn,cfg,source(quote='TLS.'))
    assert evidence.summary(conn,one.doc_id)['independent_source_count']==1
    claim(conn,cfg,source('event2'))
    assert evidence.summary(conn,one.doc_id)['independent_source_count']==2
    key=evidence.sources(conn,one.doc_id)[0]['source_key']
    store.set_source_state(conn,key,state='refuted',reason='source corrected')
    assert evidence.summary(conn,one.doc_id)['independent_source_count']==1
    assert conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']
    remaining=[s for s in evidence.sources(conn,one.doc_id) if s['state']=='active'][0]
    store.set_source_state(conn,remaining['source_key'],state='removed',reason='withdrawn')
    assert not conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']
    assert len(evidence.sources(conn,one.doc_id))==3


def test_inference_review_preserves_kind_and_requires_active_evidence(conn,cfg):
    one=claim(conn,cfg,source(role='assistant'),kind='inference')
    assert evidence.summary(conn,one.doc_id)['independent_source_count']==0
    assert not conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']
    store.review_claim(conn,one.doc_id,state='confirmed',reason='operator checked derivation')
    assert conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']
    assert evidence.summary(conn,one.doc_id)['kind']=='inference'
    with pytest.raises(ValueError,match='immutable'):
        store.save_document(conn,cfg,doc_id=one.doc_id,title='other',body='other',domain='general',dtype='memory')


def test_legacy_is_explicitly_incomplete(conn,cfg):
    doc=store.save_document(conn,cfg,title='old',body='old',domain='general',dtype='memory',mark_verified=True)
    assert evidence.summary(conn,doc.doc_id)['provenance_status']=='incomplete'


def test_grounding_distinguishes_kinds_and_rejects_fabrication():
    from agentic_rag.mining import ground_claim_items
    def run(body,role='user',kind='stated',quote=None,complete=True):
        ev={'source_id':'e1','role':role,'timestamp':None,'text':f'[{role}] '+body,'complete':complete,'offset':0}
        data={'memories':[{'title':'claim','body':body,'domain':'general','edges':[],
                          'claim_kind':kind,'evidence':[{'source_id':'e1','quote':quote or body}]}]}
        return ground_claim_items(data,[ev],'session1')['memories'][0]
    assert run('Server uses TLS.')['claim_kind']=='stated'
    assert run('We should enable TLS.','assistant')['claim_kind']=='proposal'
    assert run('If TLS were disabled, traffic might leak.')['claim_kind']=='hypothetical'
    assert run('Server uses TLS.',quote='fabricated')['evidence']==[]
    assert run('Server uses TLS.',complete=False)['claim_kind']=='inference'


def test_reader_interfaces_source_loss_and_history(conn,cfg,hook_env,monkeypatch,capsys):
    import json
    import psycopg
    from agentic_rag import db,search,mcp_server,cli
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    one=claim(conn,cfg)
    proposal=claim(conn,cfg,source('assistant','assistant'),kind='proposal')
    with db.connect(cfg,role='reader') as reader:
        hits,_=search.search(reader,cfg,'TLS',project='/synthetic/a')
        assert [h.document_id for h in hits]==[one.doc_id]
        assert hits[0].evidence['kind']=='stated' and hits[0].evidence['review_state']=='unreviewed'
        with pytest.raises(psycopg.errors.InsufficientPrivilege):reader.execute("UPDATE knowledge_sources SET state='removed'")
        reader.rollback()
    key=store.get_document(conn,one.doc_id)['claim_sources'][0]['source_key']
    assert cli.main(['evidence','source-state',key,'--state','refuted','--reason','correction'])==0
    capsys.readouterr()
    assert mcp_server.memory_search('TLS',project='/synthetic/a')['results']==[]
    assert len(mcp_server.memory_search('TLS',project='/synthetic/a',history=True)['results'])==2
    assert 'memory_source_state' not in mcp_server.tool_names(True)
    assert 'memory_review_claim' not in mcp_server.tool_names(True)
    with pytest.raises(ValueError,match='active source'):store.review_claim(conn,one.doc_id,state='confirmed',reason='attempt')


def test_evidence_is_redacted_and_batch_replay_is_atomic(conn,cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining
    from agentic_rag.mining_window import read_window
    raw='Server secret sk-ant-api03-'+'x'*40
    p=tmp_path/'source.jsonl';p.write_text(json.dumps({'uuid':'e','message':{'role':'user','content':raw}})+'\n')
    ev=read_window(p).events[0];body=ev['text'].removeprefix('[user] ')
    calls=[]
    def model(*a,**kw):
        calls.append(1);assert raw not in a[0]
        return {'memories':[{'title':'secret','body':body,'domain':'general','claim_kind':'stated','edges':[],
            'evidence':[{'source_id':ev['source_id'],'quote':body}]}]}
    monkeypatch.setattr(mining,'run_structured',model)
    original=store.save_claim
    def fail(*a,**kw):original(*a,**kw);raise RuntimeError('after evidence write')
    monkeypatch.setattr(store,'save_claim',fail)
    args=dict(session_id='s',transcript_path=str(p),last_uuid=None,project='/synthetic/a')
    with pytest.raises(RuntimeError):mining.mine_session(conn,cfg,**args)
    assert conn.execute('SELECT count(*) n FROM claim_records').fetchone()['n']==0
    assert conn.execute('SELECT count(*) n FROM knowledge_sources').fetchone()['n']==0
    monkeypatch.setattr(store,'save_claim',original)
    mining.mine_session(conn,cfg,**args)
    mining.mine_session(conn,cfg,**args)
    assert calls==[1]
    doc=conn.execute('SELECT document_id FROM claim_records').fetchone()['document_id']
    assert evidence.summary(conn,doc)['independent_source_count']==1
    assert raw not in json.dumps(evidence.sources(conn,doc),default=str)


def test_temporal_source_refutation_does_not_revive_old_value(conn,cfg):
    from tests.test_validity import put
    old=put(conn,cfg,'7000');new=put(conn,cfg,'8000','2026-02-01T00:00:00Z',relation='replacement')
    key=evidence.sources(conn,new.doc_id)[0]['source_key']
    store.set_source_state(conn,key,state='refuted',reason='source invalid')
    assert not conn.execute('SELECT assertion_eligible(%s)',(new.doc_id,)).fetchone()['assertion_eligible']
    assert not conn.execute('SELECT assertion_eligible(%s)',(old.doc_id,)).fetchone()['assertion_eligible']


def test_new_unreviewed_source_cannot_inherit_inference_confirmation(conn,cfg):
    one=claim(conn,cfg,source('s1','user'),kind='inference')
    store.review_claim(conn,one.doc_id,state='confirmed',reason='checked first source')
    claim(conn,cfg,source('s2','user','unrelated text'),kind='inference')
    first=next(s for s in evidence.sources(conn,one.doc_id) if s['source_id']=='s1')
    store.set_source_state(conn,first['source_key'],state='refuted',reason='invalid')
    assert not conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']


def test_unquoted_signal_is_not_promoted():
    from agentic_rag.mining import ground_claim_items
    ev={'source_id':'e','text':'[user] Server uses TLS.','role':'user','complete':True,'timestamp':None}
    raw={'signals':[{'title':'TLS','body':'Server uses TLS.','signal':'UNSUPPORTED_ERROR','claim_kind':'stated',
        'evidence':[{'source_id':'e','quote':'Server uses TLS.'}]}]}
    assert ground_claim_items(raw,[ev],'s')['signals'][0]['claim_kind']=='inference'


def test_invalid_temporal_source_time_remains_reviewable(conn,cfg):
    from agentic_rag.mining import ground_assertions
    ev={'source_id':'e','role':'user','timestamp':'not-a-time','text':'[user] server port is now 9000','complete':True,'offset':0}
    item={'entity':'server','attribute':'port','value':'9000','domain':'general','source_id':'e','quote':'server port is now 9000','event_at':'not-a-time','expires_at':None,'relation':'replacement'}
    grounded=ground_assertions([item],[ev])[0]
    assert grounded['evidence']['event_at'] is None
    # Also protect already accepted pre-upgrade payloads with raw invalid source time.
    grounded['evidence']['event_at']='not-a-time'
    result=store.save_assertion(conn,cfg,**grounded,project='/synthetic/a',actor='mining')
    assert result.disposition=='review'


def test_source_state_failure_rolls_back_trust_and_audit(conn,cfg,monkeypatch):
    one=claim(conn,cfg);key=evidence.sources(conn,one.doc_id)[0]['source_key']
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    def failure(*a,**kw):raise RuntimeError('audit failure')
    original=evidence._audit;monkeypatch.setattr(evidence,'_audit',failure)
    with pytest.raises(RuntimeError):store.set_source_state(conn,key,state='removed',reason='withdraw')
    assert evidence.sources(conn,one.doc_id)[0]['state']=='active'
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before
    monkeypatch.setattr(evidence,'_audit',original)
    store.set_source_state(conn,key,state='removed',reason='withdraw')
    assert not conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']


def test_attach_waits_for_withdrawal_without_reactivating(conn,cfg):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from agentic_rag import db
    one=claim(conn,cfg);key=evidence.sources(conn,one.doc_id)[0]['source_key'];conn.commit()
    ready=Event()
    def attach():
        with db.connect(cfg,role='writer') as other:
            ready.set();claim(other,cfg)
    with db.connect(cfg,role='writer') as writer:
        store.set_source_state(writer,key,state='refuted',reason='withdraw',commit=False)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attach);assert ready.wait(5)
            writer.commit();future.result(timeout=5)
    assert evidence.sources(conn,one.doc_id)[0]['state']=='refuted'
    assert not conn.execute('SELECT claim_eligible(%s)',(one.doc_id,)).fetchone()['claim_eligible']


def test_incomplete_span_and_recall_labels(conn,cfg):
    from agentic_rag.hooks.prompt_recall import _render
    from datetime import datetime,timezone
    one=claim(conn,cfg,{**source(),'complete':False},kind='inference')
    detail=evidence.summary(conn,one.doc_id)
    assert detail['provenance_status']=='incomplete'
    text=_render([{'slug':one.slug,'title':'TLS','verified_at':None,'created_at':datetime.now(timezone.utc),'claim_evidence':detail}],[],30)
    assert 'inference; unreviewed; provenance incomplete' in text


def test_mining_source_replay_to_reader_and_withdrawal(conn,cfg,tmp_path,monkeypatch):
    import json
    from agentic_rag import db,mining,search
    from agentic_rag.mining_window import read_window
    from agentic_rag.hooks.session_start import build_context
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    def ingest(session):
        p=tmp_path/f'{session}.jsonl';p.write_text(json.dumps({'uuid':session,'message':{'role':'user','content':'Server uses TLS.'}})+'\n')
        ev=read_window(p).events[0]
        monkeypatch.setattr(mining,'run_structured',lambda *a,**kw:{'memories':[{'title':'TLS','body':'Server uses TLS.','domain':'general','edges':[], 'claim_kind':'stated','evidence':[{'source_id':ev['source_id'],'quote':'Server uses TLS.'}]}]})
        args=dict(session_id=session,transcript_path=str(p),last_uuid=None,project='/synthetic/a')
        mining.mine_session(conn,cfg,**args);mining.mine_session(conn,cfg,**args)
    ingest('first');ingest('second')
    assert conn.execute('SELECT count(*) n FROM claim_records').fetchone()['n']==1
    doc_id=str(conn.execute('SELECT document_id FROM claim_records').fetchone()['document_id'])
    assert evidence.summary(conn,doc_id)['independent_source_count']==2
    with db.connect(cfg,role='reader') as reader:
        hits,_=search.search(reader,cfg,'TLS',project='/synthetic/a')
        assert len(hits)==1 and hits[0].evidence['independent_source_count']==2
        assert 'stated; unreviewed; provenance complete; user sources 2' in build_context(reader,cfg,'/synthetic/a')
    links=evidence.sources(conn,doc_id)
    for n,link in enumerate(links):
        store.set_source_state(conn,link['source_key'],state='refuted',reason='source correction')
        assert len(search.search(conn,cfg,'TLS',project='/synthetic/a')[0])==(1 if n==0 else 0)
    assert len(search.search(conn,cfg,'TLS',project='/synthetic/a',history=True)[0])==1
    assert len(store.get_document(conn,doc_id)['claim_sources'])==2


def test_evidence_filter_precedes_limit_and_each_graph_hop(conn,cfg,monkeypatch):
    from agentic_rag import search,graph
    monkeypatch.setattr(search,'try_embed_texts',lambda *a:None)
    blocked=[]
    for i in range(55):
        blocked.append(store.save_claim(conn,cfg,title='TLS',body=f'TLS unsupported {i}',domain='general',dtype='memory',project='/synthetic/a',claim_kind='inference',evidence=[]))
    good=claim(conn,cfg)
    assert [h.document_id for h in search.search(conn,cfg,'TLS',project='/synthetic/a',k=1)[0]]==[good.doc_id]
    a=store.save_document(conn,cfg,title='A',body='A',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',blocked[0].slug)])
    b=store.save_document(conn,cfg,title='B',body='B',domain='general',dtype='memory',project='/synthetic/a',edges=[store.EdgeSpec('references',blocked[0].slug)])
    assert graph.path(conn,a.doc_id,b.doc_id,project='/synthetic/a')==[]
    assert len(graph.path(conn,a.doc_id,b.doc_id,history=True))==3
