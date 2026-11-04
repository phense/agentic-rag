"""Maintained, no-download ONNX reproduction; historical measurements stay intact."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import inspect
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = Path(__file__).with_name('reranker_benchmark_models.json')
REQUIREMENTS = ROOT / 'docs/benchmarks/maintained-rerankers/requirements.txt'
PROFILES = ('minilm-l6', 'mmarco', 'jina-v2')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    stage = path.with_suffix('.tmp')
    stage.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    stage.replace(path)


def environment():
    """Check installed runtime versions without importing model-loading packages."""
    packages = {d.metadata['Name'].lower().replace('_', '-'): d.version
                for d in metadata.distributions() if d.metadata['Name']}
    if {'transformers', 'setuptools', 'torch'} & packages.keys():
        raise ValueError('forbidden_dependency')
    from packaging.requirements import Requirement
    for line in REQUIREMENTS.read_text().splitlines():
        if not line or line.lstrip().startswith(('#', '--hash')):
            continue
        requirement = Requirement(line.rstrip('\\').strip())
        if requirement.marker is None or requirement.marker.evaluate():
            installed = packages.get(requirement.name.lower().replace('_', '-'))
            if installed is None or installed not in requirement.specifier:
                raise ValueError('runtime_lock_mismatch')
    expected = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    if packages.get('agentic-rag') != expected:
        raise ValueError('application_version_mismatch')
    return packages


def cases(path):
    if path.stat().st_size > 2_000_000:
        raise ValueError('oversized_corpus')
    rows = json.loads(path.read_text())['cases']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('invalid_corpus')
    ids = set()
    for row in rows:
        passages = row['passages']
        if (not isinstance(row['id'], str) or not row['id'] or row['id'] in ids
                or not isinstance(row['query'], str) or not 1 <= len(row['query']) <= 512
                or not isinstance(passages, list) or not 1 <= len(passages) <= 12
                or any(not isinstance(p['id'], str) or not isinstance(p['text'], str)
                       or not 1 <= len(p['text']) <= 1200 for p in passages)
                or len({p['id'] for p in passages}) != len(passages)
                or not isinstance(row['expected'], list)
                or not set(row['expected']) <= {p['id'] for p in passages}):
            raise ValueError('invalid_corpus')
        ids.add(row['id'])
    return rows


def worker(config_path):
    # Limits are set in the owned child, never through preexec_fn in a thread.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (6 * 1024**3, 6 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    config = json.loads(Path(config_path).read_text())
    from agentic_rag.reranker_runtime import OnnxRanker
    start = time.monotonic()
    ranker = OnnxRanker(config['staging'], config['model'], config['threads'])
    load_seconds = time.monotonic() - start
    with Path(config['observations']).open('x', buffering=1) as stream:
        for row in config['cases']:
            start = time.monotonic()
            try:
                scores = ranker(row['query'], [p['text'] for p in row['passages']])
                if len(scores) != len(row['passages']) or not all(math.isfinite(v) and 0 <= v <= 1 for v in scores):
                    raise ValueError('invalid_scores')
                ordered = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
                result = {'case_id': row['id'], 'status': 'scored', 'scores': scores,
                          'order': [row['passages'][i]['id'] for i in ordered],
                          'expected': row['expected'], 'seconds': time.monotonic() - start,
                          'load_seconds': load_seconds, 'cpu_seconds': time.process_time(),
                          'rss_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
                stream.write(json.dumps(result, allow_nan=False) + '\n')
            except Exception as error:
                stream.write(json.dumps({'case_id': row['id'], 'status': 'failed',
                                         'error_class': type(error).__name__}) + '\n')
                return 1
    return 0


def run(args):
    # mkdir fails before any write if an earlier attempt already owns this path.
    output = args.output_dir.resolve()
    output.mkdir(parents=True, mode=0o700)
    staging = output / 'staged-models'
    result = {'protocol': 'maintained-onnx-smoke-v1', 'status': 'failed',
              'profile': args.profile, 'requested': 0, 'scored': 0, 'failed': 0,
              'unattempted': [], 'timeout_seconds': args.timeout, 'threads': args.threads}
    rows = []
    before = {}
    started = time.monotonic()
    rc = 1
    try:
        result['stage'] = 'corpus'
        rows = cases(args.corpus)
        result['requested'] = len(rows)
        result['stage'] = 'environment'
        result['packages'] = environment()
        from agentic_rag.reranker_runtime import OnnxRanker, verify
        import agentic_rag.reranker_profiles as profiles
        row = next(r for r in json.loads(CATALOGUE.read_text()) if r['id'] == args.profile)
        sources = [Path(__file__).resolve(), CATALOGUE, REQUIREMENTS, args.corpus.resolve(),
                   ROOT / 'pyproject.toml', Path(inspect.getfile(OnnxRanker)), Path(profiles.__file__)]
        before = {str(p): digest(p) for p in sources}
        result.update(source_hashes=before, model=row, python=sys.version,
                      platform=sys.platform, model_downloads=False)
        write_json(output / 'manifest.json', result)
        result['stage'] = 'artifact_staging'
        installed = staging / args.profile
        installed.mkdir(parents=True, mode=0o700)
        for name, artifact in row['files'].items():
            source = args.models_dir / args.profile / name
            verify(source, artifact)
            shutil.copyfile(source, installed / name)
            verify(installed / name, artifact)
        config = {'staging': str(staging), 'model': row, 'threads': args.threads,
                  'cases': rows, 'observations': str(output / 'observations.jsonl')}
        write_json(output / 'worker.json', config)
        env = {k: os.environ[k] for k in ['PATH', 'LD_LIBRARY_PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR']
               if k in os.environ}
        env.update(HOME=str(output), XDG_CACHE_HOME=str(output / 'unused-cache'),
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   HF_HOME=str(output / 'unused-hf-cache'), TOKENIZERS_PARALLELISM='false',
                   OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        # Dedicated interpreter; no inherited PYTHONPATH and no model subprocesses.
        result['stage'] = 'inference'
        with (output / 'worker.log').open('xb') as log:
            try:
                completed = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                    '--worker', str(output / 'worker.json')], env=env, stdout=log,
                    stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
                result['worker_exit'] = completed.returncode
                if completed.returncode:
                    result['error'] = 'worker_failed'
            except subprocess.TimeoutExpired:
                result['error'] = 'deadline_exceeded'
                result['worker_exit'] = None
        for name, artifact in row['files'].items():
            verify(installed / name, artifact)
        if any(digest(p) != h for p, h in before.items()):
            raise ValueError('source_changed')
        if 'error' not in result:
            result['stage'] = 'complete'
            result['status'] = 'completed'
            rc = 0
    except BaseException as error:
        result['error'] = type(error).__name__
        rc = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        journal = output / 'observations.jsonl'
        observations = []
        if journal.exists():
            try:
                observations = [json.loads(line) for line in journal.read_text().splitlines()]
            except (ValueError, OSError):
                result['error'] = 'invalid_journal'
                rc = 1
        attempted = [r.get('case_id') for r in observations]
        expected = [r['id'] for r in rows]
        if attempted != expected[:len(attempted)] or len(attempted) > len(expected):
            result['error'] = 'unexpected_observations'
            rc = 1
        result.update(scored=sum(r.get('status') == 'scored' for r in observations),
                      failed=sum(r.get('status') != 'scored' for r in observations),
                      unattempted=[r for r in expected if r not in attempted],
                      wall_seconds=time.monotonic() - started)
        if result['scored'] != result['requested'] or result['failed'] or not rows:
            rc = 1
        result['status'] = 'completed' if rc == 0 else 'failed'
        # Only files staged by this invocation are removed; all evidence remains.
        if staging.exists():
            shutil.rmtree(staging)
        result['staging_removed'] = not staging.exists()
        write_json(output / 'result.json', result)
    print(json.dumps({k: result[k] for k in ['status', 'requested', 'scored', 'failed', 'unattempted']}))
    return rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == '--worker':
        return worker(argv[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, default=ROOT / 'docs/benchmarks/2026-10-30-multilingual-rerankers/corpus.json')
    parser.add_argument('--threads', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or not 0.1 <= args.timeout <= 600:
        parser.error('timeout must be0.1..600 seconds')
    try:
        return run(args)
    except FileExistsError:
        parser.error('output directory already exists; retain the attempt and use a new path')


if __name__ == '__main__':
    raise SystemExit(main())
