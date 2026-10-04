"""Independent labels and pure optimizer guards: never connect to a service."""
from copy import deepcopy
import json

import pytest


def fixture_corpus():
    documents, queries = [], []
    for split, name, value in [('dev', 'Zebra', '8172'), ('test', 'Otter', '6193')]:
        documents.append(dict(id=name, title=name + ': checksum', body=name + ' checksum is ' + value + '.',
            project='/synthetic/' + name.lower(), domain='general', actor='user-a', family=name,
            split=split, assertion=dict(entity=name, attribute='checksum', value=value,
                event_at='2026-04-01T00:00:00Z'),
            evidence=dict(source_id=name, role='user', quote=name + ' checksum is ' + value + '.', complete=True)))
        queries.append(dict(id=name+'-en', family=name, split=split, language='en', category='exact',
            query=name+' checksum', domain='general', project='/synthetic/' + name.lower(),
            entity=name, attribute='checksum', as_of='2026-04-02T00:00:00Z',
            expected_ids=[name], answers=[value], unanswerable=False))
    return dict(version=1, synthetic=True, documents=documents, queries=queries)


def test_copied_source_rejected_before_database_or_output(tmp_path, monkeypatch):
    # Renaming a copied source/family must not move it into held-out data.
    from agentic_rag.benchmark import optimization
    from agentic_rag.config import Config
    corpus = fixture_corpus()
    corpus['documents'][1]['body'] = ' Zebra  checksum is 8172. '
    path = tmp_path/'corpus.json'; path.write_text(json.dumps(corpus))
    monkeypatch.setattr(optimization, 'isolated_database', lambda *a: pytest.fail('no database before validation'))
    with pytest.raises(ValueError, match='copied|leak'):
        optimization.run(Config(), output=tmp_path/'report', corpus_path=path)
    assert not (tmp_path/'report').exists()


def test_source_family_and_expected_evidence_cannot_cross_split():
    from agentic_rag.benchmark.optimization import validate
    corpus = fixture_corpus(); corpus['documents'][1]['family'] = 'Zebra'
    with pytest.raises(ValueError, match='family|leak'): validate(corpus)
    corpus = fixture_corpus(); corpus['queries'][1]['expected_ids'] = ['Zebra']
    with pytest.raises(ValueError, match='split|held|evidence'): validate(corpus)


@pytest.mark.parametrize('change', ['secret', 'assistant', 'missing_time', 'missing_attribute'])
def test_unsafe_fixture_rejected(change):
    from agentic_rag.benchmark.optimization import validate
    corpus = fixture_corpus()
    if change == 'secret': corpus['documents'][0]['body'] = 'api_key=sk-' + 'a'*40
    if change == 'assistant': corpus['documents'][0]['evidence']['role'] = 'assistant'
    if change == 'missing_time': corpus['queries'][0].pop('as_of')
    if change == 'missing_attribute': corpus['queries'][0].pop('attribute')
    with pytest.raises(ValueError): validate(corpus)


def test_answer_value_with_wrong_original_source_is_a_miss():
    from agentic_rag.benchmark.optimization import score
    query = fixture_corpus()['queries'][0]
    packet = dict(answers=[dict(value='8172', source_id='Otter', source_checked=True,
                               citation='original#chunk:0-4')], source_ids=['Otter'],
                  context='8172', wrong_scope=0, error=None)
    result = score(query, packet)
    assert result['extractive_correct'] is False
    assert result['evidence_recall'] == 0
    assert result['missing_expected_ids'] == ['Zebra']


def test_extra_wrong_answer_or_unchecked_source_cannot_receive_credit():
    from agentic_rag.benchmark.optimization import score
    query = fixture_corpus()['queries'][0]
    packet = dict(answers=[dict(value='8172', source_id='Zebra', source_checked=True, citation='a'),
                           dict(value='wrong', source_id='Zebra', source_checked=True, citation='b')],
                  source_ids=['Zebra'], context='8172 wrong', wrong_scope=0, error=None)
    assert not score(query, packet)['extractive_correct']
    packet['answers'] = [dict(value='8172', source_id='Zebra', source_checked=False, citation='a')]
    assert not score(query, packet)['extractive_correct']


def test_failed_negative_is_not_successful_abstention():
    from agentic_rag.benchmark.optimization import score
    query = dict(fixture_corpus()['queries'][0], unanswerable=True, answers=[], expected_ids=[])
    packet = dict(answers=[], source_ids=[], context='', wrong_scope=0, error='query failed')
    assert score(query, packet)['extractive_correct'] is False


def test_failures_remain_in_summary_and_repeats_do_not_inflate_families():
    from agentic_rag.benchmark.optimization import summarize
    rows = [dict(query_id='a', family='same', unanswerable=False, extractive_correct=True,
                 evidence_recall=1., abstained=False, error=None, context_chars=20,
                 context_tokens_estimate=5, wrong_scope=0, stale_sources=0,
                 irrelevant_candidate_exposure=False, raw_latency_ms=[1., 2., 3.]),
            dict(query_id='b', family='same', unanswerable=False, extractive_correct=False,
                 evidence_recall=0., abstained=True, error='indexing failed', context_chars=0,
                 context_tokens_estimate=0, wrong_scope=0, stale_sources=0,
                 irrelevant_candidate_exposure=False, raw_latency_ms=[1., 2., 3.])]
    result = summarize(rows)
    assert result['queries'] == result['extractive_denominator'] == 2
    assert result['extractive_accuracy'] == result['evidence_recall'] == .5
    assert result['failed_queries'] == 1
    assert result['independent_families'] == 1
    assert result['extractive_accuracy_family_bootstrap_95'] is None


def test_selection_is_dev_only_and_safety_first():
    from agentic_rag.benchmark.optimization import select
    summaries = [dict(profile=dict(id='ordinary', route='search', title_weight=0),
                      summary=dict(wrong_scope=0, stale_sources=0, extractive_accuracy=.5,
                                   evidence_recall=.5, latency_ms_p95=4.)),
                 dict(profile=dict(id='unsafe', route='entity', title_weight=1),
                      summary=dict(wrong_scope=1, stale_sources=0, extractive_accuracy=1.,
                                   evidence_recall=1., latency_ms_p95=1.))]
    assert select(summaries)['id'] == 'ordinary'
    with pytest.raises(ValueError, match='dev'):
        select(summaries, split='test')


@pytest.mark.parametrize('context,repeats', [(999, 20), (12001, 20), (4000, 0), (4000, 31), (4000, True)])
def test_bad_budgets_reject_before_database(tmp_path, monkeypatch, context, repeats):
    from agentic_rag.benchmark import optimization
    from agentic_rag.config import Config
    monkeypatch.setattr(optimization, 'isolated_database', lambda *a: pytest.fail('no DB'))
    with pytest.raises(ValueError):
        optimization.run(Config(), output=tmp_path/'report', context_chars=context, repeats=repeats)


def test_ranker_preserves_all_original_candidates():
    from types import SimpleNamespace
    from agentic_rag.benchmark.optimization import rank
    hits = [SimpleNamespace(document_id='a', title='Other', score=.9),
            SimpleNamespace(document_id='b', title='Zebra checksum', score=.1)]
    ordered = rank('Zebra checksum', hits, title_weight=1)
    assert [h.document_id for h in ordered] == ['b', 'a']
    assert hits[0].document_id == 'a'


def test_sealed_candidate_rejects_mutation_and_overwrite(tmp_path):
    from agentic_rag.benchmark.optimization import seal, read_candidate
    payload = dict(version=1, profile=dict(id='search-title-0', route='search', title_weight=0),
                   split='dev', corpus_sha256='a'*64, source_sha256='b'*64, context_chars=4000)
    path = tmp_path/'candidate.json'; candidate = seal(payload, path)
    assert read_candidate(path) == candidate
    with pytest.raises(FileExistsError): seal(payload, path)
    changed = deepcopy(candidate); changed['profile']['route'] = 'entity'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='hash|seal'): read_candidate(path)


def test_renamed_translation_and_history_still_cannot_cross_split():
    from agentic_rag.benchmark.optimization import validate
    corpus = fixture_corpus()
    corpus['queries'][1].update(entity='Zebra', attribute='checksum', project='/synthetic/zebra',
                              expected_ids=[], answers=[], unanswerable=True, language='de')
    with pytest.raises(ValueError, match='translation|history'):
        validate(corpus)


def test_heldout_labels_cannot_change_selection_and_seal_precedes_evaluation(tmp_path, monkeypatch):
    # The external owned-database phase is replaced; orchestration/sealing stay real.
    from agentic_rag.benchmark import optimization
    from agentic_rag.benchmark import identity
    from agentic_rag.config import Config
    monkeypatch.setattr(identity, 'model_digest', lambda cfg: 'a'*64)
    selected, dev_hashes = [], []
    for number, answer in enumerate(['6193', 'checksum']):
        corpus = fixture_corpus(); corpus['queries'][1]['answers'] = [answer]
        path = tmp_path/f'corpus-{number}.json'; path.write_text(json.dumps(corpus))
        output = tmp_path/f'report-{number}'
        def phase(cfg, data, split, profiles, budget, repeats, progress, *, expected_model):
            assert expected_model['digest'] == 'a'*64
            if split == 'test':
                sealed = optimization.read_candidate(output/'candidate.json')
                assert sealed['profile']['route'] == 'entity'
                assert repeats == 2
                assert 'answers' not in optimization._request(data['queries'][1])
            else:
                assert repeats == 1
            reports = []
            for profile in profiles:
                summary = dict(wrong_scope=0, stale_sources=0, extractive_accuracy=float(profile['route']=='entity'),
                               evidence_recall=float(profile['route']=='entity'), queries=0,
                               latency_ms_p50=1., latency_ms_p95=1.)
                reports.append(dict(profile=dict(profile), summary=summary, rows=[]))
            return dict(split=split, profiles=reports, ingestion={}, cleanup='verified')
        monkeypatch.setattr(optimization, '_phase', phase)
        report = optimization.run(Config(), output=output, corpus_path=path, repeats=2)
        selected.append(report['candidate']['profile'])
        dev_hashes.append(report['candidate']['development_sha256'])
        assert report['metadata']['general_model_accuracy'] is None
        assert all((output/name).is_file() for name in ['candidate.json','dev-results.json','heldout-results.json','results.json','report.md'])
    assert selected == [dict(id='entity-title-0', route='entity', title_weight=0)]*2
    assert dev_hashes[0] == dev_hashes[1]


@pytest.mark.parametrize('extra', ['heldout_families', 'results', 'test_labels'])
def test_mining_metadata_cannot_smuggle_heldout_labels(extra):
    from agentic_rag.benchmark.optimization import _mining_metadata
    metadata = dict(version=1, public=True, synthetic=True, selection_split='dev',
        selected_prompt='correction-v1', selected_prompt_sha256='a'*64,
        prompt_sha256={'correction-v1':'a'*64}, source_revision='b'*40,
        development_families=['dev-a','dev-b'], profiles=[{'id':'correction-v1'}], development=[], production_applied=False)
    metadata[extra] = ['held-out-label']
    with pytest.raises(ValueError, match='metadata|fields|held|bounded'):
        _mining_metadata(metadata)


def test_owned_gateway_alias_route_and_original_citations(cfg, tmp_path, monkeypatch):
    """DB integration: root executes; the worker never runs this test."""
    from agentic_rag import embedding_reuse, search, store
    from agentic_rag.benchmark import identity
    from agentic_rag.benchmark.optimization import run
    monkeypatch.setattr(identity, 'model_digest', lambda cfg: 'a'*64)
    monkeypatch.setattr(embedding_reuse, 'model_digest', lambda cfg: None)
    loader = lambda texts, cfg: [[.01]*1024 for _ in texts]
    monkeypatch.setattr(store, 'try_embed_texts', loader)
    monkeypatch.setattr(search, 'try_embed_texts', loader)
    corpus = fixture_corpus()
    corpus['documents'].append(dict(id='alias-zebra', title='OldZebra became Zebra',
        body='OldZebra is another name for Zebra.', project='/synthetic/zebra', domain='general',
        actor='user-a', family='Zebra', split='dev',
        alias=dict(alias='OldZebra', target='Zebra', effective_at='2026-04-01T00:00:00Z')))
    corpus['queries'][0].update(entity='OldZebra', query='OldZebra checksum')
    path = tmp_path/'corpus.json'; path.write_text(json.dumps(corpus))
    report = run(cfg, output=tmp_path/'report', corpus_path=path, repeats=2)
    assert report['candidate']['profile']['route'] == 'entity'
    assert report['failed_queries'] == 0
    assert report['cleanup'] == 'verified'
    assert report['heldout']['ingestion']['source_denominator'] == 1
    for profile in report['heldout']['profiles']:
        assert profile['summary']['extractive_accuracy'] == 1
        assert profile['summary']['wrong_scope'] == 0
        row = profile['rows'][0]
        assert row['expected_answers'] == ['6193']
        assert row['answers'][0]['value'] == '6193'
        assert row['answers'][0]['source_checked'] is True
        assert row['citations'][0]['source_id'] == 'Otter'
        assert '# ' in row['citations'][0]['text']
        assert len(row['raw_latency_ms']) == 2


def test_unknown_model_rejected_before_owned_phase(tmp_path, monkeypatch):
    from agentic_rag.benchmark import identity, optimization
    from agentic_rag.config import Config
    monkeypatch.setattr(identity, 'model_digest', lambda cfg: None)
    monkeypatch.setattr(optimization, '_phase', lambda *a, **k: pytest.fail('must reject before DB phase'))
    path = tmp_path/'corpus.json'; path.write_text(json.dumps(fixture_corpus()))
    with pytest.raises(ValueError, match='identity|immutable|model'):
        optimization.run(Config(), output=tmp_path/'report', corpus_path=path)
    assert not (tmp_path/'report').exists()


@pytest.mark.parametrize('stage', ['ingestion', 'query'])
def test_model_drift_aborts_comparison_instead_of_counting_a_query_miss(tmp_path, monkeypatch, stage):
    """Only SQL/inference boundaries are fake; run, ingestion and phase stay real."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from agentic_rag.benchmark import identity, optimization
    from agentic_rag.config import Config
    state = {'digest':'a'*64}
    monkeypatch.setattr(identity, 'model_digest', lambda cfg: state['digest'])
    @contextmanager
    def owned(cfg):
        yield cfg
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, *args): return self
        def fetchall(self): return [{'document_id':'doc-Zebra','n':1,'embedded':1}]
        def commit(self): pass
        def rollback(self): pass
    monkeypatch.setattr(optimization, 'isolated_database', owned)
    monkeypatch.setattr(optimization.db, 'connect', lambda *a, **k: Connection())
    monkeypatch.setattr(optimization.domains, 'add_domain', lambda *a, **k: None)
    def save(*args, **kwargs):
        if stage == 'ingestion': state['digest'] = 'b'*64
        return SimpleNamespace(doc_id='doc-'+kwargs['entity'], disposition='accepted')
    monkeypatch.setattr(optimization.store, 'save_assertion', save)
    monkeypatch.setattr(optimization.store, 'review_claim', lambda *a, **k: None)
    def execute(*args, **kwargs):
        if stage == 'query': state['digest'] = 'b'*64
        return dict(answers=[], source_ids=[], retrieved_source_ids=[], context='', wrong_scope=0,
                    error=None, warnings=[], citations=[], route='search')
    monkeypatch.setattr(optimization, '_execute', execute)
    path = tmp_path/'corpus.json'; path.write_text(json.dumps(fixture_corpus()))
    with pytest.raises(ValueError, match='model identity changed'):
        optimization.run(Config(), output=tmp_path/'report', corpus_path=path, repeats=2)
    assert not (tmp_path/'report/candidate.json').exists()
