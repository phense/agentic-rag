"""Literal scoring oracles and offline safety boundaries for the public comparison."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/benchmark_embeddings.py'


def api():
    assert SCRIPT.is_file(), 'The embedding comparison scorer is not implemented'
    spec = importlib.util.spec_from_file_location('embedding_comparison', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return {
        'documents': [{'id': x} for x in 'abc'],
        'queries': [
            {'id': 'q1', 'text': 'first', 'language': 'de', 'family': 'literal', 'split': 'heldout', 'cross_language': False,
             'relevance': {'a': 2}, 'required_groups': [['a']]},
            {'id': 'q2', 'text': 'both', 'language': 'en', 'family': 'multi_source', 'split': 'heldout', 'cross_language': True,
             'relevance': {'a': 2, 'b': 2}, 'required_groups': [['a'], ['b']]},
            {'id': 'u', 'text': 'unsupported', 'language': 'de', 'family': 'unsupported', 'split': 'heldout', 'cross_language': False,
             'relevance': {}, 'required_groups': []},
        ],
    }


def test_literal_cosine_ranking_and_multi_source_metrics():
    m = api()
    r = m.evaluate(fixture(), {'a': [1, 0], 'b': [0, 1], 'c': [.6, .8]},
                   {'q1': [1, 0], 'q2': [0, 1], 'u': [1, 0]}, 2)
    assert r['denominators'] == {'planned': 3, 'supported': 2, 'unsupported': 1, 'completed': 3, 'failed_or_missing': 0}
    assert r['complete'] is True
    assert [x['id'] for x in r['observations'][1]['ranking']] == ['b', 'c', 'a']
    overall = r['groups']['all']
    assert overall['recall_at_1'] == .75
    assert overall['all_required_at_1'] == .5
    assert overall['recall_at_3'] == 1
    assert overall['all_required_at_3'] == 1
    assert overall['mrr'] == 1
    assert overall['ndcg_at_3'] == pytest.approx(.9598603945740938)
    assert r['observations'][2]['metrics'] is None
    assert r['groups']['language:de']['n'] == 1
    assert r['groups']['cross_language:True']['n'] == 1


def test_missing_inference_is_not_silently_removed_or_called_zero():
    m = api()
    r = m.evaluate(fixture(), {'a': [1, 0], 'b': [0, 1], 'c': [.6, .8]}, {'q1': [1, 0]}, 2)
    assert r['complete'] is False
    assert r['denominators'] == {'planned': 3, 'supported': 2, 'unsupported': 1, 'completed': 1, 'failed_or_missing': 2}
    assert r['groups']['all']['n'] == 1
    assert r['observations'][1]['status'] == 'missing_inference'
    assert r['observations'][1]['metrics'] is None


@pytest.mark.parametrize('bad', [[0, 0], [float('nan'), 1], [1, 2, 3], [True, 1]])
def test_invalid_embeddings_do_not_become_ranked_results(bad):
    m = api()
    with pytest.raises(ValueError):
        m.evaluate(fixture(), {'a': bad, 'b': [0, 1], 'c': [.6, .8]}, {}, 2)


def test_acceptable_alternative_source_and_deterministic_ties():
    m = api()
    f = fixture()
    f['queries'] = [{'id': 'q', 'language': 'de', 'family': 'alternative', 'split': 'heldout',
                     'cross_language': False, 'relevance': {'a': 2, 'b': 2}, 'required_groups': [['a', 'b']]}]
    r = m.evaluate(f, {'b': [1, 0], 'a': [1, 0], 'c': [0, 1]}, {'q': [1, 0]}, 2)
    assert [x['id'] for x in r['observations'][0]['ranking']] == ['a', 'b', 'c']
    assert r['groups']['all']['all_required_at_1'] == 1


def test_truncation_renormalizes_without_padding():
    m = api()
    assert m.truncate([3, 4, 99], 2) == [.6, .8]
    with pytest.raises(ValueError):
        m.truncate([1, 0], 3)


def test_kernel_denies_network_in_inference_process():
    if sys.platform != 'linux':
        pytest.skip('comparison worker is Linux-only')
    m = api()
    code = f'''import importlib.util,socket,errno
s=importlib.util.spec_from_file_location("bench",{str(SCRIPT)!r});m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.deny_network()
for family in (socket.AF_INET,socket.AF_INET6):
 try:socket.socket(family,socket.SOCK_STREAM)
 except PermissionError as e:assert e.errno==errno.EPERM
 else:raise AssertionError("network socket unexpectedly allowed")
print("network denied")
'''
    p = subprocess.run([sys.executable, '-I', '-c', code], text=True, capture_output=True, timeout=10)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == 'network denied'
