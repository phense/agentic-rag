"""Offline model failure scoring and corpus integrity; no provider or DB calls."""
import pytest

from agentic_rag.benchmark.corpus import load
from agentic_rag.benchmark.metrics import summarize
from agentic_rag.benchmark.runner import _model_stage


def test_answer_failure_is_counted_in_answer_and_judge_denominators(monkeypatch):
    from agentic_rag import llm
    def unavailable(*args, **kwargs):
        raise RuntimeError('synthetic provider failure')
    monkeypatch.setattr(llm, 'run_structured', unavailable)
    queries = [{'id': 'q', 'query': 'test', 'answers': ['yes']}]
    rows = [{'query_id': 'q', 'context': '', 'unanswerable': False, 'error': None,
             'ranking': {'recall_at_5': 0., 'recall_at_10': 0., 'mrr': 0.},
             'context_chars': 0, 'latency_ms': 0}]
    _model_stage(rows, queries, None, judge=False, tracked_runner=None)
    _model_stage(rows, queries, None, judge=True, tracked_runner=None)
    metrics = summarize(rows)
    assert metrics['answer_scored_queries'] == metrics['judge_scored_queries'] == 1
    assert metrics['answer_accuracy'] == metrics['judge_accuracy'] == 0
    assert metrics['failed_queries'] == 1


def test_versioned_corpus_has_bilingual_held_out_coverage():
    corpus, digest = load()
    assert len(digest) == 64
    assert len(corpus['queries']) >= 50
    for split in ['dev', 'test']:
        rows = [q for q in corpus['queries'] if q['split'] == split]
        assert {q['language'] for q in rows} == {'en', 'de'}
        assert any(q['unanswerable'] for q in rows)
    assert len({q['category'] for q in corpus['queries']}) >= 8


def test_cleanup_requires_matching_marker(monkeypatch):
    from types import SimpleNamespace
    from agentic_rag.benchmark import database
    class Connection:
        closed = False
        def execute(self, *args): return self
        def fetchone(self): return {'owner_id': 'different'}
        def close(self): self.closed = True
    connection = Connection()
    monkeypatch.setattr(database.db, 'connect', lambda *a, **k: connection)
    monkeypatch.setattr(database.psycopg, 'connect', lambda *a, **k: pytest.fail('must not DROP'))
    name = 'rag_bench_' + 'a' * 24
    with pytest.raises(ValueError, match='marker'):
        database.cleanup(SimpleNamespace(db_name=name), name, 'expected')
    assert connection.closed


@pytest.mark.parametrize('key', ['PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'])
def test_libpq_environment_cannot_redirect_benchmark(monkeypatch, key):
    from agentic_rag.config import Config
    from agentic_rag.benchmark import database
    monkeypatch.setenv(key, 'unexpected-target')
    monkeypatch.setattr(database.psycopg, 'connect', lambda *a, **k: pytest.fail('must reject before connecting'))
    with pytest.raises(ValueError, match='unset PGHOST'):
        with database.isolated_database(Config()):
            pytest.fail('must not create database')


def test_marker_failure_drops_only_just_created_database(monkeypatch):
    from agentic_rag.config import Config
    from agentic_rag.benchmark import database
    for key in ['PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE']:
        monkeypatch.delenv(key, raising=False)
    commands = []
    dsns = []
    class Admin:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, command): commands.append(command.as_string())
    def connect(dsn, **kwargs):
        dsns.append(dsn)
        return Admin()
    def fail_marker(*args, **kwargs): raise RuntimeError('cannot initialize marker')
    monkeypatch.setattr(database.psycopg, 'connect', connect)
    monkeypatch.setattr(database.db, 'connect', fail_marker)
    with pytest.raises(RuntimeError, match='marker'):
        with database.isolated_database(Config()): pass
    assert len(commands) == 2
    assert commands[0].startswith('CREATE DATABASE "rag_bench_')
    assert commands[1] == commands[0].replace('CREATE DATABASE', 'DROP DATABASE')
    assert dsns == ['dbname=postgres host=127.0.0.1']


@pytest.mark.parametrize('key,value', [('answers',['']), ('answers','yes'),
                                      ('expected_ids',[None]), ('stale_answers',[7])])
def test_invalid_labels_cannot_inflate_scores(key,value):
    from agentic_rag.benchmark.corpus import validate
    corpus,_ = load()
    corpus['queries'][0][key] = value
    with pytest.raises(ValueError, match='label list'):
        validate(corpus)


def test_scoped_model_corpus_rejected_before_database_or_provider(tmp_path,monkeypatch):
    from pathlib import Path
    from agentic_rag.config import Config
    from agentic_rag.benchmark import corpus,runner
    monkeypatch.setattr(runner,'isolated_database',lambda *a:pytest.fail('must reject before DB work'))
    with pytest.raises(ValueError,match='require retrieval mode'):
        runner.run(Config(),corpus_path=Path(corpus.__file__).with_name('corpus-scope-v1.json'),
                   mode='end-to-end',output=tmp_path/'must-not-create')
    assert not (tmp_path/'must-not-create').exists()
