import pytest
import psycopg
from agentic_rag import db, evidence, jobs, profiles, store, worker
from agentic_rag.domains import seed_defaults

PROJECT = '/synthetic/profile-a'

@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    conn.execute('DELETE FROM project_profiles')
    conn.commit()
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def put(conn, cfg, text='We prefer explicit tests.', *, kind='stated', project=PROJECT, quote=None):
    return store.save_claim(conn, cfg, title='Preference', body=text, domain='general',
        dtype='memory', project=project, claim_kind=kind, evidence=[{
        'namespace':'synthetic', 'source_id':text, 'role':'user',
        'quote': quote or text, 'complete':True}])


def test_missing_bounded_stable_and_recent(conn, cfg):
    assert profiles.read(conn,cfg,PROJECT)['status']=='missing'
    for n in range(9): put(conn,cfg,f'We prefer explicit tests {n}.')
    for n in range(9):
        store.save_document(conn,cfg,title=f'Focus {n}',body='Legacy focus',domain='general',dtype='memory',project=PROJECT)
    put(conn,cfg,'We prefer unsupported assumptions.',quote='Unrelated source.')
    put(conn,cfg,'We prefer proposals.',kind='proposal')
    store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert view['status']=='fresh'
    assert len(view['sections']['stable'])==6
    assert len(view['sections']['recent'])==6
    assert all(x['text'].startswith('We prefer explicit tests') for x in view['sections']['stable'])
    assert all(len(x['text'])<=600 and len(x['source_keys'])<=8 for s in view['sections'].values() for x in s)
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='profile_refresh'").fetchone()['n']==1


def test_source_loss_revalidates_dated_cache_and_revision(conn,cfg):
    doc=put(conn,cfg)
    store.refresh_profile(conn,cfg,PROJECT)
    old=profiles.read(conn,cfg,PROJECT)
    key=evidence.sources(conn,doc.doc_id)[0]['source_key']
    store.set_source_state(conn,key,state='removed',reason='withdrawn')
    view=profiles.read(conn,cfg,PROJECT)
    assert view['status']=='stale' and view['generated_at']==old['generated_at']
    assert view['revision']!=old['revision'] and view['warnings']
    assert view['sections']=={'stable':[],'recent':[]}


def test_revision_scoped_and_cache_failure_atomic(conn,cfg,monkeypatch):
    put(conn,cfg)
    store.refresh_profile(conn,cfg,PROJECT)
    old=profiles.read(conn,cfg,PROJECT)
    put(conn,cfg,'We prefer other project.',project='/synthetic/profile-b')
    assert profiles.read(conn,cfg,PROJECT)['revision']==old['revision']
    assert profiles.read(conn,cfg,None)['sections']=={'stable':[],'recent':[]}
    put(conn,cfg,'We prefer a new convention.')
    def fail(*a,**kw): raise RuntimeError('audit unavailable')
    monkeypatch.setattr(profiles,'_audit',fail)
    with pytest.raises(RuntimeError): store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert view['generated_at']==old['generated_at'] and view['status']=='stale'
    assert view['sections']==old['sections']


def test_reader_and_async_dispatch(conn,cfg):
    put(conn,cfg)
    with db.connect(cfg,role='reader') as reader:
        assert profiles.read(reader,cfg,PROJECT)['status']=='missing'
        with pytest.raises(psycopg.errors.InsufficientPrivilege): store.refresh_profile(reader,cfg,PROJECT)
    assert jobs.enqueue_profile(conn,cfg,PROJECT)
    assert not jobs.enqueue_profile(conn,cfg,PROJECT)
    job=conn.execute("SELECT * FROM mining_queue WHERE kind='profile_refresh'").fetchone()
    worker.process_job(conn,cfg,dict(job))
    with db.connect(cfg,role='reader') as reader:
        assert profiles.read(reader,cfg,PROJECT)['sections']['stable']


def test_long_stated_text_never_truncates_into_stable_instruction(conn,cfg):
    text='We prefer '+('a'*600)+' but only under explicit approval.'
    put(conn,cfg,text)
    store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert not view['sections']['stable']
    assert view['sections']['recent'][0]['text'].endswith('…')


def test_expiry_changes_revision_without_writes_and_correction_filters_old(conn,cfg):
    from datetime import datetime,timedelta,timezone
    from tests.test_validity import put as assertion
    now=datetime.now(timezone.utc)
    old=assertion(conn,cfg,'7000',(now-timedelta(days=2)).isoformat(),project=PROJECT)
    store.refresh_profile(conn,cfg,PROJECT)
    before=profiles.read(conn,cfg,PROJECT)
    assert before['sections']['recent'][0]['id']==old.doc_id
    assertion(conn,cfg,'8000',(now-timedelta(days=1)).isoformat(),project=PROJECT,
              relation='replacement',expires_at=(datetime.now(timezone.utc)+timedelta(seconds=.5)).isoformat())
    assert not profiles.read(conn,cfg,PROJECT)['sections']['recent']
    store.refresh_profile(conn,cfg,PROJECT)
    fresh=profiles.read(conn,cfg,PROJECT)
    assert len(fresh['sections']['recent'])==1
    conn.execute('SELECT pg_sleep(0.6)')
    expired=profiles.read(conn,cfg,PROJECT)
    assert expired['revision']!=fresh['revision'] and expired['status']=='stale'
    assert not expired['sections']['recent']


def test_cache_constraints_and_writer_refresh_preserve_canonical_rows(conn,cfg):
    put(conn,cfg)
    before=conn.execute('SELECT row_to_json(d) AS data FROM documents d ORDER BY id').fetchall()
    with db.connect(cfg,role='writer') as writer:
        profiles.refresh(writer,cfg,PROJECT)
    assert conn.execute('SELECT row_to_json(d) AS data FROM documents d ORDER BY id').fetchall()==before
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE project_profiles SET stable_ids=array_fill(gen_random_uuid(),ARRAY[7])")
    conn.rollback()
    assert len(profiles.read(conn,cfg,PROJECT)['sections']['stable'])==1
    from dataclasses import replace
    assert profiles.read(conn,replace(cfg,stale_days=1),PROJECT)['status']=='stale'


def test_explicit_use_convention_and_bounded_body(conn,cfg):
    put(conn,cfg,'We use pytest for this project.')
    store.save_document(conn,cfg,title='Large',body='x'*10000,domain='general',dtype='memory',project=PROJECT)
    store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert view['sections']['stable'][0]['text']=='We use pytest for this project.'
    assert len(view['sections']['recent'][0]['text'])==600


def test_source_resolution_bounds_spans_and_retains_late_support(conn,cfg):
    text='We prefer bounded evidence.'
    doc=put(conn,cfg,text,quote='Unrelated original quote.')
    for n in range(24):
        evidence.attach(conn,doc.doc_id,[{'namespace':'synthetic-many','source_id':str(n),
            'role':'user','quote':f'Unrelated span {n}.','complete':True}],actor='test')
    all_sources=evidence.sources(conn,doc.doc_id)
    last=sorted(all_sources,key=lambda s:s['source_key'])[-1]
    evidence.attach(conn,doc.doc_id,[{'namespace':last['namespace'],'source_id':last['source_id'],
        'role':'user','quote':text,'complete':True}],actor='test')
    conn.commit()
    assert len(evidence.sources(conn,doc.doc_id))>24
    rows=profiles._rows(conn,cfg,PROJECT,ids=[doc.doc_id])
    assert len(rows[0]['sources'])<=8
    assert any(s['quote']==text for s in rows[0]['sources'])
    assert 'assertion_sources' not in rows[0]
    store.refresh_profile(conn,cfg,PROJECT)
    item=profiles.read(conn,cfg,PROJECT)['sections']['stable'][0]
    assert last['source_key'] in item['source_keys'] and len(item['source_keys'])<=8


def test_capped_sources_keep_incomplete_provenance(conn,cfg):
    doc=put(conn,cfg)
    for n in range(9):
        evidence.attach(conn,doc.doc_id,[{'namespace':'many','source_id':str(n),
            'role':'user','quote':'We prefer explicit tests.','complete':True}],actor='test')
    evidence.attach(conn,doc.doc_id,[{'namespace':'many','source_id':'incomplete',
        'role':'user','quote':'partial','complete':False}],actor='test')
    store.review_claim(conn,doc.doc_id,state='confirmed',reason='reviewed all attached evidence')
    store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert view['sections']['stable'][0]['provenance_status']=='incomplete'
    assert any('capped at eight' in warning for warning in view['warnings'])


def test_recent_includes_updated_legacy_and_section_cap_warning(conn,cfg):
    legacy=store.save_document(conn,cfg,title='Old origin',body='Updated focus.',
        domain='general',dtype='memory',project=PROJECT)
    # Fixture represents a legacy document created long ago and updated now.
    conn.execute("UPDATE documents SET created_at=now()-interval '90 days' WHERE id=%s",(legacy.doc_id,))
    conn.commit()
    for n in range(7): put(conn,cfg,f'We prefer convention {n}.')
    store.refresh_profile(conn,cfg,PROJECT)
    view=profiles.read(conn,cfg,PROJECT)
    assert legacy.doc_id in [x['id'] for x in view['sections']['recent']]
    assert any('stable limited to six' in w for w in view['warnings'])
