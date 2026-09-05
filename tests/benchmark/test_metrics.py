import pytest


def test_rank_metrics_use_distinct_evidence_and_count_misses():
    from agentic_rag.benchmark.metrics import rank_metrics
    got = rank_metrics(['a','a','wrong','b'], ['a','b'])
    assert got == {'recall_at_5':1.0,'recall_at_10':1.0,'mrr':1.0}
    assert rank_metrics(['wrong'],['a']) == {'recall_at_5':0.0,'recall_at_10':0.0,'mrr':0.0}
    assert rank_metrics([],[]) == {'recall_at_5':None,'recall_at_10':None,'mrr':None}


def test_answer_scoring_distinguishes_abstention_wrong_and_stale():
    from agentic_rag.benchmark.metrics import answer_metrics
    q={'answers':['7712'],'unanswerable':False,'stale_answers':['7701']}
    assert answer_metrics('Port is 7712.',False,q)['correct'] is True
    assert answer_metrics('77120',False,q)['correct'] is False
    assert answer_metrics('7701',False,q)['stale'] is True
    assert answer_metrics('',True,q)['correct'] is False
    assert answer_metrics('',True,{'answers':[],'unanswerable':True,'stale_answers':[]})['correct'] is True
    assert answer_metrics('7712 or 7701',False,q)['correct'] is False


def test_missing_ingestion_and_failed_query_stay_in_denominator():
    from agentic_rag.benchmark.metrics import summarize
    rows=[{'query_id':'a','category':'exact','split':'test','unanswerable':False,
           'ranking':{'recall_at_5':1.0,'recall_at_10':1.0,'mrr':1.0},'error':None,
           'answer':{'correct':True,'abstained':False,'stale':False},'latency_ms':5,'context_chars':100},
          {'query_id':'b','category':'exact','split':'test','unanswerable':False,
           'ranking':{'recall_at_5':0.0,'recall_at_10':0.0,'mrr':0.0},'error':'ingest failed',
           'answer':{'correct':False,'abstained':False,'stale':False},'latency_ms':7,'context_chars':0}]
    got=summarize(rows)
    assert got['queries']==2 and got['failed_queries']==1
    assert got['recall_at_5']==0.5 and got['answer_accuracy']==0.5


def test_corpus_rejects_missing_evidence_and_leaking_split():
    from agentic_rag.benchmark.corpus import validate
    corpus={'version':1,'synthetic':True,'documents':[{'id':'a','title':'a','body':'body','project':'p'}],
            'queries':[{'id':'q','query':'question','expected_ids':['missing'],'answers':['yes'],
                        'unanswerable':False,'stale_answers':[],'split':'test','category':'exact','language':'en'}]}
    with pytest.raises(ValueError,match='evidence'):
        validate(corpus)
    corpus['queries'][0]['expected_ids']=['a']
    corpus['queries'][0]['split']='unknown'
    with pytest.raises(ValueError,match='split'):
        validate(corpus)


def test_cleanup_refuses_canonical_names_before_connecting():
    from agentic_rag.benchmark.database import validate_name
    for name in ['agentic_rag','postgres','agentic_rag_test','rag_bench_','rag_bench_abc;DROP']:
        with pytest.raises(ValueError):
            validate_name(name)
    validate_name('rag_bench_'+'a'*24)
