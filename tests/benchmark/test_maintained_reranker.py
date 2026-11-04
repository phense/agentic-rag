"""Security reproduction must refuse custom-code models before any side effect."""
from pathlib import Path
import base64
import hashlib
import json
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/benchmark_reranker_offline.py'


def test_custom_code_profile_is_refused_before_output_or_model_access(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--profile', 'jina-v3.5',
        '--models-dir', str(tmp_path / 'missing-models'), '--output-dir', str(tmp_path / 'output')],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'invalid choice' in result.stderr
    assert not (tmp_path / 'output').exists()


@pytest.fixture
def native_fixture(tmp_path):
    """Own ReduceSum graph, no pretrained weights or custom Python model code.

    Generated with onnx1.23.2 helper/checker, IR10/opset11. For pair q+low,
    token IDs2+3 give sigmoid(5); q+high gives sigmoid(6).
    """
    pytest.importorskip('onnxruntime')
    from tokenizers import Tokenizer, models, pre_tokenizers
    root = tmp_path / 'checkout'
    script = root / 'scripts' / SCRIPT.name
    script.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT, script)
    shutil.copyfile(SCRIPT.parent.parent / 'pyproject.toml', root / 'pyproject.toml')
    requirements = root / 'docs/benchmarks/maintained-rerankers/requirements.txt'
    requirements.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT.parent.parent / requirements.relative_to(root), requirements)
    model_root = tmp_path / 'models'
    model = model_root / 'mmarco'
    model.mkdir(parents=True)
    graph = 'CAo6tQEKOQoJaW5wdXRfaWRzEgNzdW0iCVJlZHVjZVN1bSoLCgRheGVzQAGgAQcqDwoIa2VlcGRpbXMYAaABAhINc3ludGhldGljLXN1bVojCglpbnB1dF9pZHMSFgoUCAcSEAoHEgViYXRjaAoFEgNzZXFaKAoOYXR0ZW50aW9uX21hc2sSFgoUCAcSEAoHEgViYXRjaAoFEgNzZXFiGgoDc3VtEhMKEQgHEg0KBxIFYmF0Y2gKAggBQgQKABAL'
    (model / 'model.onnx').write_bytes(base64.b64decode(graph))
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, '[PAD]': 1, 'q': 2, 'low': 3, 'high': 4}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(model / 'tokenizer.json'))
    row = {'id': 'mmarco', 'repo': 'synthetic/sum', 'revision': 'own-fixture-v1',
           'pad': '[PAD]', 'files': {p.name: {'bytes': p.stat().st_size,
               'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in model.iterdir()}}
    catalogue = script.with_name('reranker_benchmark_models.json')
    catalogue.write_text(json.dumps([row]))
    corpus = tmp_path / 'corpus.json'
    corpus.write_text(json.dumps({'cases': [
        {'id': 'one', 'query': 'q', 'passages': [{'id': 'L', 'text': 'low'}, {'id': 'H', 'text': 'high'}], 'expected': ['H']},
        {'id': 'two', 'query': 'q', 'passages': [{'id': 'H', 'text': 'high'}, {'id': 'L', 'text': 'low'}], 'expected': ['H']},
    ]}))
    return {'script': script, 'models': model_root, 'corpus': corpus,
            'output': tmp_path / 'output', 'catalogue': catalogue}


def invoke(fixture, *extra):
    return subprocess.run([sys.executable, str(fixture['script']), '--profile', 'mmarco',
        '--models-dir', str(fixture['models']), '--corpus', str(fixture['corpus']),
        '--output-dir', str(fixture['output']), *extra], capture_output=True, text=True, timeout=20)


def test_real_onnx_run_records_literal_order_identity_and_preserves_inputs(native_fixture):
    f = native_fixture
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in f['models'].rglob('*') if p.is_file()}
    result = invoke(f)
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads((f['output'] / 'result.json').read_text())
    rows = [json.loads(r) for r in (f['output'] / 'observations.jsonl').read_text().splitlines()]
    assert payload['status'] == 'completed'
    assert (payload['requested'], payload['scored'], payload['failed'], payload['unattempted']) == (2, 2, 0, [])
    assert [r['order'] for r in rows] == [['H', 'L'], ['H', 'L']]
    assert rows[0]['scores'] == pytest.approx([0.9933071490757153, 0.9975273768433653])
    assert not {'transformers', 'setuptools', 'torch'} & payload['packages'].keys()
    assert payload['model_downloads'] is False and payload['staging_removed']
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items())
    assert not (f['output'] / 'unused-hf-cache').exists()
    assert payload['source_hashes'][str(f['script'])] == hashlib.sha256(f['script'].read_bytes()).hexdigest()
    original = (f['output'] / 'result.json').read_bytes()
    again = invoke(f)
    assert again.returncode == 2 and 'already exists' in again.stderr
    assert (f['output'] / 'result.json').read_bytes() == original


def test_corruption_fails_before_inference_and_retains_denominators(native_fixture):
    f = native_fixture
    (f['models'] / 'mmarco/model.onnx').write_bytes(b'corrupted')
    result = invoke(f)
    assert result.returncode == 1
    payload = json.loads((f['output'] / 'result.json').read_text())
    assert payload['status'] == 'failed' and payload['scored'] == 0
    assert payload['requested'] == 2 and payload['unattempted'] == ['one', 'two']
    assert not (f['output'] / 'observations.jsonl').exists()
    assert not (f['output'] / 'worker.log').exists()
    assert payload['staging_removed']


def test_native_loader_failure_remains_a_failure_with_worker_log(native_fixture):
    f = native_fixture
    model = f['models'] / 'mmarco/model.onnx'
    model.write_bytes(b'invalid ONNX graph')
    row = json.loads(f['catalogue'].read_text())[0]
    row['files']['model.onnx'] = {'bytes': model.stat().st_size, 'sha256': hashlib.sha256(model.read_bytes()).hexdigest()}
    f['catalogue'].write_text(json.dumps([row]))
    result = invoke(f)
    assert result.returncode == 1
    payload = json.loads((f['output'] / 'result.json').read_text())
    assert payload['worker_exit'] != 0 and payload['scored'] == 0
    assert payload['unattempted'] == ['one', 'two']
    assert (f['output'] / 'worker.log').stat().st_size > 0
    assert payload['staging_removed']


def test_deadline_kills_owned_child_and_retains_incomplete_attempt(native_fixture):
    f = native_fixture
    source = f['script'].read_text()
    # Slow only the external child boundary; parent accounting/cleanup are real.
    f['script'].write_text(source.replace('def worker(config_path):', 'def worker(config_path):\n    time.sleep(5)'))
    result = invoke(f, '--timeout', '0.2')
    assert result.returncode == 1
    payload = json.loads((f['output'] / 'result.json').read_text())
    assert payload['error'] == 'deadline_exceeded' and payload['worker_exit'] is None
    assert payload['scored'] == 0 and payload['unattempted'] == ['one', 'two']
    assert payload['staging_removed'] and payload['wall_seconds'] < 4


def test_failed_second_inference_preserves_first_and_unattempted_third(native_fixture):
    f = native_fixture
    corpus = json.loads(f['corpus'].read_text())
    corpus['cases'].append({**corpus['cases'][0], 'id': 'three'})
    f['corpus'].write_text(json.dumps(corpus))
    # Fault injection at the inference boundary; first scoring is real ONNX.
    source = f['script'].read_text()
    f['script'].write_text(source.replace("scores = ranker(row['query'],",
        "if row['id'] == 'two':\n                    raise RuntimeError('synthetic inference failure')\n                scores = ranker(row['query'],"))
    result = invoke(f)
    assert result.returncode == 1
    payload = json.loads((f['output'] / 'result.json').read_text())
    assert (payload['requested'], payload['scored'], payload['failed'], payload['unattempted']) == (3, 1, 1, ['three'])
    rows = [json.loads(r) for r in (f['output'] / 'observations.jsonl').read_text().splitlines()]
    assert rows[0]['case_id'] == 'one' and rows[0]['order'] == ['H', 'L']
    assert rows[1] == {'case_id': 'two', 'status': 'failed', 'error_class': 'RuntimeError'}
    assert payload['staging_removed']


def test_forbidden_dependency_refuses_before_native_loading(native_fixture):
    f = native_fixture
    # Model the installed-distribution boundary without installing an unsafe package.
    source = f['script'].read_text()
    f['script'].write_text(source.replace("if {'transformers', 'setuptools', 'torch'} & packages.keys():",
        "packages['transformers'] = '4.57.3'\n    if {'transformers', 'setuptools', 'torch'} & packages.keys():"))
    result = invoke(f)
    assert result.returncode == 1
    payload = json.loads((f['output'] / 'result.json').read_text())
    assert payload['error'] == 'ValueError' and payload['unattempted'] == ['one', 'two']
    assert not (f['output'] / 'worker.log').exists()
