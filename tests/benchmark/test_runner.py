from dataclasses import replace
import json

from agentic_rag.benchmark.corpus import load


def tiny_corpus(tmp_path):
    corpus={'version':1,'synthetic':True,
            'documents':[{'id':'a','title':'Zebra control','body':'Zebra checksum is 8172.','project':'zebra'}],
            'queries':[{'id':'positive','query':'Zebra checksum','expected_ids':['a'],'answers':['8172'],
                        'unanswerable':False,'stale_answers':[],'split':'test','category':'exact','language':'en'},
                       {'id':'negative','query':'absentwhollyunknown','expected_ids':[],'answers':[],
                        'unanswerable':True,'stale_answers':[],'split':'test','category':'unanswerable','language':'en'}]}
    path=tmp_path/'corpus.json';path.write_text(json.dumps(corpus));return path


def test_real_gateway_search_reports_and_cleans_owned_database(cfg,tmp_path):
    from agentic_rag.benchmark.runner import run
    report=run(cfg,corpus_path=tiny_corpus(tmp_path),output=tmp_path/'report',search_mode='fts')
    assert report['summary']['queries']==2
    assert report['summary']['recall_at_5']==1.0
    assert report['summary']['answer_accuracy'] is None
    assert report['cleanup']=='verified'
    assert report['ingestion']['failed_sources']==[]
    assert (tmp_path/'report/results.json').is_file()
    assert (tmp_path/'report/report.md').is_file()
    assert report['rows'][0]['context_chars'] <= report['config']['context_chars']
    assert report['metadata']['corpus_sha256'] == load(tiny_corpus(tmp_path))[1]
    assert report['metadata']['corpus_sha256'] == load(tmp_path/'report/corpus.json')[1]


def test_mining_mode_uses_real_gateway_and_grounded_model_boundary(cfg,tmp_path,monkeypatch):
    from agentic_rag import mining
    from agentic_rag.benchmark.runner import run
    calls=[]
    def model(prompt,*a,**k):
        calls.append(prompt)
        return {'memories':[{'title':'Zebra remembered','body':'Zebra checksum is 8172.',
                            'domain':'general','edges':[]}],
                'lessons':[],'signals':[],'contradictions':[],'pin_suggestions':[],
                'contradictions_with_pins':[],'domain_proposals':[]}
    monkeypatch.setattr(mining,'run_structured',model)
    report=run(cfg,corpus_path=tiny_corpus(tmp_path),output=tmp_path/'mining',
               search_mode='fts',mode='end-to-end')
    assert len(calls)==1 and 'Zebra checksum' in calls[0]
    assert report['summary']['recall_at_10']==1
    assert report['ingestion']['indexed_sources']==1
    assert report['metadata']['mode']=='end-to-end'


def test_context_limit_and_comparison_guard(cfg,tmp_path):
    from agentic_rag.benchmark.runner import run,compare
    report=run(cfg,corpus_path=tiny_corpus(tmp_path),output=tmp_path/'cap',
               search_mode='fts',context_chars=32)
    assert all(row['context_chars']<=32 for row in report['rows'])
    changed={**report,'config':{**report['config'],'context_chars':33}}
    import pytest
    with pytest.raises(ValueError,match='budget'):
        compare(report,changed)


def test_corpus_identity_cannot_escape_temporary_sources(cfg,tmp_path,monkeypatch):
    from agentic_rag import mining
    from agentic_rag.benchmark.runner import run
    from pathlib import Path
    corpus_path = tiny_corpus(tmp_path)
    corpus = json.loads(corpus_path.read_text())
    escaped = str(tmp_path/'must-not-overwrite')
    corpus['documents'][0]['id'] = escaped
    corpus['queries'][0]['expected_ids'] = [escaped]
    corpus_path.write_text(json.dumps(corpus))
    target = Path(escaped+'.jsonl')
    target.write_text('original content')
    observed = []
    def mine(*args, **kwargs):
        observed.append(Path(kwargs['transcript_path']))
        raise RuntimeError('model boundary intentionally stopped')
    monkeypatch.setattr(mining, 'mine_session', mine)
    report = run(cfg,corpus_path=corpus_path,output=tmp_path/'safe',
                 mode='end-to-end',search_mode='fts')
    assert target.read_text() == 'original content'
    assert observed and observed[0].name == 'source-1.jsonl'
    assert report['summary']['failed_queries'] == 1
    assert report['summary']['recall_at_5'] == 0
    assert report['cleanup'] == 'verified'


def test_database_is_gone_after_cli_success(cfg,tmp_path,monkeypatch,capsys):
    from agentic_rag import cli,db
    seen=[]
    original=db.connect
    def tracked(config,*args,**kwargs):
        seen.append(config.db_name)
        return original(config,*args,**kwargs)
    monkeypatch.setattr(db,'connect',tracked)
    monkeypatch.setattr(cli,'load_config',lambda:cfg)
    assert cli.main(['benchmark','run','--corpus',str(tiny_corpus(tmp_path)),
                     '--search-mode','fts','--output',str(tmp_path/'cli')]) == 0
    assert seen and all(name.startswith('rag_bench_') for name in seen)
    import psycopg
    with psycopg.connect(db.dsn(cfg,dbname='postgres')) as connection:
        assert connection.execute('SELECT datname FROM pg_database WHERE datname = ANY(%s)',
                                  (list(set(seen)),)).fetchall() == []
    assert 'Reports:' in capsys.readouterr().out


def test_scope_corpus_has_no_foreign_or_unknown_context(cfg,tmp_path):
    from pathlib import Path
    from agentic_rag.benchmark import corpus
    from agentic_rag.benchmark.runner import run
    report=run(cfg,corpus_path=Path(corpus.__file__).with_name('corpus-scope-v1.json'),
               output=tmp_path/'scope',search_mode='fts')
    assert report['summary']['recall_at_5']==1
    rows={r['query_id']:r for r in report['rows']}
    assert rows['alpha-en']['retrieved_source_ids']==['alpha']
    assert rows['beta-de']['retrieved_source_ids']==['beta']
    assert set(rows['all']['retrieved_source_ids'])=={'alpha','beta'}
    assert rows['unknown-hidden']['retrieved_source_ids']==[]
    assert rows['project-hidden-global']['retrieved_source_ids']==[]


def test_temporal_fixture_measures_prior_eligibility_and_current_history(cfg,tmp_path):
    from pathlib import Path
    from agentic_rag.benchmark.runner import run
    corpus=Path(__file__).parents[2]/'agentic_rag/benchmark/corpus-temporal-v1.json'
    before=run(cfg,corpus_path=corpus,output=tmp_path/'before',search_mode='fts',validity_baseline=True)
    after=run(cfg,corpus_path=corpus,output=tmp_path/'after',search_mode='fts')
    assert before['temporal']['stale_result_rate']>0
    assert after['temporal']['stale_result_rate']==0
    assert after['temporal']['current_recall_at_10']==1
    assert after['temporal']['historical_recall_at_10']==1
    assert after['provider']['model_calls_attempted']==0
    assert after['summary']['stale_answer_rate'] is None
