"""Private correction labels never inherit synthetic/provider authority."""
import json

import pytest

from agentic_rag.config import Config


def _private_case(variant=0, value='8000'):
    """Hand-authored user correction; hashes only frame the serialized fixture."""
    import hashlib
    def digest(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    entity='Orion' if variant==0 else 'Orion '+str(variant)
    source_id='original' if variant==0 else 'original-'+str(variant)
    family=digest(['global','general',entity,'port'])
    quote=entity+' port is now '+value
    source=dict(namespace='operator',source_id=source_id,role='user',source_at=None,state='active',
        changed_at='2026-01-01T00:00:00+00:00',quote=quote,complete=True,reviewed=True,evidence_version='1',source_version='1',
        recorded_at='2026-01-01T00:00:00+00:00',retained_version='1',
        source_key=hashlib.sha256(json.dumps(['operator',source_id]).encode()).hexdigest(),
        span_hash=hashlib.sha256(quote.encode()).hexdigest(),retained_hash='a'*64)
    source['original_sha256']=digest(source)
    identity=f'00000000-0000-4000-8000-{variant+1:012d}'
    history=dict(document_id=identity,entity=entity,attribute='port',value=value,relation='replacement',
        event_at='2026-01-01T00:00:00+00:00',expires_at=None,document_version='1',assertion_version='1',original_sha256='b'*64,
        source_key=source['source_key'],span_hash=source['span_hash'])
    identity_family=digest(['global','general',identity])
    tokens=sorted(['source:'+source['source_key'],'span:'+source['span_hash'],'identity:'+identity_family])
    split_family=digest(tokens)
    case=dict(id=identity,document_id=identity,family=family,split='dev' if int(family[:2],16)<128 else 'test',
        question=entity+' / port',entity=entity,attribute='port',value=value,domain='general',project_scope='global',
        event_at='2026-01-01T00:00:00+00:00',expires_at=None,document_version='1',assertion_version='1',claim_version='1',
        sources=[source],history=[history],source_families=tokens,split_family=split_family,identity_family=identity_family)
    case['split']='dev' if int(split_family[:2],16)<128 else 'test'
    case['original_sha256']=digest({k:v for k,v in case.items() if k not in ('split','split_family')})
    return case


def _both_splits():
    cases=[_private_case(i) for i in range(32)]
    return [next(c for c in cases if c['split']==split) for split in ('dev','test')]


def _mock_export(tmp_path,monkeypatch,cases):
    from contextlib import contextmanager
    from agentic_rag import db
    from agentic_rag.benchmark import corrections
    @contextmanager
    def snapshot(cfg):
        yield object(),'2026-10-04T00:00:00+00:00',[p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name<='018_entity_identities.sql']
    monkeypatch.setattr(corrections,'_reader_snapshot',snapshot)
    monkeypatch.setattr(corrections,'_collect',lambda *a,**k:(cases,{'families_seen':len(cases),'withheld_families':0,'limited':False}))
    path=tmp_path/'labels.json'
    corrections.export_confirmed_corrections(Config(),domain='general',scope='global',output_path=path)
    return path


def test_private_candidate_existing_path_rejects_before_database(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from agentic_rag.benchmark import corrections
    path=_mock_export(tmp_path,monkeypatch,_both_splits())
    output=tmp_path/'result.json';candidate=tmp_path/'result.json.candidate.json'
    candidate.write_text('existing sealed candidate');candidate.chmod(0o600)
    @contextmanager
    def forbidden(cfg):
        pytest.fail('existing candidate reached database')
        yield
    monkeypatch.setattr(corrections,'_reader_snapshot',forbidden)
    with pytest.raises(ValueError,match='exist'):
        corrections.evaluate_export(Config(),export_path=path,output_path=output)
    assert candidate.read_text()=='existing sealed candidate'


def test_private_selection_uses_dev_only_and_seals_before_heldout(tmp_path,monkeypatch):
    from agentic_rag.benchmark import corrections
    cases=_both_splits();path=_mock_export(tmp_path,monkeypatch,cases)
    def score(conn,cfg,case,at,profile):
        if case['split']=='test':
            assert (tmp_path/'result.json.candidate.json').is_file()
            # Deliberately opposite held-out performance must not change selection.
            supported=profile=='fts'
        else:supported=profile=='entity'
        return dict(id=case['id'],family=case['family'],split_family=case['split_family'],split=case['split'],
            supported=supported,miss=not supported,stale=0,wrong_scope=0,error=None,context_chars=30)
    monkeypatch.setattr(corrections,'_score_case',score)
    result=corrections.evaluate_export(Config(),export_path=path,output_path=tmp_path/'result.json')
    assert result['optimization']['chosen']=='entity'
    assert result['optimization']['dev']['entity']['supported']==1
    assert result['optimization']['heldout']['supported']==0 and result['optimization']['heldout']['misses']==1
    assert result['optimization']['heldout_evaluations']==1
    assert (tmp_path/'result.json.candidate.json').stat().st_mode & 0o777==0o600


def test_fts_private_route_uses_literal_scope_and_no_inference_seams(monkeypatch):
    from agentic_rag import embed,llm,neural_rerank
    from agentic_rag.benchmark import corrections
    for module,name in ((embed,'embed_texts'),(llm,'run_structured'),(neural_rerank,'order')):
        monkeypatch.setattr(module,name,lambda *a,**k:pytest.fail('private inference invoked'))
    class Reader:
        def execute(self,statement,args):
            assert 'NULL' in statement and 'hybrid_search_temporal' in statement
            assert args==('Orion / port','general',['/synthetic/corrections/a'],'2026-10-04T00:00:00+00:00')
            return self
        def fetchall(self):return []
    case=_private_case();case['project_scope']='/synthetic/corrections/a'
    result=corrections._fts_facts(Reader(),case,'2026-10-04T00:00:00+00:00')
    assert result['facts']==[] and result['project_scope']=='/synthetic/corrections/a'


def test_export_rejects_broad_scope_before_database(tmp_path, monkeypatch):
    from agentic_rag.benchmark import corrections
    monkeypatch.setattr(corrections.db, 'connect', lambda *a, **k: pytest.fail('database accessed'))
    with pytest.raises(ValueError, match='exact'):
        corrections.export_confirmed_corrections(Config(), domain='general', scope='all',
            output_path=tmp_path/'private.json')


def test_private_file_is_new_and_private_and_rejects_git_and_symlinks(tmp_path):
    from agentic_rag.benchmark import corrections
    path=tmp_path/'private'/'labels.json'
    corrections._write_private(path, {'kind':'private-confirmed-corrections'})
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match='exist'):
        corrections._write_private(path, {'replacement':True})
    assert json.loads(path.read_text()) == {'kind':'private-confirmed-corrections'}
    link=tmp_path/'linked'; link.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        corrections._write_private(link/'other.json', {})
    repo=tmp_path/'other-repository'; repo.mkdir(); (repo/'.git').mkdir()
    with pytest.raises(ValueError, match='Git'):
        corrections._write_private(repo/'private.json', {})


def test_private_artifact_rejects_secret_or_redacted_labels(tmp_path):
    from agentic_rag.benchmark import corrections
    for text in ('[REDACTED]', 'api_key=publicfixture123456789'):
        with pytest.raises(ValueError, match='secret|redacted'):
            corrections._write_private(tmp_path/'blocked.json', {'value':text})
    assert not (tmp_path/'blocked.json').exists()


def test_credential_attribute_is_withheld_even_for_unrecognizable_value(tmp_path):
    from agentic_rag.benchmark import corrections
    with pytest.raises(ValueError,match='secret'):
        corrections._write_private(tmp_path/'blocked.json',{'entity':'Orion','attribute':'password','value':'shortfixture'})
    assert not (tmp_path/'blocked.json').exists()


@pytest.mark.parametrize('limit', [True,0,33,-1])
def test_unsafe_export_limit_is_rejected_before_database(tmp_path,monkeypatch,limit):
    from agentic_rag.benchmark import corrections
    monkeypatch.setattr(corrections.db,'connect',lambda *a,**k:pytest.fail('database accessed'))
    with pytest.raises(ValueError,match='limit'):
        corrections.export_confirmed_corrections(Config(),domain='general',scope='global',limit=limit,output_path=tmp_path/'labels.json')


def test_private_evaluation_rejects_synthetic_and_bad_hash_before_database(tmp_path, monkeypatch):
    from agentic_rag.benchmark import corrections
    monkeypatch.setattr(corrections.db, 'connect', lambda *a, **k: pytest.fail('database accessed'))
    for data in ({'version':1,'synthetic':True,'kind':'private-confirmed-corrections'},
                 {'version':1,'synthetic':False,'kind':'private-confirmed-corrections','artifact_sha256':'0'*64}):
        path=tmp_path/'input.json'; path.write_text(json.dumps(data)); path.chmod(0o600)
        with pytest.raises(ValueError):
            corrections.evaluate_export(Config(), export_path=path, output_path=tmp_path/'result.json')


def test_zero_case_export_and_evaluation_are_local_and_counted(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from agentic_rag.benchmark import corrections
    @contextmanager
    def snapshot(cfg):
        from agentic_rag import db
        yield object(), '2026-10-04T00:00:00+00:00', [p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name <= '018_entity_identities.sql']
    monkeypatch.setattr(corrections, '_reader_snapshot', snapshot)
    monkeypatch.setattr(corrections, '_collect', lambda *a, **k: ([], {'families_seen':0,'withheld_families':0,'limited':False}))
    export=tmp_path/'labels.json'; report=tmp_path/'results.json'
    summary=corrections.export_confirmed_corrections(Config(), domain='general', scope='global', output_path=export)
    assert summary['cases']==0 and summary['provider_calls']==0
    data=json.loads(export.read_text())
    assert data['synthetic'] is False and data['kind']=='private-confirmed-corrections'
    result=corrections.evaluate_export(Config(), export_path=export, output_path=report)
    assert result['cases']==0 and result['misses']==0 and result['supported']==0
    assert result['accuracy'] is None and result['provider_calls']==0


@pytest.mark.parametrize('change', ['extra_field','missing_time','bad_revision','bad_schema'])
def test_resealed_invalid_private_format_is_rejected_before_database(tmp_path, monkeypatch, change):
    from contextlib import contextmanager
    from agentic_rag.benchmark import corrections
    from agentic_rag import db
    @contextmanager
    def snapshot(cfg):
        yield object(), '2026-10-04T00:00:00+00:00', [p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name <= '018_entity_identities.sql']
    monkeypatch.setattr(corrections,'_reader_snapshot',snapshot)
    monkeypatch.setattr(corrections,'_collect',lambda *a,**k:([],{'families_seen':0,'withheld_families':0,'limited':False}))
    path=tmp_path/'labels.json'
    corrections.export_confirmed_corrections(Config(),domain='general',scope='global',output_path=path)
    data=json.loads(path.read_text())
    if change=='extra_field':data['arbitrary_private_metadata']='unapproved'
    if change=='missing_time':data['as_of']=None
    if change=='bad_revision':data['source_revision']='not-a-revision'
    if change=='bad_schema':data['source_schema']=[]
    data['artifact_sha256']=corrections._hash({k:v for k,v in data.items() if k!='artifact_sha256'})
    path.write_text(json.dumps(data))
    @contextmanager
    def forbidden(cfg):
        pytest.fail('invalid private data reached database')
        yield
    monkeypatch.setattr(corrections,'_reader_snapshot',forbidden)
    with pytest.raises(ValueError):
        corrections.evaluate_export(Config(),export_path=path,output_path=tmp_path/'results.json')


@pytest.mark.parametrize('fault',['split','scope','source_key','extra'])
def test_resealed_case_cannot_change_family_scope_or_original_source(tmp_path,monkeypatch,fault):
    from contextlib import contextmanager
    from agentic_rag import db
    from agentic_rag.benchmark import corrections
    @contextmanager
    def snapshot(cfg):
        yield object(),'2026-10-04T00:00:00+00:00',[p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name<='018_entity_identities.sql']
    monkeypatch.setattr(corrections,'_reader_snapshot',snapshot)
    monkeypatch.setattr(corrections,'_collect',lambda *a,**k:([_private_case()],{'families_seen':1,'withheld_families':0,'limited':False}))
    path=tmp_path/'labels.json'
    corrections.export_confirmed_corrections(Config(),domain='general',scope='global',output_path=path)
    data=json.loads(path.read_text());case=data['cases'][0]
    if fault=='split':case['split']='test' if case['split']=='dev' else 'dev'
    if fault=='scope':case['project_scope']='/foreign'
    if fault=='source_key':
        source=case['sources'][0];source['source_key']='0'*64
        source['original_sha256']=corrections._hash({k:v for k,v in source.items() if k!='original_sha256'})
    if fault=='extra':case['unapproved']='metadata'
    case['original_sha256']=corrections._case_hash(case)
    data['artifact_sha256']=corrections._hash({k:v for k,v in data.items() if k!='artifact_sha256'})
    path.write_text(json.dumps(data))
    @contextmanager
    def forbidden(cfg):
        pytest.fail('invalid case reached database')
        yield
    monkeypatch.setattr(corrections,'_reader_snapshot',forbidden)
    with pytest.raises(ValueError):corrections.evaluate_export(Config(),export_path=path,output_path=tmp_path/'result.json')


def test_evaluation_unavailable_case_remains_in_denominator(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from agentic_rag import db
    from agentic_rag.benchmark import corrections
    @contextmanager
    def snapshot(cfg):
        yield object(),'2026-10-04T00:00:00+00:00',[p.name for p in sorted(db.SQL_DIR.glob('*.sql')) if p.name<='018_entity_identities.sql']
    monkeypatch.setattr(corrections,'_reader_snapshot',snapshot)
    monkeypatch.setattr(corrections,'_collect',lambda *a,**k:([_private_case()],{'families_seen':1,'withheld_families':0,'limited':False}))
    path=tmp_path/'labels.json'
    corrections.export_confirmed_corrections(Config(),domain='general',scope='global',output_path=path)
    monkeypatch.setattr(corrections.entities,'read',lambda *a,**k:dict(status='unavailable',domain='general',project_scope='global',facts=[]))
    result=corrections.evaluate_export(Config(),export_path=path,output_path=tmp_path/'result.json')
    assert result['cases']==1 and result['misses']==1 and result['failed_cases']==1 and result['accuracy']==0


def _fact(conn, cfg, value, when, *, relation='replacement', domain='general', project='/synthetic/corrections/a', complete=True):
    from agentic_rag import store
    result=store.save_assertion(conn,cfg,entity='Orion',attribute='port',value=value,
        event_at=when,relation=relation,domain=domain,project=project,
        evidence={'source_id':value+when+domain,'role':'user','quote':'Orion port is now '+value,
                  'complete':complete})
    store.review_claim(conn,result.doc_id,state='confirmed',reason='Explicit original user correction')
    return result


def test_original_confirmed_correction_is_exported_and_locally_supported(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store, domains, embed, llm, neural_rerank
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn)
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    old=_fact(conn,cfg,'7000','2026-01-01T00:00:00Z',relation='assertion')
    new=_fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    for module,name in ((embed,'embed_texts'),(llm,'run_structured'),(neural_rerank,'order')):
        monkeypatch.setattr(module,name,lambda *a,**k:pytest.fail('private data reached a provider'))
    path=tmp_path/'labels.json'
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=path)
    assert result['cases']==1
    case=json.loads(path.read_text())['cases'][0]
    assert case['value']=='8000' and case['document_id']==new.doc_id
    assert old.doc_id in [x['document_id'] for x in case['history']]
    assert case['sources'][0]['quote']=='Orion port is now 8000'
    evaluated=corrections.evaluate_export(cfg,export_path=path,output_path=tmp_path/'result.json')
    assert evaluated['cases']==1 and evaluated['supported']==1 and evaluated['misses']==0


@pytest.mark.parametrize('fault',['withdrawn','incomplete','unreviewed','expired','later_withdrawn'])
def test_untrusted_or_superseded_originals_never_revive(conn,cfg,tmp_path,monkeypatch,fault):
    from agentic_rag import store, evidence, domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    _fact(conn,cfg,'7000','2026-01-01T00:00:00Z',relation='assertion')
    new=_fact(conn,cfg,'8000','2026-02-01T00:00:00Z',complete=fault!='incomplete')
    if fault=='withdrawn':store.set_source_state(conn,evidence.sources(conn,new.doc_id)[0]['source_key'],state='removed',reason='Withdraw original')
    if fault=='unreviewed':store.review_claim(conn,new.doc_id,state='unreviewed',reason='Withdraw confirmation')
    if fault=='expired':
        # Owned fault fixture; production immutable gateway stays unchanged.
        conn.execute("UPDATE fact_assertions SET expires_at='2026-03-01T00:00:00Z' WHERE document_id=%s",(new.doc_id,));conn.commit()
    if fault=='later_withdrawn':
        later=_fact(conn,cfg,'9000','2026-03-01T00:00:00Z')
        store.set_source_state(conn,evidence.sources(conn,later.doc_id)[0]['source_key'],state='removed',reason='Withdraw later original')
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=tmp_path/'labels.json')
    assert result['cases']==0


def test_export_exact_domain_does_not_include_foreign_replacement(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);domains.add_domain(conn,'infrastructure')
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    _fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    _fact(conn,cfg,'9000','2026-03-01T00:00:00Z',domain='infrastructure')
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=tmp_path/'labels.json')
    assert result['cases']==1 and json.loads((tmp_path/'labels.json').read_text())['cases'][0]['value']=='8000'


def test_original_withdrawal_cannot_inherit_later_reviewed_attachment(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,evidence,domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    new=_fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    original=evidence.sources(conn,new.doc_id)[0]['source_key']
    _fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    evidence.attach(conn,new.doc_id,[{'namespace':'later','source_id':'later-confirmed',
        'role':'user','quote':'Orion port is now 8000','complete':True}],actor='test')
    store.review_claim(conn,new.doc_id,state='confirmed',reason='Review all currently active spans')
    store.set_source_state(conn,original,state='removed',reason='Original correction withdrawn')
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=tmp_path/'labels.json')
    assert result['cases']==0 and result['withheld_families']==1


def test_complete_family_bound_withholds_instead_of_truncating(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    _fact(conn,cfg,'7000','2026-01-01T00:00:00Z',relation='assertion')
    _fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    monkeypatch.setattr(corrections,'MAX_HISTORY',1)
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=tmp_path/'labels.json')
    assert result['cases']==0 and result['withheld_families']==1


def test_frozen_export_counts_withdrawn_label_as_miss_without_provider(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,domains,evidence,embed
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    new=_fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    path=tmp_path/'labels.json'
    corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=path)
    store.set_source_state(conn,evidence.sources(conn,new.doc_id)[0]['source_key'],state='removed',reason='Withdraw source')
    monkeypatch.setattr(embed,'embed_texts',lambda *a,**k:pytest.fail('private provider call'))
    result=corrections.evaluate_export(cfg,export_path=path,output_path=tmp_path/'results.json')
    assert result['cases']==1 and result['misses']==1 and result['supported']==0


def test_exact_project_excludes_global_and_other_project(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    _fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    _fact(conn,cfg,'9000','2026-03-01T00:00:00Z',project='/synthetic/corrections/b')
    global_fact=store.save_assertion(conn,cfg,entity='Orion',attribute='port',value='10000',event_at='2026-04-01T00:00:00Z',
        relation='replacement',scope='global',domain='general',evidence={'source_id':'global','role':'user','quote':'Orion port 10000'})
    store.review_claim(conn,global_fact.doc_id,state='confirmed',reason='Explicit global correction')
    path=tmp_path/'labels.json'
    result=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=path)
    assert result['cases']==1 and json.loads(path.read_text())['cases'][0]['value']=='8000'


def test_confirmed_alias_star_with_independent_sources_is_one_split_family(conn,cfg,tmp_path,monkeypatch):
    from agentic_rag import store,domains
    from agentic_rag.benchmark import corrections
    domains.seed_defaults(conn);monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    _fact(conn,cfg,'8000','2026-02-01T00:00:00Z')
    other=store.save_assertion(conn,cfg,entity='Old Orion',attribute='status',value='running',
        event_at='2026-03-01T00:00:00Z',relation='replacement',domain='general',project='/synthetic/corrections/a',
        evidence={'source_id':'independent-status','role':'user','quote':'Old Orion status is now running'})
    store.review_claim(conn,other.doc_id,state='confirmed',reason='Original user confirmed status')
    store.save_entity_alias(conn,cfg,alias='Old Orion',target='Orion',domain='general',project='/synthetic/corrections/a',
        effective_at='2026-04-01T00:00:00Z',confirm=True,evidence={'namespace':'operator','source_id':'explicit-alias',
            'role':'user','quote':'Old Orion is the same system as Orion','complete':True})
    path=tmp_path/'labels.json'
    summary=corrections.export_confirmed_corrections(cfg,domain='general',project='/synthetic/corrections/a',output_path=path)
    cases=json.loads(path.read_text())['cases']
    assert summary['cases']==2 and len({c['family'] for c in cases})==2
    assert len({c['identity_family'] for c in cases})==1 and len({c['split_family'] for c in cases})==1
    assert len({c['split'] for c in cases})==1
