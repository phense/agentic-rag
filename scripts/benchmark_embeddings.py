#!/usr/bin/env python3
"""Issue83 public-fixture CPU experiment; never reads production config or data.

Workers accept only an explicit frozen corpus, verified local artifacts and an
exclusive output directory. The Jina worker denies Internet sockets at the kernel
boundary before importing model code. This is not a sandbox for hostile native
wheels. Run models sequentially through the finite supervisor command.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import errno
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/benchmarks/2026-11-04-embedding-comparison'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def normalized(vector, width):
    if not isinstance(vector, (list, tuple)) or len(vector) != width or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in vector
    ):
        raise ValueError('invalid vector shape or finite numeric values')
    norm = math.sqrt(math.fsum(v*v for v in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('zero vector')
    return [v / norm for v in vector]


def truncate(vector, width):
    if not 1 <= width <= len(vector):
        raise ValueError('no padding or unsupported expansion')
    return normalized(vector[:width], width)


def query_groups(query):
    return ('all',*(f'{field}:{query[field]}' for field in ('language','family','split','cross_language')))


def denominators(queries,completed):
    return {'planned':len(queries),'supported':sum(bool(q['relevance']) for q in queries),
            'unsupported':sum(not q['relevance'] for q in queries),
            'completed':sum(q['id'] in completed for q in queries),
            'failed_or_missing':sum(q['id'] not in completed for q in queries)}


def evaluate(corpus, doc_vectors, query_vectors, width):
    docs = {d['id']: normalized(doc_vectors[d['id']], width) for d in corpus['documents']}
    if len(docs) != len(corpus['documents']) or set(doc_vectors) != set(docs):
        raise ValueError('document identities do not match frozen corpus')
    known_queries = {q['id'] for q in corpus['queries']}
    if set(query_vectors) - known_queries:
        raise ValueError('unexpected query identity')
    observations = []
    grouped = {}
    for q in corpus['queries']:
        row = {'id': q['id'], 'status': 'missing_inference', 'metrics': None}
        if q['id'] in query_vectors:
            query = normalized(query_vectors[q['id']], width)
            ranking = sorted(({'id': id, 'cosine': math.fsum(a*b for a, b in zip(query, v))}
                              for id, v in docs.items()), key=lambda x: (-x['cosine'], x['id']))
            row.update(status='completed', ranking=ranking)
            labels = q['relevance']
            if not set(labels).issubset(docs):
                raise ValueError('unknown relevance identity')
            if labels:
                order = [r['id'] for r in ranking]
                gains = sorted((2**r-1 for r in labels.values()), reverse=True)
                metrics = {'mrr': 1 / next(i+1 for i, id in enumerate(order) if id in labels)}
                for k in (1, 3, 5, 10):
                    top = order[:k]
                    metrics[f'recall_at_{k}'] = len(set(top) & labels.keys()) / len(labels)
                    metrics[f'all_required_at_{k}'] = int(all(set(group) & set(top) for group in q['required_groups']))
                    dcg = math.fsum((2**labels.get(id, 0)-1)/math.log2(i+2) for i, id in enumerate(top))
                    ideal = math.fsum(g/math.log2(i+2) for i, g in enumerate(gains[:k]))
                    metrics[f'ndcg_at_{k}'] = dcg / ideal
                row['metrics'] = metrics
                for group in query_groups(q):
                    grouped.setdefault(group, []).append(metrics)
        observations.append(row)
    groups = {g: {'n': len(rows), **{k: statistics.mean(r[k] for r in rows) for k in rows[0]}}
              for g, rows in grouped.items()}
    planned_groups={}
    for q in corpus['queries']:
        for group in query_groups(q):planned_groups.setdefault(group,[]).append(q)
    for group,queries in planned_groups.items():
        groups.setdefault(group,{'n':0})['denominators']=denominators(queries,query_vectors)
    completed = sum(r['status'] == 'completed' for r in observations)
    supported = sum(bool(q['relevance']) for q in corpus['queries'])
    return {'complete': completed == len(observations), 'denominators': {
        'planned': len(observations), 'supported': supported, 'unsupported': len(observations)-supported,
        'completed': completed, 'failed_or_missing': len(observations)-completed},
        'interpretation': 'Metrics condition on completed supported queries; read denominators before comparing. Unsupported rankings are not supported answers.',
        'groups': groups, 'observations': observations}


def paired_comparison(corpus,baseline,candidate,*,resamples=4000,seed=8301):
    """Query-paired bootstrap, not independent-model CIs or corpus generalization."""
    if type(resamples) is not int or resamples<1:raise ValueError('positive resample count required')
    left={r['id']:r['metrics'] for r in baseline['observations']}
    right={r['id']:r['metrics'] for r in candidate['observations']}
    if len(left)!=len(corpus['queries']) or set(left)!=set(right) or set(left)!={q['id'] for q in corpus['queries']}:
        raise ValueError('comparison query identities differ')
    groups={}
    for q in corpus['queries']:
        if q['relevance']:
            for group in query_groups(q):groups.setdefault(group,[]).append(q['id'])
    result={};rng=random.Random(seed)
    for group,ids in sorted(groups.items()):
        paired=[id for id in ids if left[id] is not None and right[id] is not None]
        row={'planned_supported':len(ids),'paired_supported':len(paired),
             'unpaired_supported_ids':[id for id in ids if id not in paired],'metrics':{}}
        if paired:
            deltas={key:[right[id][key]-left[id][key] for id in paired] for key in left[paired[0]]}
            samples={key:[] for key in deltas}
            for _ in range(resamples):
                indexes=[rng.randrange(len(paired)) for _ in paired]
                for key,values in deltas.items():samples[key].append(statistics.mean(values[i] for i in indexes))
            for key,values in deltas.items():
                row['metrics'][key]={'mean_delta':statistics.mean(values),
                    'ci95':[percentile(samples[key],.025),percentile(samples[key],.975)]}
        result[group]=row
    return {'seed':seed,'resamples':resamples,'method':'query-paired percentile bootstrap; candidate minus baseline',
            'baseline_denominators':baseline['denominators'],'candidate_denominators':candidate['denominators'],
            'interpretation':'Descriptive uncertainty on this small authored fixture; not production or answer-quality inference.',
            'groups':result}


def deny_network():
    """Deny IPv4/IPv6 socket creation, including native library calls; fail closed."""
    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                         ctypes.c_uint, ctypes.POINTER(Compare)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('seccomp_init')
    try:
        socket_call = lib.seccomp_syscall_resolve_name(b'socket')
        if socket_call < 0:
            raise RuntimeError('socket syscall unavailable')
        for family in (2, 10):  # AF_INET, AF_INET6
            comparison = Compare(0, 4, family, 0)  # SCMP_CMP_EQ
            if lib.seccomp_rule_add_array(context, 0x50000 | errno.EPERM, socket_call, 1,
                                          ctypes.byref(comparison)) != 0:
                raise RuntimeError('seccomp_rule')
        if lib.seccomp_load(context) != 0:
            raise RuntimeError('seccomp_load')
    finally:
        lib.seccomp_release(context)


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)] if values else None


def stats(values):
    return {'n': len(values), 'p50': percentile(values, .5), 'p95': percentile(values, .95),
            'p99': percentile(values, .99), 'maximum': max(values) if values else None}


def http(origin, endpoint, payload=None):
    data = None if payload is None else canonical(payload).encode()
    request = urllib.request.Request(origin + endpoint, data=data, headers={'Content-Type': 'application/json'})
    # A dedicated owned loopback daemon; never an environment-selected proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=120) as r:
        return json.load(r)


def verify_files(root, manifest):
    for name, expected in manifest['files'].items():
        p = (root / name).resolve()
        if not p.is_relative_to(root.resolve()) or not p.is_file() or __import__('hashlib').file_digest(p.open('rb'), 'sha256').hexdigest() != expected:
            raise ValueError('artifact hash mismatch: ' + name)


def require_free_port(port=11583):
    """Refuse a pre-existing listener; never send it discovery or unload calls."""
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError as exc:raise RuntimeError('benchmark daemon port already in use') from exc


def assert_owned_listener(daemon,port=11583):
    """Linux-only proof: the listening socket is held by this live child PID."""
    if daemon.poll() is not None:raise RuntimeError('owned daemon exited')
    proc=Path('/proc')/str(daemon.pid)
    sockets=set()
    for fd in (proc/'fd').iterdir():
        try:target=os.readlink(fd)
        except FileNotFoundError:continue
        if target.startswith('socket:['):sockets.add(target[8:-1])
    local=f'0100007F:{port:04X}'
    matches=[line.split()[9] for line in (proc/'net/tcp').read_text().splitlines()[1:]
             if line.split()[1]==local and line.split()[3]=='0A']
    if not matches or not set(matches).issubset(sockets) or daemon.poll() is not None:
        raise RuntimeError('benchmark listener ownership mismatch')


def worker(args):
    out = Path(args.output)
    out.mkdir(mode=0o700)
    corpus_path = Path(args.corpus)
    corpus = json.loads(corpus_path.read_text())
    protocol = json.loads(Path(args.protocol).read_text())
    if sha256(corpus_path.read_bytes()).hexdigest() != protocol['corpus_sha256']:
        raise ValueError('frozen corpus mismatch')
    descriptor = protocol['models'][args.worker]
    width = descriptor['dimensions']
    snapshot = Path(args.model_dir).resolve()
    vectors = {'documents': {}, 'queries': {}, 'duplicates': {}}
    observations = []
    result = {'model': args.worker, 'descriptor': descriptor, 'corpus_sha256': protocol['corpus_sha256'],
              'status': 'failed', 'stage': 'load', 'platform': platform.platform(),
              'python': platform.python_version(), 'torch_threads': 2, 'process_started': time.time(),
              'os_cache': 'not dropped; fresh process is not cold OS cache'}
    start = time.perf_counter()
    cpu_start = time.process_time()
    daemon = None
    lock = threading.Lock()
    try:
        if args.worker == 'bge':
            store = snapshot
            manifest = store / 'manifests/registry.ollama.ai/library/bge-m3-q8/latest'
            if sha256(manifest.read_bytes()).hexdigest() != descriptor['digest']:
                raise ValueError('BGE model manifest mismatch')
            m = json.loads(manifest.read_text())
            for layer in [m['config'], *m['layers']]:
                p = store / 'blobs' / layer['digest'].replace(':', '-')
                with p.open('rb') as f:
                    if __import__('hashlib').file_digest(f, 'sha256').hexdigest() != layer['digest'].split(':')[1]:
                        raise ValueError('BGE blob mismatch')
            daemon_env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(out),
                          'OLLAMA_MODELS': str(store), 'OLLAMA_HOST': '127.0.0.1:11583',
                          'OLLAMA_NUM_PARALLEL': '1', 'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NO_CLOUD': '1'}
            require_free_port()
            daemon_log = (out / 'ollama.log').open('w')
            daemon = subprocess.Popen(['/usr/local/bin/ollama', 'serve'], env=daemon_env, stdout=daemon_log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if daemon.poll() is not None:
                    raise RuntimeError('owned Ollama exited at startup')
                try:
                    tags = http('http://127.0.0.1:11583', '/api/tags')
                    assert_owned_listener(daemon)
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('owned Ollama not ready')
            if not any(x['digest'] == descriptor['digest'] for x in tags['models']):
                raise ValueError('owned model discovery mismatch')
            def encode(texts, side='document', task='retrieval'):
                response = http('http://127.0.0.1:11583', '/api/embed', {'model': descriptor['model'],
                    'input': texts, 'truncate': False, 'keep_alive': '10m', 'options': {'num_thread': 2}})
                return [normalized(v, width) for v in response['embeddings']]
            result['runtime'] = {'ollama_version': http('http://127.0.0.1:11583', '/api/version'),
                                 'quantization': 'Q8_0', 'separate_owned_daemon': True}
        else:
            manifest = json.loads((snapshot.parent / (args.worker + '-manifest.json')).read_text())
            if manifest['revision'] != descriptor['revision'] or manifest['repo'] != descriptor['repo']:
                raise ValueError('Jina repository identity mismatch')
            verify_files(snapshot, manifest)
            # Imports and all remote code execute only after kernel network denial.
            deny_network()
            import torch
            from transformers import AutoModel
            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
            model = AutoModel.from_pretrained(str(snapshot), trust_remote_code=True, modality='text',
                                              task='retrieval', dtype=torch.float32, local_files_only=True).eval()
            if model._modality != 'text':
                raise ValueError('unexpected modality')
            def encode(texts, side='document', task='retrieval'):
                with lock, torch.inference_mode():
                    return model.encode(texts, task=task, prompt_name=side, max_length=8192).float().tolist()
            result['runtime'] = {'packages': {n: importlib.metadata.version(n) for n in
                ('torch', 'transformers', 'peft', 'safetensors', 'numpy', 'tokenizers', 'huggingface-hub')},
                'loaded_parameters': sum(p.numel() for p in model.parameters()),
                'loaded_components': sorted(name for name, _ in model.named_modules() if name in
                    ('base_model.model.language_model', 'base_model.model.visual', 'base_model.model.audio_tower',
                     'base_model.model.vision_tower')), 'dtype': str(next(model.parameters()).dtype),
                'task': 'retrieval', 'kernel_internet_denied': True}
        result['load_seconds'] = time.perf_counter()-start
        result['stage'] = 'first_query'
        query = corpus['queries'][0]
        t = time.perf_counter()
        vec = encode([query['text']], 'query')[0]
        normalized(vec, width)
        result['first_query_seconds'] = time.perf_counter()-t
        result['stage'] = 'documents'
        t = time.perf_counter()
        for offset in range(0, len(corpus['documents']), 4):
            batch = corpus['documents'][offset:offset+4]
            values = encode([r['text'] for r in batch])
            if len(values) != len(batch):
                raise ValueError('document batch count mismatch')
            for row, value in zip(batch, values):
                normalized(value, width)
                vectors['documents'][row['id']] = value
            write(out/'vectors.json', vectors)
        result['document_build_seconds'] = time.perf_counter()-t
        result['document_inputs_per_second'] = len(corpus['documents']) / result['document_build_seconds']
        result['stage'] = 'queries'
        for query in corpus['queries']:
            t = time.perf_counter()
            value = encode([query['text']], 'query')[0]
            normalized(value, width)
            observations.append({'id': query['id'], 'seconds': time.perf_counter()-t, 'status': 'completed'})
            vectors['queries'][query['id']] = value
            with (out/'observations.jsonl').open('a') as f:
                f.write(canonical(observations[-1])+'\n')
            write(out/'vectors.json', vectors)
        result['warm_query_seconds'] = stats([r['seconds'] for r in observations])
        result['stage'] = 'concurrency'
        result['concurrent_client_seconds'] = {}
        sampled = [q for q in corpus['queries'] if q['split'] == 'heldout'][:16]
        for clients in (1, 2, 4):
            durations = []
            def call(q):
                t = time.perf_counter(); value = encode([q['text']], 'query')[0]
                normalized(value, width)
                return time.perf_counter()-t
            t = time.perf_counter()
            with ThreadPoolExecutor(max_workers=clients) as pool:
                durations = list(pool.map(call, sampled[:clients*4]))
            wall = time.perf_counter()-t
            result['concurrent_client_seconds'][str(clients)] = {**stats(durations), 'wall_seconds': wall,
                'inputs_per_second': len(durations)/wall, 'scope': 'embedding call including local serialization; excludes application retrieval'}
        result['stage'] = 'duplicates'
        dup_observations = []
        for pair in corpus['duplicate_pairs']:
            values = encode([pair['left'], pair['right']], 'document', 'text-matching')
            if len(values) != 2:
                raise ValueError('duplicate batch mismatch')
            a, b = (normalized(v, width) for v in values)
            cosine = math.fsum(x*y for x, y in zip(a, b))
            predicted = cosine >= protocol['ranking']['dedup_threshold']
            dup_observations.append({'id': pair['id'], 'expected_same': pair['same'], 'cosine': cosine,
                                     'predicted_same': predicted, 'task': 'text-matching' if args.worker != 'bge' else 'production-unprefixed'})
            vectors['duplicates'][pair['id']] = values
        result['duplicates'] = {'threshold': protocol['ranking']['dedup_threshold'], 'n': len(dup_observations),
            'false_positive': sum(r['predicted_same'] and not r['expected_same'] for r in dup_observations),
            'false_negative': sum(not r['predicted_same'] and r['expected_same'] for r in dup_observations),
            'observations': dup_observations}
        result['stage'] = 'score'
        quality = evaluate(corpus, vectors['documents'], vectors['queries'], width)
        write(out/'quality.json', quality)
        if args.worker != 'bge':
            for dim in protocol['ranking']['smaller_dimensions']:
                write(out/f'quality-{dim}.json', evaluate(corpus,
                    {k: truncate(v, dim) for k, v in vectors['documents'].items()},
                    {k: truncate(v, dim) for k, v in vectors['queries'].items()}, dim))
            verify_files(snapshot, manifest)
        write(out/'vectors.json', vectors)
        result.update(status='complete', stage='finished')
    except Exception as exc:
        result['failure'] = {'class': type(exc).__name__, 'message': str(exc)[:1500]}
        raise
    finally:
        if daemon is not None:
            try:
                assert_owned_listener(daemon)
                http('http://127.0.0.1:11583', '/api/embed', {'model': descriptor['model'], 'input': [], 'keep_alive': 0})
            except Exception:
                pass
            daemon.terminate()
            try:
                daemon.wait(timeout=15)
            except subprocess.TimeoutExpired:
                daemon.kill(); daemon.wait(timeout=5)
            daemon_log.close()
        result['wall_seconds'] = time.perf_counter()-start
        result['cpu_self_seconds'] = time.process_time()-cpu_start
        result['cpu_reaped_children_seconds'] = (resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime
                                                + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime)
        result['peak_self_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        result['completed'] = {'documents': len(vectors['documents']), 'queries': len(vectors['queries']), 'duplicates': len(vectors['duplicates'])}
        result['planned'] = {'documents': len(corpus['documents']), 'queries': len(corpus['queries']), 'duplicates': len(corpus['duplicate_pairs'])}
        write(out/'worker-result.json', result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker', choices=('bge', 'small', 'nano'), required=True)
    p.add_argument('--model-dir', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--corpus', default=str(DEFAULT/'corpus.json'))
    p.add_argument('--protocol', default=str(DEFAULT/'protocol.json'))
    worker(p.parse_args())


if __name__ == '__main__':
    main()
