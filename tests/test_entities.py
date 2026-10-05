"""Entity relations preserve originals and cannot bridge scope or source trust."""
import pytest
from agentic_rag import store, domains

PROJECT = '/synthetic/entities/a'


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    domains.seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)


def fact(conn, cfg, name, attribute, value, when='2026-01-01T00:00:00Z', **kwargs):
    return store.save_assertion(conn, cfg, entity=name, attribute=attribute, value=value,
        domain=kwargs.pop('domain','general'), project=kwargs.pop('project',PROJECT),
        event_at=when, evidence={'source_id':__import__('hashlib').sha256((name+attribute+value+when).encode()).hexdigest(), 'namespace':'entity-tests',
        'role':'user', 'quote':f'{name} {attribute} is now {value}'}, **kwargs)


def link(conn,cfg,alias='orion-old',target='orion',**kwargs):
    return store.save_entity_alias(conn,cfg,alias=alias,target=target,domain='general',
        project=PROJECT,effective_at='2026-02-01T00:00:00Z',
        evidence={'namespace':'alias-tests','source_id':alias+'->'+target,'role':'user',
        'quote':f'{alias} is another name for {target}.','complete':True},**kwargs)


def test_alternate_names_find_original_facts_and_revocation_separates(conn,cfg):
    # Mutation caught: treating a confirmed alias as a destructive identity union.
    one=fact(conn,cfg,'orion','port','8766')
    two=fact(conn,cfg,'orion-old','tls','enabled')
    assert hasattr(store,'save_entity_alias'), 'An audited reversible alias gateway is required'
    relation=link(conn,cfg,confirm=True)
    assert relation['state']=='accepted'
    from agentic_rag.entities import read
    packet=read(conn,'orion-old',domain='general',project=PROJECT)
    assert {f['document_id'] for f in packet['facts']}=={one.doc_id,two.doc_id}
    for item in packet['facts']:
        chunk=conn.execute('SELECT content FROM chunks WHERE id=%s',(item['chunk_id'],)).fetchone()
        assert chunk['content'][item['start']:item['end']]==item['text']
    store.review_entity_alias(conn,relation['document_id'],state='revoked',reason='mistaken link')
    assert [f['document_id'] for f in read(conn,'orion-old',domain='general',project=PROJECT)['facts']]==[two.doc_id]
    assert store.get_document(conn,one.doc_id)['assertion']['entity']=='orion'
    assert store.get_document(conn,two.doc_id)['assertion']['entity']=='orion-old'


def test_rename_as_of_current_expiry_and_history(conn,cfg):
    # Mutation caught: selecting by ingestion time or reviving an expired replacement.
    new=fact(conn,cfg,'orion','status','running','2026-03-01T00:00:00Z',relation='replacement',expires_at='2026-05-01T00:00:00Z')
    old=fact(conn,cfg,'orion-old','status','stopped')  # late import
    link(conn,cfg,confirm=True)
    from agentic_rag.entities import read
    opts=dict(domain='general',project=PROJECT)
    assert [f['document_id'] for f in read(conn,'orion-old',as_of='2026-01-15T00:00:00Z',**opts)['facts']]==[old.doc_id]
    assert [f['document_id'] for f in read(conn,'orion-old',as_of='2026-04-01T00:00:00Z',**opts)['facts']]==[new.doc_id]
    assert read(conn,'orion-old',as_of='2026-05-01T00:00:00Z',**opts)['facts']==[]
    history=read(conn,'orion-old',history=True,**opts)
    assert {f['document_id'] for f in history['facts']}=={old.doc_id,new.doc_id}
    assert next(f for f in history['facts'] if f['document_id']==old.doc_id)['superseded']
    assert next(f for f in history['facts'] if f['document_id']==new.doc_id)['expired']


def test_review_suggestions_competing_anchor_and_no_transitive_merge(conn,cfg):
    from agentic_rag.entities import read
    fact(conn,cfg,'orion','port','8766');fact(conn,cfg,'orion-old','tls','enabled')
    proposed=link(conn,cfg)
    assert proposed['state']=='review'
    assert len(read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==1
    assert read(conn,'orion-old',domain='general',project=PROJECT)['suggestions'][0]['state']=='review'
    store.review_entity_alias(conn,proposed['document_id'],state='accepted',reason='checked original quote')
    assert link(conn,cfg,alias='orion',target='third',confirm=True)['state']=='review'
    assert link(conn,cfg,alias='orion-old',target='another',confirm=True)['state']=='review'
    assert link(conn,cfg,alias='fourth',target='orion-old',confirm=True)['state']=='review'
    assert len(read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==2
    counts=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    assert link(conn,cfg,confirm=True)['duplicate']
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==counts


def test_project_domain_and_global_are_exact_boundaries(conn,cfg):
    from agentic_rag.entities import read
    domains.add_domain(conn,'infrastructure')
    a=fact(conn,cfg,'server','status','running')
    b=fact(conn,cfg,'server','status','offline',project='/synthetic/entities/b')
    g=store.save_assertion(conn,cfg,entity='server',attribute='status',value='global',domain='general',scope='global',
        event_at='2026-01-01T00:00:00Z',evidence={'source_id':'global','role':'user','quote':'global'})
    # Both ordinary and entity reads retain facts in the other domain.
    foreign=fact(conn,cfg,'server','status','other-domain','2026-03-01T00:00:00Z',domain='infrastructure',relation='replacement')
    assert [f['document_id'] for f in read(conn,'server',domain='general',project=PROJECT)['facts']]==[a.doc_id]
    assert [f['document_id'] for f in read(conn,'server',domain='general',project='/synthetic/entities/b')['facts']]==[b.doc_id]
    assert [f['document_id'] for f in read(conn,'server',domain='general',scope='global')['facts']]==[g.doc_id]
    assert [f['document_id'] for f in read(conn,'server',domain='infrastructure',project=PROJECT)['facts']]==[foreign.doc_id]
    ids={read(conn,'server',domain='general',project=p)['identity_id'] for p in (PROJECT,'/synthetic/entities/b')}
    assert len(ids)==2


def test_bound_confirmed_span_cannot_inherit_later_unreviewed_support(conn,cfg):
    from agentic_rag import entities,evidence
    fact(conn,cfg,'orion','port','8766');fact(conn,cfg,'orion-old','tls','enabled')
    relation=link(conn,cfg,confirm=True)
    original=evidence.sources(conn,relation['document_id'])[0]['source_key']
    body=store.get_document(conn,relation['document_id'])['body']
    other=store.save_claim(conn,cfg,title='Later source',body=body,domain='general',dtype='memory',project=PROJECT,
        claim_kind='stated',evidence=[{'namespace':'another','source_id':'later','role':'user','quote':body,'complete':True}])
    assert other.doc_id==relation['document_id']
    store.set_source_state(conn,original,state='removed',reason='withdraw original relation')
    packet=entities.read(conn,'orion-old',domain='general',project=PROJECT)
    assert len(packet['facts'])==1 and packet['links']==[]
    assert packet['suggestions'][0]['state']=='accepted'
    with pytest.raises(ValueError,match='original complete active user'):
        store.review_entity_alias(conn,relation['document_id'],state='accepted',reason='cannot inherit later source')
    store.set_source_state(conn,original,state='active',reason='revalidated source')
    store.review_claim(conn,relation['document_id'],state='unreviewed',reason='needs another review')
    assert len(entities.read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==1
    store.review_entity_alias(conn,relation['document_id'],state='accepted',reason='explicit revalidation')
    assert len(entities.read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==2


def test_withdrawn_newer_fact_does_not_resurrect_old_status(conn,cfg):
    from agentic_rag import entities,evidence
    old=fact(conn,cfg,'orion-old','status','stopped')
    new=fact(conn,cfg,'orion','status','running','2026-03-01T00:00:00Z',relation='replacement')
    link(conn,cfg,confirm=True)
    store.set_source_state(conn,evidence.sources(conn,new.doc_id)[0]['source_key'],state='removed',reason='withdraw status')
    assert entities.read(conn,'orion-old',domain='general',project=PROJECT)['facts']==[]
    assert [f['document_id'] for f in entities.read(conn,'orion-old',domain='general',project=PROJECT,history=True)['facts']]==[old.doc_id]


def test_current_conflicts_are_reviewable_without_answer_context(conn,cfg):
    from agentic_rag.entities import read
    fact(conn,cfg,'orion','port','8766')
    fact(conn,cfg,'orion-old','port','8000')
    link(conn,cfg,confirm=True)
    result=read(conn,'orion',domain='general',project=PROJECT)
    assert result['status']=='ambiguous' and result['context']==''
    assert {f['value'] for f in result['facts']}=={'8766','8000'}
    assert all(f['ambiguous'] for f in result['facts'])


def test_cli_and_mcp_expose_additive_read_and_gated_writes(conn,cfg,hook_env,capsys):
    from agentic_rag import cli,mcp_server
    assert 'memory_entity' in mcp_server.tool_names(True)
    assert 'memory_entity_alias' in mcp_server.tool_names(False)
    assert 'memory_entity_alias' not in mcp_server.tool_names(True)
    assert 'memory_entity_alias_review' not in mcp_server.tool_names(True)
    one=fact(conn,cfg,'orion','port','8766')
    assert cli.main(['entity','resolve','orion','--project',PROJECT,'--domain','general'])==0
    import json
    assert json.loads(capsys.readouterr().out)['facts'][0]['document_id']==one.doc_id
    assert mcp_server.memory_entity('orion',domain='general',project=PROJECT)['facts'][0]['document_id']==one.doc_id
    saved=mcp_server.memory_entity_alias(alias='orion-old',target='orion',domain='general',project=PROJECT,
        effective_at='2026-02-01T00:00:00Z',evidence={'namespace':'mcp','source_id':'manual','role':'user',
        'quote':'orion-old is another name for orion.','complete':True})
    assert saved['state']=='review'
    assert mcp_server.memory_entity_alias_review(saved['document_id'],'accepted','checked original source')['state']=='accepted'


@pytest.mark.parametrize('changes',[
    {'name':''},{'name':'x\x00y'},{'name':'x'*2001},{'domain':''},{'domain':None},
    {'project':None},{'scope':'all','project':None},{'scope':'unknown','project':None},
    {'scope':'global'},{'project':'relative'}, {'context_chars':999},{'context_chars':12001},
    {'context_chars':True},{'history':'true'},{'as_of':'2026-01-01'},
    {'history':True,'as_of':'2026-01-01T00:00:00Z'},{'attribute':''},
])
def test_malformed_entity_read_rejected_before_sql(conn,changes):
    from agentic_rag.entities import read
    before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    arguments=dict(name='host',domain='general',project=PROJECT)
    arguments.update(changes)
    with pytest.raises((ValueError,TypeError)):
        read(conn,**arguments)
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before


@pytest.mark.parametrize('changes',[
    {'alias':''},{'alias':'x\x00y'},{'target':'orion-old'},{'target':'x'*2001},
    {'domain':''},{'project':None},{'scope':'unknown','project':None},{'confirm':'true'},
    {'effective_at':None},{'effective_at':'2026-02-01'},
    {'evidence':{}},{'evidence':{'namespace':'n','source_id':'s','role':'user','quote':'x'*4001}},
    {'evidence':{'namespace':'n','source_id':'s','role':'system','quote':'names'}},
    {'evidence':{'namespace':'n','source_id':'s','role':'user','quote':'x\x00y'}},
])
def test_malformed_alias_is_atomic(conn,cfg,changes):
    before={t:conn.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in ('documents','entity_identities','entity_aliases','audit_log')}
    arguments=dict(alias='orion-old',target='orion',domain='general',project=PROJECT,
        effective_at='2026-02-01T00:00:00Z',evidence={'namespace':'malformed','source_id':'s','role':'user','quote':'names','complete':True})
    arguments.update(changes)
    with pytest.raises((ValueError,TypeError)):
        store.save_entity_alias(conn,cfg,**arguments)
    for table in before:
        assert conn.execute('SELECT count(*) n FROM '+table).fetchone()['n']==before[table]


@pytest.mark.parametrize('changes',[
    {'role':'assistant'},{'role':'unknown'},{'complete':False},{'complete':'true'},
    {'quote':'orion might be another host; no old name given'},
])
def test_uncertain_alias_support_is_retained_for_review(conn,cfg,changes):
    evidence={'namespace':'untrusted','source_id':'s','role':'user','quote':'orion-old is another name for orion.','complete':True}
    evidence.update(changes)
    result=store.save_entity_alias(conn,cfg,alias='orion-old',target='orion',domain='general',project=PROJECT,
        effective_at='2026-02-01T00:00:00Z',evidence=evidence,confirm=True)
    assert result['state']=='review'
    assert store.get_document(conn,result['document_id'])['body']==evidence['quote']


def test_gateway_rollback_preserves_all_alias_effects_and_caller_work(conn,cfg,monkeypatch):
    from agentic_rag import entities
    baseline={t:conn.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in
        ('documents','claim_records','claim_evidence','knowledge_sources','entity_identities','entity_aliases','audit_log')}
    real=entities._audit
    def crash(*a,**kw):
        real(*a,**kw)
        if a[2]=='entity_alias_save':
            raise RuntimeError('crash after relation mutation')
    monkeypatch.setattr(entities,'_audit',crash)
    with pytest.raises(RuntimeError,match='crash'):
        link(conn,cfg,confirm=True)
    assert {t:conn.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in baseline}==baseline
    monkeypatch.setattr(entities,'_audit',real)
    conn.rollback()
    link(conn,cfg,confirm=True,commit=False)  # previously idle caller
    conn.rollback()
    assert {t:conn.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in baseline}==baseline
    retry=link(conn,cfg,confirm=True)
    assert retry['state']=='accepted'
    assert link(conn,cfg,confirm=True)['document_id']==retry['document_id']


def test_backfill_attachment_failure_rolls_back_index_and_audit(conn,cfg,monkeypatch):
    from agentic_rag import entities
    saved=fact(conn,cfg,'host','port','8000')
    before={t:conn.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in
        ('documents','fact_assertions','claim_evidence','assertion_entities','entity_identities','audit_log')}
    original=entities.attach_assertion
    def fail(*a,**kw):
        original(*a,**kw)
        raise RuntimeError('crash after index mutation')
    monkeypatch.setattr(entities,'attach_assertion',fail)
    with pytest.raises(RuntimeError):
        store.backfill_entity_identities(conn)
    for table in before:
        assert conn.execute('SELECT count(*) n FROM '+table).fetchone()['n']==before[table]
    monkeypatch.setattr(entities,'attach_assertion',original)
    conn.rollback()
    store.backfill_entity_identities(conn,commit=False)
    conn.rollback()
    assert conn.execute('SELECT count(*) n FROM assertion_entities').fetchone()['n']==0
    assert store.get_document(conn,saved.doc_id)['body']=='8000'


def test_stale_domain_attachment_repaired_audited_without_rewriting_fact(conn,cfg):
    from agentic_rag import entities
    domains.add_domain(conn,'infrastructure')
    saved=fact(conn,cfg,'host','port','8000')
    store.backfill_entity_identities(conn)
    original=conn.execute('SELECT to_jsonb(a) data FROM fact_assertions a WHERE document_id=%s',(saved.doc_id,)).fetchone()['data']
    old_identity=conn.execute('SELECT entity_id FROM assertion_entities WHERE document_id=%s',(saved.doc_id,)).fetchone()['entity_id']
    store.set_domain(conn,saved.doc_id,'infrastructure')
    assert entities.read(conn,'host',domain='general',project=PROJECT)['facts']==[]
    new=entities.read(conn,'host',domain='infrastructure',project=PROJECT)
    assert new['facts'][0]['document_id']==saved.doc_id and new['warnings']
    assert store.backfill_entity_identities(conn,limit=1)==dict(mapped=1,remaining=0,unresolved=0)
    assert conn.execute('SELECT entity_id FROM assertion_entities WHERE document_id=%s',(saved.doc_id,)).fetchone()['entity_id']!=old_identity
    assert conn.execute('SELECT to_jsonb(a) data FROM fact_assertions a WHERE document_id=%s',(saved.doc_id,)).fetchone()['data']==original
    audits=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    assert store.backfill_entity_identities(conn)['mapped']==0
    assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==audits


def test_relation_domain_drift_invalidates_until_boundary_restored(conn,cfg):
    from agentic_rag.entities import read
    domains.add_domain(conn,'infrastructure')
    fact(conn,cfg,'orion','port','8766');fact(conn,cfg,'orion-old','tls','enabled')
    saved=link(conn,cfg,confirm=True)
    store.set_domain(conn,saved['document_id'],'infrastructure')
    assert len(read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==1
    with pytest.raises(ValueError,match='unchanged scope/domain'):
        store.review_entity_alias(conn,saved['document_id'],state='accepted',reason='must not cross domain')


def test_read_only_roles_cannot_mutate_alias_index_and_writer_cannot_rewire(conn,cfg):
    import psycopg
    from agentic_rag import db
    saved=link(conn,cfg,confirm=True)
    with db.connect(cfg,role='reader') as reader:
        for sql in ("UPDATE entity_aliases SET state='revoked'",'DELETE FROM entity_identities',
                    'UPDATE assertion_entities SET indexed_at=now()'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute(sql)
            reader.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.review_entity_alias(reader,saved['document_id'],state='revoked',reason='reader has no authority')
    with db.connect(cfg,role='writer') as writer:
        for sql in ('UPDATE entity_aliases SET target_id=alias_id','DELETE FROM entity_aliases',
                    "UPDATE entity_identities SET name='hijack'"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                writer.execute(sql)
            writer.rollback()


def test_competing_concurrent_confirmations_activate_one_anchor(conn,cfg):
    from concurrent.futures import ThreadPoolExecutor
    from agentic_rag import db
    def write(target):
        with db.connect(cfg,role='writer') as writer:
            writer.execute("SET LOCAL lock_timeout='3s'")
            return link(writer,cfg,target=target,confirm=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(write,['anchor-a','anchor-b']))
    assert sorted(r['state'] for r in outcomes)==['accepted','review']


def test_assertion_alias_shared_source_has_consistent_lock_order(conn,cfg):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from agentic_rag import db
    start=Barrier(2)
    source={'namespace':'shared-lock','source_id':'same-event','role':'user',
            'quote':'orion-old is another name for orion, port 8766.','complete':True}
    def write(mode):
        with db.connect(cfg,role='writer') as writer:
            writer.execute("SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='5s'")
            start.wait(timeout=3)
            if mode=='alias':
                return store.save_entity_alias(writer,cfg,alias='orion-old',target='orion',domain='general',project=PROJECT,
                    effective_at='2026-02-01T00:00:00Z',evidence=source,confirm=True)['state']
            return store.save_assertion(writer,cfg,entity='orion',attribute='port',value='8766',domain='general',
                project=PROJECT,event_at='2026-02-01T00:00:00Z',evidence=source).disposition
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(write,['alias','assertion']))==['accepted','accepted']


def test_optional_sql_failure_preserves_caller_transaction_and_settings(conn,cfg,monkeypatch):
    from agentic_rag import entities
    conn.execute("SET LOCAL statement_timeout='100ms'; SET LOCAL lock_timeout='50ms'")
    fact(conn,cfg,'caller','port','8000',commit=False)
    def fail(c):
        c.execute('SELECT missing_entity_optional_function()')
    monkeypatch.setattr(entities,'available',fail)
    result=entities.read(conn,'caller',domain='general',project=PROJECT)
    assert result['status']=='unavailable' and result['facts']==[]
    assert conn.execute("SELECT current_setting('statement_timeout') s,current_setting('lock_timeout') l").fetchone()=={'s':'100ms','l':'50ms'}
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n']==1
    conn.rollback()
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n']==0


def test_limits_withhold_incomplete_answer_not_revive_hidden_replacement(conn,cfg,monkeypatch):
    from agentic_rag import entities
    fact(conn,cfg,'orion-old','status','stopped')
    new=fact(conn,cfg,'orion','status','running','2026-03-01T00:00:00Z',relation='replacement')
    fact(conn,cfg,'orion','tls','enabled')
    link(conn,cfg,confirm=True)
    monkeypatch.setattr(entities,'FACT_LIMIT',1)
    result=entities.read(conn,'orion-old',domain='general',project=PROJECT)
    assert result['status']=='limited' and result['facts']==[] and result['context']==''
    monkeypatch.setattr(entities,'FACT_LIMIT',100)
    monkeypatch.setattr(entities,'LINK_LIMIT',0)
    result=entities.read(conn,'orion-old',domain='general',project=PROJECT)
    assert result['status']=='limited' and result['context']==''


def test_context_budget_and_long_titles_keep_original_value_citations(conn,cfg):
    from agentic_rag.entities import read
    name='h'*1900
    attr='a'*1900
    fact(conn,cfg,name,attr,'port 8766')
    packet=read(conn,name,domain='general',project=PROJECT,context_chars=1000)
    assert packet['facts'][0]['value'] in packet['facts'][0]['text']
    assert packet['context']=='' and packet['context_chars']<=1000
    assert packet['warnings']


def test_old_client_unindexed_facts_have_same_stable_id_after_backfill(conn,cfg,monkeypatch):
    from agentic_rag import entities
    real=entities.attach_assertion
    monkeypatch.setattr(entities,'attach_assertion',lambda *a:False)
    saved=fact(conn,cfg,'legacy-host','port','8766')
    before=entities.read(conn,'legacy-host',domain='general',project=PROJECT)
    assert before['identity_id'] is not None
    assert before['facts'][0]['identity_id']==before['identity_id']
    assert not before['identity_persisted']
    monkeypatch.setattr(entities,'attach_assertion',real)
    assert store.backfill_entity_identities(conn)['mapped']==1
    after=entities.read(conn,'legacy-host',domain='general',project=PROJECT)
    assert before['identity_id']==after['identity_id'] and after['identity_persisted']
    assert after['facts'][0]['document_id']==saved.doc_id


def test_alias_limit_also_bounds_names_and_reports_total(conn,cfg,monkeypatch):
    from agentic_rag import entities
    link(conn,cfg,alias='one',confirm=True);link(conn,cfg,alias='two',confirm=True)
    monkeypatch.setattr(entities,'LINK_LIMIT',1)
    packet=entities.read(conn,'orion',domain='general',project=PROJECT)
    assert packet['status']=='limited' and packet['context']==''
    assert len(packet['names'])<=2
    assert packet['name_count']==3


def test_admin_document_purge_retains_legacy_delete_contract(conn,cfg,monkeypatch):
    # Mutation caught: additive relation FKs breaking an authorized document purge.
    from agentic_rag import curation,db
    relation=link(conn,cfg,confirm=True)
    doc=store.get_document(conn,relation['document_id'])
    correction=store.save_document(conn,cfg,title='Correction',body='The link was wrong.',domain='general',
        dtype='lesson',project=PROJECT,edges=[store.EdgeSpec('contradicts',doc['slug'],'The link was wrong.','high')],actor='mining')
    # Boundary double supplies a selected refutation without a provider call;
    # actual scope recheck, justified refutation and admin purge remain real.
    monkeypatch.setattr(curation,'_refute_candidates',lambda *a:[dict(id=doc['id'],slug=doc['slug'],title=doc['title'],
        body=doc['body'],source_id=correction.doc_id,expected_scope=PROJECT,contra_body='The link was wrong.',
        evidence='The link was wrong.',evidence_at=doc['created_at'])])
    monkeypatch.setattr(curation,'run_structured',lambda *a,**kw:dict(refute=True,reason='Wrong alias',quote='The link was wrong.'))
    assert curation.run_pass(conn,cfg,budget=1).refuted==1
    with db.connect(cfg,role='admin') as admin:
        assert curation.purge(admin,older_days=-1,assume_yes=True)==1
    assert conn.execute('SELECT count(*) n FROM entity_aliases').fetchone()['n']==0
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='entity_alias_save'").fetchone()['n']==1


def test_cross_domain_distinct_saves_do_not_deadlock(conn,cfg):
    from concurrent.futures import ThreadPoolExecutor
    from agentic_rag import db
    domains.add_domain(conn,'infrastructure')
    saved=fact(conn,cfg,'host','port','8766')
    def write(domain):
        with db.connect(cfg,role='writer') as c:
            c.execute("SET LOCAL lock_timeout='2s'; SET LOCAL statement_timeout='4s'")
            return fact(c,cfg,'host','port','8766',domain=domain).doc_id
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write,['infrastructure','general']))
        assert results[0] != saved.doc_id
        assert results[1] == saved.doc_id


def test_caller_owned_assertion_batch_and_concurrent_second_key_complete(conn,cfg):
    # Mutation caught: adding a per-call boundary lock after an exact-key lock
    # while a prior assertion in the caller's transaction still holds that boundary.
    from concurrent.futures import ThreadPoolExecutor
    import time
    from agentic_rag import db
    first=fact(conn,cfg,'batch-host','one','v1',commit=False)
    def other():
        with db.connect(cfg,role='writer') as c:
            c.execute("SET LOCAL application_name='entity-batch-other'; SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='5s'")
            return fact(c,cfg,'batch-host','two','v2')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(other)
        with db.connect(cfg,role='owner') as observer:
            for _ in range(100):
                row=observer.execute("SELECT wait_event_type FROM pg_stat_activity WHERE application_name='entity-batch-other'").fetchone()
                observer.rollback()
                if future.done() or (row and row['wait_event_type']=='Lock'):
                    break
                time.sleep(.02)
        conn.execute("SET LOCAL lock_timeout='3s'; SET LOCAL statement_timeout='5s'")
        second=fact(conn,cfg,'batch-host','two','v2',commit=False)
        conn.commit()
        assert future.result(timeout=5).doc_id==second.doc_id
    assert first.doc_id!=second.doc_id
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n']==2


def test_cli_alias_review_and_backfill_match_gateway(conn,cfg,hook_env,capsys):
    import json
    from agentic_rag import cli,entities
    fact(conn,cfg,'orion','port','8766');fact(conn,cfg,'orion-old','tls','enabled')
    assert cli.main(['entity','alias','--alias','orion-old','--target','orion','--domain','general','--project',PROJECT,
        '--namespace','cli-alias','--source-id','manual','--quote','orion-old is another name for orion.',
        '--effective-at','2026-02-01T00:00:00Z','--complete'])==0
    relation=json.loads(capsys.readouterr().out)
    assert relation['state']=='review'
    assert cli.main(['entity','review',relation['document_id'],'--state','accepted','--reason','checked source'])==0
    assert json.loads(capsys.readouterr().out)['state']=='accepted'
    assert len(entities.read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==2
    assert cli.main(['entity','backfill','--limit','1'])==0
    batch=json.loads(capsys.readouterr().out)
    assert batch=={'mapped':1,'remaining':1,'unresolved':0}
    assert cli.main(['entity','backfill','--limit','1'])==0
    assert json.loads(capsys.readouterr().out)=={'mapped':1,'remaining':0,'unresolved':0}
    assert cli.main(['entity','review',relation['document_id'],'--state','revoked','--reason','wrong link'])==0
    assert json.loads(capsys.readouterr().out)['state']=='revoked'
    assert len(entities.read(conn,'orion-old',domain='general',project=PROJECT)['facts'])==1


def test_candidate_on_populated017_retains_legacy_reads_writes_and_fallback(cfg,tmp_path):
    import shutil
    from unittest.mock import patch
    from agentic_rag import db,entities,search
    from agentic_rag.benchmark.database import isolated_database
    old_sql=tmp_path/'sql017';old_sql.mkdir()
    for file in db.SQL_DIR.glob('*.sql'):
        if file.name<'018':shutil.copyfile(file,old_sql/file.name)
    initialize=db.init_db
    with patch.object(db,'init_db',lambda c:initialize(c,sql_dir=old_sql)),isolated_database(cfg) as owned:
        with db.connect(owned,role='writer') as writer:
            saved=fact(writer,owned,'legacy-on017','port','8766')
            packet=entities.read(writer,'legacy-on017',domain='general',project=PROJECT)
            assert packet['status']=='unavailable' and packet['warnings']
            assert writer.execute('SELECT 1 ok').fetchone()['ok']==1
            assert [h.document_id for h in search.search(writer,owned,'legacy-on017',project=PROJECT,strategy='lexical')[0]]==[saved.doc_id]
            with pytest.raises(ValueError,match='migration018'):
                link(writer,owned,confirm=True)
            assert store.get_document(writer,saved.doc_id)['body']=='8766'
        with db.connect(owned,role='owner') as owner:
            assert db.apply_migrations(owner,db.SQL_DIR)==['018_entity_identities.sql', '019_embedding_reuse.sql', '020_domain_assertions.sql']
        with db.connect(owned,role='reader') as reader:
            initial=entities.read(reader,'legacy-on017',domain='general',project=PROJECT)
            assert not initial['identity_persisted'] and initial['facts'][0]['document_id']==saved.doc_id
        with db.connect(owned,role='writer') as writer:
            assert store.backfill_entity_identities(writer)['mapped']==1
        with db.connect(owned,role='reader') as reader:
            later=entities.read(reader,'legacy-on017',domain='general',project=PROJECT)
            assert initial['identity_id']==later['identity_id'] and later['identity_persisted']
