"""Exercise the measured raw request with fake HTTP and a real durable sink."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent


class PersistenceTest(unittest.TestCase):
    # Regression: a failed native drain must not erase an attempted request.
    def exercise(self, http_timeout=False, drain_failure=True):
        spec = importlib.util.spec_from_file_location('measured_benchmark', ROOT/'benchmark.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tree = ast.parse((ROOT/'benchmark.py').read_text())
        raw = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'raw')
        response = dict(model='test', results=[dict(index=0, relevance_score=0.8)])

        class Client:
            def __init__(self, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def post(self, *args, **kwargs):
                if http_timeout: raise module.httpx.ReadTimeout('synthetic timeout')
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: response)

        def drain():
            if drain_failure: raise TimeoutError('native_drain_120s')
            return 0.25

        with tempfile.TemporaryDirectory() as scratch:
            sink = Path(scratch)/'observations.jsonl'
            def save(row):
                with sink.open('a') as stream: stream.write(json.dumps(row)+'\n')
            scope = dict(vars(module), a=SimpleNamespace(name='test', round=0),
                url='http://unused', httpx=SimpleNamespace(Client=Client),
                drain=drain, save=save)
            exec(compile(ast.Module(body=[raw], type_ignores=[]), str(ROOT/'benchmark.py'), 'exec'), scope)
            case = dict(id='case', query='Wer gibt frei?', family='role', language='de', expected=['1'],
                passages=[dict(id='1', text='Freigabe')], pair='pair')
            if drain_failure:
                with self.assertRaisesRegex(TimeoutError, 'native_drain_120s'): scope['raw'](case, 'quality')
            else: scope['raw'](case, 'quality')
            rows = [json.loads(line) for line in sink.read_text().splitlines()] if sink.exists() else []
            self.assertEqual(len(rows), 1, 'attempted HTTP request missing from durable evidence')
            self.assertEqual(rows[0]['error'], 'ReadTimeout' if http_timeout else None)
            if drain_failure: self.assertEqual(rows[0]['drain_error'], 'TimeoutError')
            else: self.assertEqual(rows[0]['drain_ms'], 0.25)

    def test_successful_http_failed_drain(self): self.exercise()
    def test_timed_out_http_failed_drain(self): self.exercise(http_timeout=True)
    def test_successful_http_and_drain(self): self.exercise(drain_failure=False)

    def test_adapter_batch_is_retained_when_drain_fails(self):
        spec = importlib.util.spec_from_file_location('measured_benchmark', ROOT/'benchmark.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        saved = []
        def fail(): raise TimeoutError('native_drain_120s')
        with self.assertRaisesRegex(TimeoutError, 'native_drain_120s'):
            module.persist_after_drain([dict(request=i) for i in range(4)], fail, saved.append, makespan_ms=1500)
        self.assertEqual([r['request'] for r in saved], [0, 1, 2, 3])
        self.assertTrue(all(r['drain_error']=='TimeoutError' and r['drain_ms'] is None for r in saved))
        self.assertTrue(all(r['makespan_ms']==1500 for r in saved))

    def test_normal_adapter_batch_keeps_shared_drain_and_timing(self):
        spec = importlib.util.spec_from_file_location('measured_benchmark', ROOT/'benchmark.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        saved = []
        module.persist_after_drain([dict(request=i) for i in range(4)], lambda: 2.5, saved.append, makespan_ms=1000)
        self.assertEqual(saved, [dict(request=i, drain_ms=2.5, makespan_ms=1000) for i in range(4)])


if __name__ == '__main__': unittest.main()
