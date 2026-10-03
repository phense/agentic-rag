"""Themed views must preserve original evidence and never resurrect withdrawn facts."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from agentic_rag import store, domains, db, thematic, evidence, profiles, context, mcp_server, cli, jobs, worker

PROJECT = '/synthetic/thematic/a'


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    domains.seed_defaults(conn)
    conn.execute('DELETE FROM thematic_summaries')
    conn.execute('DELETE FROM project_profiles')
    conn.commit()
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def put(conn, cfg, text='The provider outage lasted ten minutes.', **kwargs):
    return store.save_document(conn, cfg, title=kwargs.pop('title','Provider incident'), body=text,
        domain=kwargs.pop('domain','general'), dtype='lesson', project=kwargs.pop('project',PROJECT), **kwargs)


def refresh(conn,cfg,topic='provider-outages',**kwargs):
    return store.refresh_summaries(conn,cfg,topic,project=kwargs.pop('project',PROJECT),**kwargs)


def read(conn,cfg,topic='provider-outages',**kwargs):
    return thematic.read(conn,cfg,topic,project=kwargs.pop('project',PROJECT),**kwargs)


def test_thematic_gateway_returns_versioned_original_excerpts(conn, cfg, monkeypatch):
    # Mutation caught: treating generated summaries as unreferenced canonical truth.
    domains.seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    doc = store.save_document(conn, cfg, title='Provider incident', body='The provider outage lasted ten minutes.',
                              domain='general', dtype='lesson', project=PROJECT)
    assert hasattr(store, 'refresh_summaries'), 'Audited thematic refresh gateway is required'
    result = store.refresh_summaries(conn, cfg, 'provider-outages', project=PROJECT)
    assert result['status'] == 'fresh'
    assert result['inference_status'] == 'extractive_theme_membership'
    assert len(result['entries']) == 1
    entry = result['entries'][0]
    assert entry['document_id'] == doc.doc_id
    assert entry['text'] == 'The provider outage lasted ten minutes.'
    assert entry['source_version'] and entry['versions']['document']
    assert entry['source_kind'] == 'legacy'
    assert entry['provenance_status'] == 'incomplete'
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='summary_refresh'").fetchone()['n'] == 1


def test_incremental_refresh_reuses_unchanged_and_withholds_edited_sources(conn,cfg):
    one=put(conn,cfg)
    two=put(conn,cfg,'Provider outage recovery took two minutes.')
    first=refresh(conn,cfg)
    assert first['usage']['rebuilt']==2 and first['usage']['reused']==0
    before=conn.execute('SELECT entries,generated_at FROM thematic_summaries').fetchone()
    retry=refresh(conn,cfg)
    assert retry['usage']['rebuilt']==0 and retry['usage']['reused']==2
    assert conn.execute('SELECT entries,generated_at FROM thematic_summaries').fetchone()==before
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='summary_refresh'").fetchone()['n']==1
    put(conn,cfg,'The provider outage lasted eleven minutes.',doc_id=one.doc_id)
    stale=read(conn,cfg)
    assert stale['status']=='stale' and stale['invalidated']==1
    assert [e['document_id'] for e in stale['entries']]==[two.doc_id]
    changed=refresh(conn,cfg)
    assert changed['usage']['rebuilt']==1 and changed['usage']['reused']==1
    assert {e['text'] for e in changed['entries']}=={
        'The provider outage lasted eleven minutes.','Provider outage recovery took two minutes.'}


@pytest.mark.parametrize('state',['removed','refuted'])
def test_source_withdrawal_invalidates_current_and_history(conn,cfg,state):
    doc=store.save_claim(conn,cfg,title='Provider report',body='The provider outage was confirmed.',
        domain='general',dtype='lesson',project=PROJECT,claim_kind='stated',evidence=[{
        'namespace':'synthetic','source_id':'operator','role':'user','quote':'The provider outage was confirmed.','complete':True}])
    assert refresh(conn,cfg)['entries']
    assert refresh(conn,cfg,history=True)['entries']
    key=evidence.sources(conn,doc.doc_id)[0]['source_key']
    store.set_source_state(conn,key,state=state,reason='synthetic correction')
    for history in (False,True):
        packet=read(conn,cfg,history=history)
        assert packet['status']=='stale' and not packet['entries']
        assert refresh(conn,cfg,history=history)['entries']==[]
    assert store.get_document(conn,doc.doc_id)['body']=='The provider outage was confirmed.'


def test_history_is_labelled_without_resurrecting_expired_or_refuted_facts(conn,cfg):
    now=datetime.now(timezone.utc)
    def assertion(value,when,**kw):
        return store.save_assertion(conn,cfg,entity='deployment',attribute='store',value=value,
            event_at=when,evidence={'source_id':value,'role':'user','quote':value},domain='general',project=PROJECT,**kw)
    old=assertion('Deployment uses PostgreSQL',(now-timedelta(days=2)).isoformat())
    assert refresh(conn,cfg,'deployment-architecture')['entries'][0]['document_id']==old.doc_id
    new=assertion('Deployment uses PostgreSQL and pgvector',(now-timedelta(days=1)).isoformat(),relation='replacement')
    assert not read(conn,cfg,'deployment-architecture')['entries']
    current=refresh(conn,cfg,'deployment-architecture')
    assert [e['document_id'] for e in current['entries']]==[new.doc_id]
    history=refresh(conn,cfg,'deployment-architecture',history=True)
    assert {e['document_id']:e['temporal_status'] for e in history['entries']}=={
        new.doc_id:'current',old.doc_id:'historical_superseded'}
    expired=store.save_assertion(conn,cfg,entity='expired deployment',attribute='port',value='Deployment port 7000',
        event_at=(now-timedelta(days=2)).isoformat(),expires_at=(now-timedelta(days=1)).isoformat(),
        evidence={'source_id':'expired','role':'user','quote':'Deployment port 7000'},domain='general',project=PROJECT)
    assert expired.doc_id not in {e['document_id'] for e in refresh(conn,cfg,'deployment-architecture',history=True)['entries']}
    key=evidence.sources(conn,old.doc_id)[0]['source_key']
    store.set_source_state(conn,key,state='removed',reason='withdrawn old architecture evidence')
    assert old.doc_id not in {e['document_id'] for e in read(conn,cfg,'deployment-architecture',history=True)['entries']}


def test_expiry_without_writes_invalidates_both_modes(conn,cfg):
    now=datetime.now(timezone.utc)
    store.save_assertion(conn,cfg,entity='provider',attribute='status',value='Provider outage',
        event_at=(now-timedelta(days=1)).isoformat(),expires_at=(now+timedelta(seconds=.8)).isoformat(),
        evidence={'source_id':'short','role':'user','quote':'Provider outage'},domain='general',project=PROJECT)
    refresh(conn,cfg); refresh(conn,cfg,history=True)
    conn.execute('SELECT pg_sleep(0.9)')
    assert not read(conn,cfg)['entries']
    assert not read(conn,cfg,history=True)['entries']


def test_future_and_unsupported_claims_never_enter_themes(conn,cfg):
    for kind in ('proposal','hypothetical','inference'):
        store.save_claim(conn,cfg,title=kind,body='Provider outage '+kind,domain='general',dtype='lesson',project=PROJECT,
            claim_kind=kind,evidence=[{'namespace':'synthetic','source_id':kind,'role':'assistant','quote':'Provider outage '+kind,'complete':True}])
    store.save_assertion(conn,cfg,entity='future provider',attribute='status',value='Provider outage tomorrow',
        event_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        evidence={'source_id':'future','role':'user','quote':'Provider outage tomorrow'},domain='general',project=PROJECT)
    assert not refresh(conn,cfg)['entries']
    assert not refresh(conn,cfg,history=True)['entries']


def test_confirmed_inference_is_still_labelled_inference(conn,cfg):
    doc=store.save_claim(conn,cfg,title='Inference',body='Provider outage probably involved OAuth.',domain='general',dtype='lesson',project=PROJECT,
        claim_kind='inference',evidence=[{'namespace':'synthetic','source_id':'assistant-inference','role':'assistant','quote':'Provider outage probably involved OAuth.','complete':True}])
    store.review_claim(conn,doc.doc_id,state='confirmed',reason='explicit synthetic operator review')
    packet=refresh(conn,cfg)
    assert packet['entries'][0]['source_kind']=='inference'
    assert packet['entries'][0]['review_state']=='confirmed'
    assert 'kind=inference' in packet['context']
    store.review_claim(conn,doc.doc_id,state='unreviewed',reason='review withdrawn')
    assert not read(conn,cfg)['entries']


def test_project_domain_global_unknown_and_access_change(conn,cfg):
    domains.add_domain(conn,'user')
    local=put(conn,cfg)
    global_doc=put(conn,cfg,'Provider outage global report.',project=None,scope='global')
    foreign=put(conn,cfg,'Provider outage foreign report.',project='/synthetic/thematic/b')
    user=put(conn,cfg,'Provider outage user-domain report.',domain='user')
    put(conn,cfg,'Provider outage unknown report.',project=None,scope='unknown')
    assert {e['document_id'] for e in refresh(conn,cfg)['entries']}=={local.doc_id,global_doc.doc_id,user.doc_id}
    assert {e['document_id'] for e in refresh(conn,cfg,domain='user')['entries']}=={user.doc_id}
    assert {e['document_id'] for e in refresh(conn,cfg,project=None)['entries']}=={global_doc.doc_id}
    store.set_project_scope(conn,local.doc_id,project='/synthetic/thematic/b')
    result=read(conn,cfg)
    assert local.doc_id not in {e['document_id'] for e in result['entries']}
    assert foreign.doc_id not in {e['document_id'] for e in result['entries']}


def test_foreign_candidates_cannot_crowd_out_local_sources(conn,cfg):
    local=put(conn,cfg)
    for n in range(30): put(conn,cfg,f'Provider outage outage outage foreign {n}.',project='/synthetic/thematic/b')
    assert [e['document_id'] for e in refresh(conn,cfg)['entries']]==[local.doc_id]


def test_limits_and_exact_clipped_citations(conn,cfg):
    for n in range(26): put(conn,cfg,f'Provider outage {n} '+('background '*70),title=f'Incident {n}')
    result=refresh(conn,cfg,context_chars=12000)
    assert result['usage']['candidates']==24
    assert any('24' in w for w in result['warnings'])
    narrow=read(conn,cfg,context_chars=1000)
    assert narrow['omitted']>0 and len(narrow['context'])<=1000
    for e in result['entries']:
        row=conn.execute('SELECT content FROM chunks WHERE id=%s',(e['chunk_id'],)).fetchone()
        assert row['content'][e['start']:e['end']]==e['text']
        assert len(e['text'])<=240 and e['clipped']
    assert 'clipped excerpt' in result['context']


@pytest.mark.parametrize('kwargs',[
    {'topic':''},{'topic':'x'*121},{'topic':'a\x00b'},{'project':'relative'},
    {'history':'true'},{'history':1},{'context_chars':True},{'context_chars':999},
    {'context_chars':12001},{'domain':''},{'domain':['user']},
])
def test_malformed_selectors_fail_before_any_write(conn,cfg,kwargs):
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    with pytest.raises(ValueError): refresh(conn,cfg,**kwargs)
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before


def test_atomic_failure_interruption_retry_preserves_originals(conn,cfg,monkeypatch):
    put(conn,cfg)
    refresh(conn,cfg)
    original=conn.execute('SELECT entries,generated_at FROM thematic_summaries').fetchone()
    original_documents=conn.execute('SELECT to_jsonb(d) data FROM documents d ORDER BY id').fetchall()
    put(conn,cfg,'Provider outage second report.')
    old_audit=thematic._audit
    def interrupt(*args): raise KeyboardInterrupt()
    monkeypatch.setattr(thematic,'_audit',interrupt)
    with pytest.raises(KeyboardInterrupt): refresh(conn,cfg)
    assert conn.execute('SELECT entries,generated_at FROM thematic_summaries').fetchone()==original
    assert read(conn,cfg)['status']=='stale'
    monkeypatch.setattr(thematic,'_audit',old_audit)
    assert refresh(conn,cfg)['status']=='fresh'
    assert conn.execute('SELECT to_jsonb(d) data FROM documents d WHERE id=%s',(original_documents[0]['data']['id'],)).fetchone()['data']==original_documents[0]['data']


def test_reader_privilege_and_mcp_contract(conn,cfg,hook_env):
    put(conn,cfg)
    refresh(conn,cfg)
    with db.connect(cfg,role='reader') as reader:
        assert read(reader,cfg)['entries']
        with pytest.raises(PermissionError): refresh(reader,cfg)
        assert read(reader,cfg)['entries']
    assert 'memory_summary' in mcp_server.tool_names(True)
    assert len(mcp_server.tool_names(False))-len(mcp_server.tool_names(True))==6
    wire=mcp_server.memory_summary('provider-outages',project=PROJECT)
    assert wire['entries'] and isinstance(wire['entries'][0]['versions'],dict)
    json.dumps(wire)


def test_absent_migration_and_sql_failure_keep_baseline(conn,cfg,monkeypatch):
    doc=put(conn,cfg)
    conn.execute('ALTER TABLE thematic_summaries RENAME TO thematic_summaries_hidden')
    try:
        packet=read(conn,cfg)
        assert packet['status']=='unavailable'
        assert store.get_document(conn,doc.doc_id)['body']=='The provider outage lasted ten minutes.'
        profiles.refresh(conn,cfg,PROJECT)
        assert profiles.read(conn,cfg,PROJECT)['status']=='fresh'
    finally:
        conn.execute('ALTER TABLE thematic_summaries_hidden RENAME TO thematic_summaries'); conn.commit()
    def error(*args):
        conn.execute('SELECT 1/0')
    monkeypatch.setattr(thematic,'_state',error)
    assert read(conn,cfg)['status']=='unavailable'
    assert conn.execute('SELECT 42 n').fetchone()['n']==42


def test_sql_limits_preserve_shorter_caller_timeout(conn,cfg):
    put(conn,cfg)
    conn.execute("SET LOCAL statement_timeout='750ms'; SET LOCAL lock_timeout='500ms'")
    read(conn,cfg)
    assert conn.execute("SHOW statement_timeout").fetchone()['statement_timeout']=='750ms'
    assert conn.execute("SHOW lock_timeout").fetchone()['lock_timeout']=='500ms'


def test_concurrent_writers_and_readers_serialize_cache(conn,cfg):
    put(conn,cfg)
    def run(n):
        with db.connect(cfg,role='writer' if n%2 else 'reader') as c:
            return refresh(c,cfg) if n%2 else read(c,cfg)
    with ThreadPoolExecutor(max_workers=4) as pool: packets=list(pool.map(run,range(8)))
    assert all(p['status'] in ('fresh','missing') for p in packets)
    assert conn.execute('SELECT count(*) n FROM thematic_summaries').fetchone()['n']==1
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='summary_refresh'").fetchone()['n']==1
    assert read(conn,cfg)['status']=='fresh'


def test_profile_jobs_refresh_themes_and_context_schedules_missing_cache(conn,cfg):
    put(conn,cfg)
    profiles.refresh(conn,cfg,PROJECT)
    assert read(conn,cfg)['status']=='fresh'
    conn.execute('DELETE FROM thematic_summaries'); conn.commit()
    packet=context.build(conn,cfg,project=PROJECT)
    assert packet['profile_status']=='stale'
    assert jobs.enqueue_profile(conn,cfg,PROJECT)
    job=conn.execute("SELECT * FROM mining_queue WHERE kind='profile_refresh'").fetchone()
    worker.process_job(conn,cfg,dict(job))
    assert read(conn,cfg)['status']=='fresh'
    assert context.build(conn,cfg,project=PROJECT)['profile_status']=='fresh'


def test_cli_refresh_reports_real_incremental_work_and_budget(conn,cfg,hook_env,capsys):
    put(conn,cfg)
    assert cli.main(['summary','provider-outages','--project',PROJECT,'--refresh','--context-chars','1000'])==0
    packet=json.loads(capsys.readouterr().out)
    assert packet['usage']['rebuilt']==1 and packet['context_budget']==1000
    assert cli.main(['summary','provider-outages','--project',PROJECT,'--refresh'])==0
    assert json.loads(capsys.readouterr().out)['usage']['reused']==1


def test_uncommitted_refresh_on_fresh_connection_rolls_back_with_audit(conn,cfg):
    # Mutation caught: a nested transaction helper commits an idle caller's writes.
    put(conn,cfg)
    with db.connect(cfg,role='writer') as writer:
        store.refresh_summaries(writer,cfg,'provider-outages',project=PROJECT,commit=False)
        writer.rollback()
    assert conn.execute('SELECT count(*) n FROM thematic_summaries').fetchone()['n']==0
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='summary_refresh'").fetchone()['n']==0


def test_context_discloses_theme_selection_omissions(conn,cfg):
    for n in range(4): put(conn,cfg,f'Provider outage case {n}.')
    profiles.refresh(conn,cfg,PROJECT)
    packet=context.build(conn,cfg,project=PROJECT)
    assert any('provider-outages' in w and 'two' in w for w in packet['warnings'])


def test_source_beyond_reference_cap_still_invalidates(conn,cfg):
    text='Provider outage had complete user support.'
    doc=store.save_claim(conn,cfg,title='Many sources',body=text,domain='general',dtype='lesson',project=PROJECT,
        claim_kind='stated',evidence=[{'namespace':'many','source_id':'0','role':'user','quote':text,'complete':True}])
    for n in range(1,10):
        evidence.attach(conn,doc.doc_id,[{'namespace':'many','source_id':str(n),'role':'user','quote':text,'complete':True}],actor='test')
    conn.commit()
    first=refresh(conn,cfg)
    assert first['entries'][0]['sources_omitted'] and len(first['entries'][0]['sources'])==8
    selected={s['source_key'] for s in first['entries'][0]['sources']}
    omitted=next(s for s in evidence.sources(conn,doc.doc_id) if s['source_key'] not in selected)
    store.set_source_state(conn,omitted['source_key'],state='removed',reason='withdraw omitted source')
    assert read(conn,cfg)['entries']==[]
    assert read(conn,cfg)['status']=='stale'
    assert refresh(conn,cfg)['entries']


def test_concurrent_source_withdrawal_during_hydration_is_withheld(conn,cfg,monkeypatch):
    text='Provider outage concurrent report.'
    doc=store.save_claim(conn,cfg,title='Concurrent source',body=text,domain='general',dtype='lesson',project=PROJECT,
        claim_kind='stated',evidence=[{'namespace':'race','source_id':'one','role':'user','quote':text,'complete':True}])
    key=evidence.sources(conn,doc.doc_id)[0]['source_key']
    original=thematic._build_entry
    def hydrate(c,candidate,topic):
        with db.connect(cfg,role='writer') as other:
            store.set_source_state(other,key,state='removed',reason='withdraw during hydration')
        return original(c,candidate,topic)
    monkeypatch.setattr(thematic,'_build_entry',hydrate)
    packet=refresh(conn,cfg)
    assert packet['status']=='stale' and not packet['entries']
    assert not read(conn,cfg)['entries']


@pytest.mark.parametrize('field,value',[('history','true'),('history',1),('context_chars','4800'),('context_chars',True)])
def test_mcp_rejects_coerced_wire_types(field,value):
    from mcp.server.fastmcp.utilities.func_metadata import func_metadata
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        func_metadata(mcp_server.memory_summary).arg_model.model_validate({'topic':'outage',field:value})
