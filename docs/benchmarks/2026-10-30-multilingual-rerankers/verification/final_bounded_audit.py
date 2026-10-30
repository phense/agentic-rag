"""Offline evidence reconstruction. Never imports or executes measured helpers."""
import argparse
import collections
import copy
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

REPO = Path('/home/administrator/Claude/agentic-rag/.worktrees/request-tracing-60-20261030')
ROOT = Path('/home/administrator/Claude/.scratch/rag62-three-models-20261030')
SRC = REPO / 'docs/benchmarks/2026-10-30-multilingual-rerankers'
RUNS = ROOT / 'runs-f'
NAMES = ['minilm-l6', 'mmarco', 'jina-v2', 'jina-v3.5']
GRID = [(6, 120), (6, 600), (6, 1200), (12, 600), (12, 1200)]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def metric(order, expected):
    if not expected:
        return None
    rel = [int(x in expected) for x in order]
    ideal = sum(1 / math.log2(j + 2) for j in range(min(len(expected), 3)))
    return dict(top1=bool(rel[0]), recall3=sum(rel[:3]) / len(expected),
                all_sources3=sum(rel[:3]) == len(expected),
                mrr=1 / (rel.index(1) + 1) if 1 in rel else 0,
                ndcg3=sum(v / math.log2(j + 2) for j, v in enumerate(rel[:3])) / ideal)


def quality(rows):
    ms = [r['_independent'] for r in rows if r['_independent'] is not None]
    result = dict(n=len(rows), scored_n=len(ms), unavailable_n=len(rows) - len(ms),
                  top1_count=sum(m['top1'] for m in ms),
                  all_sources3_count=sum(m['all_sources3'] for m in ms))
    for key in ['top1', 'recall3', 'all_sources3', 'mrr', 'ndcg3']:
        result[key] = statistics.mean(m[key] for m in ms) if ms else None
    return result


def quantile(values, p):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * p
    a, b = math.floor(position), math.ceil(position)
    return values[a] * (b - position) + values[b] * (position - a) if a != b else values[a]


def timing(values):
    return dict(n=len(values), p50_ms=quantile(values, .5), p95_ms=quantile(values, .95),
                p99_ms=quantile(values, .99), max_ms=max(values) if values else None)


def pad(text, n, position, language):
    filler = (' Das Gebäude wird regelmäßig dokumentiert. Die allgemeine Beschreibung enthält keine weiteren Entscheidungen. '
              if language == 'de' else ' The building is documented regularly. This general description contains no further decisions. ')
    count = max(0, n - len(text) - 2)
    extra = ''.join(filler[i % len(filler)] for i in range(count))
    if position == 'end':
        return extra + ' ' + text
    if position == 'middle':
        return extra[:len(extra) // 2] + ' ' + text + ' ' + extra[len(extra) // 2:]
    return text + ' ' + extra


def permute(case, reverse=False):
    docs = copy.deepcopy(case['passages'])
    random.Random(case['pair']).shuffle(docs)
    return list(reversed(docs)) if reverse else docs


def expected_rows(cases, rnd):
    """Construct identities and payloads from corpus, not observed counts/labels."""
    import unicodedata
    out = []

    def add(case, mode, docs=None, **extra):
        docs = permute(case) if docs is None else docs
        out.append(dict(mode=mode, case_id=case['id'], family=case['family'],
                        language=case['language'], split=case['split'], expected=case['expected'],
                        input=[p['id'] for p in docs], _query=case['query'],
                        _docs=[p['text'] for p in docs], **extra))

    add(cases[0], 'cold-first', permutation=0)
    prior = [c for c in cases if c['split'] == 'prior-diagnostic']
    if rnd == 0:
        for c in cases:
            add(c, 'quality', permutation=0)
            add(c, 'quality', permute(c, True), permutation=1)
            add(c, 'adapter')
        for c in prior:
            other = next(x for x in prior if x['pair'] == c['pair'] and x['language'] != c['language'])
            add(c, 'cross-language', permute(dict(c, passages=other['passages'])),
                candidate_language=other['language'], permutation=0)
        firsts = [c for c in prior if '-1-' in c['id']]
        assert len(firsts) == 16
        for c in firsts:
            for pos in ['beginning', 'middle', 'end']:
                docs = [dict(p, text=pad(p['text'], 6000, pos, c['language'])) for p in permute(c)]
                add(c, 'long-context', docs, position=pos, target_chars=6000, permutation=0)
        for c in [c for c in firsts if c['language'] == 'de']:
            for variant in ['whitespace', 'umlaut-ascii', 'unicode-nfd']:
                q = c['query']
                if variant == 'whitespace':
                    q = '  ' + q.replace(' ', '   ') + '  '
                elif variant == 'umlaut-ascii':
                    q = q.translate(str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}))
                else:
                    q = unicodedata.normalize('NFD', q)
                add(dict(c, query=q), 'perturbation', variant=variant, permutation=0)
        unsupported = {
            'de': ['Wie hoch ist die Temperatur auf dem Mars?', 'Wer gewann den Segelwettbewerb in Oslo?',
                   'Wann wurde die Sternwarte in Lima eröffnet?', 'Welche Zutaten enthält die Mangosuppe?',
                   'Wie viele Zuschauer hatte das Theaterstück in Riga?', 'Wo liegt das Grab des Königs von Bhutan?',
                   'Welche Farbe hat das Trikot des Vereins in Porto?', 'Warum wandern die Vögel nach Süden?'],
            'en': ['What is the temperature on Mars?', 'Who won the sailing competition in Oslo?',
                   'When did the observatory in Lima open?', 'Which ingredients are in the mango soup?',
                   'How many spectators attended the play in Riga?', 'Where is the tomb of the king of Bhutan?',
                   'What colour is the club jersey in Porto?', 'Why do birds migrate south?']}
        for lang, queries in unsupported.items():
            c = next(c for c in prior if c['language'] == lang)
            for i, q in enumerate(queries):
                add(dict(c, id=f'unsupported-{i}-{lang}', query=q, expected=[]), 'unsupported', permutation=0)
    for cell, (n, length) in enumerate(GRID):
        for repeat in range(15):
            c = cases[(repeat * 7 + cell * 11) % len(cases)]
            docs = [dict(id=str(i), text=pad(c['passages'][i % 6]['text'], length, 'beginning', c['language'])) for i in range(n)]
            add(dict(c, expected=[]), 'performance', docs, candidates=n, target_chars=length, repeat=repeat, permutation=0)
    if rnd == 0:
        for concurrency in [1, 2, 4]:
            for repeat in range(5):
                c = cases[(repeat * 13) % len(cases)]
                docs = [dict(p, text=pad(p['text'], 599, 'beginning', c['language'])) for p in permute(c)]
                for _ in range(concurrency):
                    add(c, 'concurrency', docs, concurrency=concurrency, repeat=repeat)
        add(dict(cases[0], query='Wie behebe ich ERR_PERMISSION_DENIED beim Öffnen des Archivs?'), 'exact-symbol-bypass')
    assert len(out) == (520 if rnd == 0 else 76)
    return out


def countertext(value):
    return {k: int(v) for k, v in (line.split() for line in value.splitlines())}


def compare(a, b, path=''):
    if isinstance(a, dict):
        assert a.keys() == b.keys(), ('keys', path, a.keys() - b.keys(), b.keys() - a.keys())
        for k in a:
            compare(a[k], b[k], path + '/' + str(k))
    elif isinstance(a, list):
        assert len(a) == len(b), ('length', path)
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, path + '/' + str(i))
    elif isinstance(a, (int, float)) and not isinstance(a, bool):
        assert math.isclose(a, b, rel_tol=2e-12, abs_tol=2e-12), ('number', path, a, b)
    else:
        assert a == b, ('value', path, a, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--partial', action='store_true')
    ap.add_argument('--model-files', action='store_true')
    args = ap.parse_args()
    corpus = read(SRC / 'corpus.json')
    cases = corpus['cases']
    ids = {c['id'] for c in cases}
    assert len(cases) == len(ids) == 96
    assert len({c['query'] for c in cases}) == 96
    assert len({c['family'] for c in cases}) == 24
    assert len({c['pair'] for c in cases}) == 48
    language = {}
    for lang in ['de', 'en']:
        cs = [c for c in cases if c['language'] == lang]
        assert len(cs) == 48
        assert collections.Counter(c['split'] for c in cs) == {'prior-diagnostic': 16, 'new-unseen': 32}
        assert sum(len(c['expected']) for c in cs) == 53
        language[lang] = dict(questions=len(cs), required_source_occurrences=53,
                              splits=dict(collections.Counter(c['split'] for c in cs)))
    for c in cases:
        assert len(c['passages']) == len({d['id'] for d in c['passages']}) == 6
        assert len(c['expected']) == len(set(c['expected'])) in [1, 2]
        assert set(c['expected']) <= {d['id'] for d in c['passages']}
    for pair in {c['pair'] for c in cases}:
        a, b = [c for c in cases if c['pair'] == pair]
        assert a['expected'] == b['expected'] and {a['language'], b['language']} == {'de', 'en'}
    prior_path = REPO / 'docs/benchmarks/2026-10-30-german-reranker/corpus.json'
    if not prior_path.exists():
        candidates = [p for p in (REPO / 'docs/benchmarks/2026-10-30-german-reranker').rglob('*.json') if p.name.startswith('corpus')]
        assert len(candidates) == 1, candidates
        prior_path = candidates[0]
    prior_cases = read(prior_path)['cases']
    assert len(prior_cases) == 32
    assert [{k: v for k, v in c.items() if k != 'split'} for c in cases[:32]] == prior_cases
    manifests = {}
    for name, path, key in [
        ('original_full_suite', REPO / 'docs/verification/issue62/full-green-exit.json', 'source_files'),
        ('german_evaluation', REPO / 'docs/benchmarks/2026-10-30-german-reranker/evaluation/seal.json', None)]:
        data = read(path)
        mapping = data[key] if key else data['frozen']['source']
        assert len(mapping) == (343 if key else 159)
        mismatches = [f for f, h in mapping.items() if not (REPO / f).exists() or sha(REPO / f) != h]
        assert not mismatches, (name, mismatches)
        manifests[name] = dict(files=len(mapping), mismatches=mismatches, sha256=sha(path))
    matrix_seal = read(RUNS / 'matrix-seal.json')
    e_runs, d_runs = ROOT / 'runs-e', ROOT / 'runs-d'
    e_seal, old_seal = read(e_runs / 'matrix-seal.json'), read(d_runs / 'matrix-seal.json')
    for newer, older in [(RUNS, e_runs), (e_runs, d_runs)]:
        seal = read(newer / 'matrix-seal.json')
        assert seal['previous_run'] == str(older)
        assert seal['previous_matrix_sha256'] == sha(older / 'matrix-exit.json')
        assert seal['previous_frozen'] == read(older / 'matrix-seal.json')['frozen']
        assert read(older / 'matrix-exit.json')['exit'] == 1
    for old_run in ('runs-d', 'runs-e'):
        old = read(ROOT / old_run / 'matrix-seal.json')
        assert all(sha(SRC / 'executed-sources' / old_run / f) == h for f, h in old['frozen'].items())
    for name in NAMES:
        old, new = e_runs / (name + '-r0'), RUNS / (name + '-r0')
        mapping = lambda d: {str(p.relative_to(d)): sha(p) for p in d.rglob('*') if p.is_file()}
        assert mapping(old) == mapping(new), ('reused unit differs', name)
        assert sha(e_runs / (name + '-r0-console.log')) == sha(RUNS / (name + '-r0-console.log'))
    def verify_unit_frozen(seal, name, rnd):
        base = SRC if rnd else SRC / 'executed-sources' / ('runs-e' if name == 'jina-v3.5' else 'runs-d')
        expected = matrix_seal if rnd else (e_seal if name == 'jina-v3.5' else old_seal)
        assert set(seal['frozen']) == set(expected['frozen']) - {'PLAN.md'}
        assert all(expected['frozen'][f] == h for f, h in seal['frozen'].items())
        assert all(sha(base / f) == h for f, h in seal['frozen'].items())
    assert matrix_seal['source_revision'] == 'e81b21ffc907218800e1fa9646abf74d0c81b7e7'
    assert all(sha(SRC / f) == h for f, h in matrix_seal['frozen'].items())
    models = read(SRC / 'models.json')
    assert models == matrix_seal['models'] == read(Path('/dev/shm/rag62-three-models-20261030/models.json'))
    verified_models = []
    if args.model_files:
        for model in models:
            for f, info in model['files'].items():
                path = Path('/dev/shm/rag62-three-models-20261030') / model['name'] / f
                assert path.stat().st_size == info['bytes'] and sha(path) == info['sha256'], str(path)
                verified_models.append(dict(model=model['name'], file=f, sha256=info['sha256'], bytes=info['bytes']))
    matrix_exit = read(RUNS / 'matrix-exit.json') if (RUNS / 'matrix-exit.json').exists() else None
    if not args.partial:
        assert matrix_exit is not None and matrix_exit['exit'] == 0
        assert matrix_exit['protocol_status'] == 'original-protocol-incomplete-model-runtime-failure'
        assert matrix_exit['accepted_successful_units'] == 9 and matrix_exit['failed_units'] == 1
        assert len(matrix_exit['completed']) == 10
        expected_order = [(n, 0) for n in NAMES] + [(n, 1) for n in ['mmarco', 'jina-v2', 'minilm-l6']] + [(n, 2) for n in ['jina-v2', 'minilm-l6', 'mmarco']]
        assert [(r['model'], r['round']) for r in matrix_exit['completed']] == expected_order
    unit_records = matrix_exit['completed'] if matrix_exit else (read(RUNS / 'matrix-progress.json') if (RUNS / 'matrix-progress.json').exists() else read(ROOT / 'runs-d/matrix-exit.json')['completed'][:3])
    rows_by_model = {}
    summaries = {}
    additional = {}
    unit_audits = []
    failed_units = []
    fingerprints = {}
    for name in NAMES:
        rows, starts, envelopes, all_events = [], [], [], []
        extras = dict(native_tied_responses=0, bridge_tied_responses=0, bridge_new_tied_responses=0,
                      native_order_changes_all_events=0, censored=[], adapter_without_inference=[],
                      all_misses=[], server_performance={}, concurrency_ranked_timing={})
        for rnd in range(1 if name == 'jina-v3.5' else 3):
            root = RUNS / f'{name}-r{rnd}'
            if not (root / 'exit.json').exists():
                if args.partial:
                    continue
                raise AssertionError(('missing unit', name, rnd))
            ex, seal = [read(root / f) for f in ['exit.json', 'seal.json']]
            if ex['exit'] != 0 and ex['observations'] == 0:
                assert args.partial
                assert ex['observations'] == 0 and lines(root / 'observations.jsonl') == []
                assert ex['child_stopped'] and ex['child_exit'] is None
                assert ex['cleanup_errors'] == ex['remaining_group_members'] == [] and ex['temporary_model_copy_removed']
                assert seal['source_revision'] == matrix_seal['source_revision']
                verify_unit_frozen(seal, name, rnd)
                assert all(sha(REPO / f) == h for f, h in seal['product'].items())
                assert seal['model'] == next(m for m in models if m['name'] == name)
                for env in [seal['envelope'], ex['envelope_after']]:
                    assert env['affinity'] == [0, 1, 2, 3] and env['cpu.max'] == '400000 100000'
                    assert env['memory.max'] == '8589934592' and env['memory.swap.max'] == '0'
                    assert all(v == 0 for v in countertext(env['memory.events']).values())
                record = next(v for v in unit_records if v['model'] == name and v['round'] == rnd)
                assert record['exit'] == 1 and record['post_exit_port_connect_errno'] == 111
                failed_units.append(dict(model=name, round=rnd, exit=ex, seal=seal, matrix_record=record,
                    missing_artifacts=[f for f in ['startup.json', 'server-events.jsonl', 'server-console.log'] if not (root / f).exists()]))
                for f in root.iterdir():
                    if f.is_file():
                        fingerprints[str(f.relative_to(ROOT))] = sha(f)
                continue
            startup = read(root / 'startup.json')
            assert ex['exit'] == (1 if name == 'jina-v3.5' else 0) and ex['child_stopped'] and ex['child_exit'] == -15
            assert ex['cleanup_errors'] == ex['remaining_group_members'] == []
            assert ex['temporary_model_copy_removed']
            assert seal['source_revision'] == matrix_seal['source_revision']
            verify_unit_frozen(seal, name, rnd)
            assert all(sha(REPO / f) == h for f, h in seal['product'].items())
            model = next(m for m in models if m['name'] == name)
            assert seal['model'] == model
            assert startup['same_cgroup'] and startup['affinity'] == [0, 1, 2, 3]
            before, after = seal['envelope'], ex['envelope_after']
            for env in [before, after]:
                assert env['affinity'] == [0, 1, 2, 3]
                assert env['cpu.max'] == '400000 100000'
                assert env['memory.max'] == '8589934592' and env['memory.swap.max'] == '0'
                assert all(v == 0 for v in countertext(env['memory.events']).values())
            record = next(v for v in unit_records if v['model'] == name and v['round'] == rnd)
            assert record['exit'] == ex['exit'] and record['post_exit_port_connect_errno'] == 111
            props = dict(line.split('=', 1) for line in record['systemd_properties'].splitlines())
            if ex['exit'] == 0:
                assert props['ActiveState'] == 'inactive' and props['SubState'] == 'dead'
                assert props['Result'] == 'success' and props['ExecMainStatus'] == '0'
            else:
                assert name == 'jina-v3.5' and rnd == 0 and props['ActiveState'] == props['SubState'] == 'failed'
                assert props['Result'] == 'exit-code' and props['ExecMainStatus'] == '1'
                failed_units.append(dict(model=name, round=rnd, exit=ex, matrix_record=record))
            rs, events = lines(root / 'observations.jsonl'), lines(root / 'server-events.jsonl')
            plan = expected_rows(cases, rnd)
            assert len(rs) == ex['observations']
            if ex['exit'] == 0:
                assert len(rs) == len(plan)
            else:
                assert name == 'jina-v3.5' and rnd == 0 and len(rs) == 322 < len(plan)
                plan = plan[:len(rs)]
            loaded = [e for e in events if e['kind'] == 'loaded']
            assert len(loaded) == 1 and loaded[0]['pid'] == startup['pid']
            assert loaded[0]['affinity'] == [0, 1, 2, 3]
            assert loaded[0]['cgroup'].strip() == '0::' + before['path'] == '0::' + after['path']
            assert all(e['kind'] in ['loaded', 'inference'] for e in events)
            by_seq = {e['sequence']: e for e in events if e['kind'] == 'inference'}
            assert len(by_seq) == len(events) - 1
            assert sorted(by_seq) == list(range(1, len(by_seq) + 1))
            for seq, event in by_seq.items():
                body = event['output']
                scores = {v['index']: v['relevance_score'] for v in body['results']}
                native = body['measurement']['native_scores']
                assert body['model'] == name and body['measurement']['sequence'] == seq
                assert len(scores) == len(native) == event['candidates']
                assert set(scores) == set(range(len(scores)))
                assert all(math.isfinite(v) and 0 <= v <= 1 for v in scores.values())
                assert all(math.isfinite(v) for v in native)
                for i, score in scores.items():
                    mapped = (max(-1, min(1, native[i])) + 1) / 2 if name == 'jina-v3.5' else 1 / (1 + math.exp(-native[i]))
                    assert math.isclose(score, mapped, abs_tol=2e-15, rel_tol=2e-15)
                native_order = sorted(scores, key=lambda i: (-native[i], i))
                bridge_order = sorted(scores, key=lambda i: (-scores[i], i))
                extras['native_order_changes_all_events'] += native_order != bridge_order
                extras['native_tied_responses'] += len(set(native)) < len(native)
                extras['bridge_tied_responses'] += len(set(scores.values())) < len(scores)
                extras['bridge_new_tied_responses'] += any(native[i] != native[j] and scores[i] == scores[j] for i in scores for j in scores if i < j)
            cursor = 1
            offset = 0
            while offset < len(rs):
                r, want = rs[offset], plan[offset]
                for k, v in want.items():
                    if not k.startswith('_'):
                        assert r[k] == v, (name, rnd, offset, k, r[k], v)
                assert r['model'] == name and r['round'] == rnd
                assert len(r['order']) == len(r['input']) and set(r['order']) == set(r['input'])
                assert math.isfinite(r['elapsed_ms']) and r['elapsed_ms'] >= 0
                if r['drain_ms'] is None:
                    assert ex['exit'] == 1 and offset == len(rs)-1 and r['drain_error'] == 'TimeoutError'
                else:
                    assert r['drain_ms'] >= 0
                adapter = r['mode'] in ['adapter', 'concurrency', 'exact-symbol-bypass']
                docs = [('\n' + d)[:600] for d in want['_docs']] if adapter else want['_docs']
                fingerprint = hashlib.sha256(json.dumps([want['_query'], docs], ensure_ascii=False).encode()).hexdigest()
                if r['mode'] == 'concurrency':
                    count = r['concurrency']
                    batch = rs[offset:offset + count]
                    assert len(batch) == count
                    for j, row in enumerate(batch):
                        for k, v in plan[offset + j].items():
                            if not k.startswith('_'):
                                assert row[k] == v
                        row['_independent'] = metric(row['order'], row['expected'])
                        assert row['metrics'] == row['_independent']
                        assert row['model'] == name and row['round'] == rnd
                        assert row['makespan_ms'] == r['makespan_ms'] and row['drain_ms'] == r['drain_ms']
                        assert row['elapsed_ms'] <= row['makespan_ms']
                        if row['diagnostics']['outcome'] != 'ranked':
                            assert row['order'] == row['input']
                        if row['diagnostics']['outcome'] == 'pressure':
                            assert row['diagnostics']['candidates'] == 0
                    accepted = [row for row in batch if row['diagnostics']['outcome'] != 'pressure']
                    batch_events = []
                    while cursor in by_seq and by_seq[cursor]['input_sha256'] == fingerprint and len(batch_events) < len(accepted):
                        batch_events.append(by_seq[cursor]); cursor += 1
                    assert len(batch_events) == len(accepted), (name, 'concurrency event count', count, len(batch_events), len(accepted))
                    event_orders = collections.Counter(tuple(r['input'][v['index']] for v in sorted(e['output']['results'], key=lambda v: (-v['relevance_score'], v['index']))) for e in batch_events)
                    for row in batch:
                        if row['diagnostics']['outcome'] == 'ranked':
                            assert event_orders[tuple(row['order'])] > 0
                            event_orders[tuple(row['order'])] -= 1
                    offset += count
                    continue
                event = None
                if cursor in by_seq and by_seq[cursor]['input_sha256'] == fingerprint:
                    event = by_seq[cursor]
                    cursor += 1
                if r['mode'] == 'exact-symbol-bypass':
                    assert event is None and r['diagnostics']['outcome'] == 'bypass' and r['order'] == r['input']
                elif adapter:
                    diag = r['diagnostics']
                    artifact = 'model.safetensors' if name == 'jina-v3.5' else 'model.onnx'
                    assert diag['route'] == 'focused-v1' and diag['model'] == name and diag['revision'] == model['files'][artifact]['sha256']
                    assert diag['candidates'] == 6 and diag['passage_chars'] == sum(map(len, docs))
                    if diag['outcome'] == 'ranked':
                        assert event is not None and r['error'] is None
                        expected_order = [r['input'][v['index']] for v in sorted(event['output']['results'], key=lambda v: (-v['relevance_score'], v['index']))]
                        assert r['order'] == expected_order
                    else:
                        assert r['order'] == r['input']
                        assert diag['outcome'] == 'timeout' and r['error'] in ['TimeoutError', 'ReadTimeout', 'ConnectTimeout', 'WriteTimeout', 'PoolTimeout']
                    if event is None:
                        extras['adapter_without_inference'].append(dict(round=rnd, case_id=r['case_id'], outcome=diag['outcome']))
                else:
                    if event is None and r.get('drain_error'):
                        assert ex['exit'] == 1 and offset == len(rs)-1
                        assert r['input_chars'] == sum(map(len, docs)) and r['input_chars'] == 35994
                        assert r['error'] == 'ReadTimeout' and r['response'] is r['metrics'] is None
                        assert r['order'] == r['input'] and r['drain_ms'] is None
                        r['_independent'] = None
                        extras['censored'].append(dict(round=rnd, mode=r['mode'], case_id=r['case_id'],
                            position=r.get('position'), elapsed_ms=r['elapsed_ms'],drain_ms=None,
                            drain_error=r['drain_error'], native_completion_event=False, error=r['error']))
                        offset += 1
                        continue
                    assert event is not None, (name, rnd, offset, 'no raw native event', cursor, r['case_id'])
                    assert event['input_chars'] == r['input_chars'] == sum(map(len, docs))
                    if r['error']:
                        assert r['error'] in ['ReadTimeout', 'ConnectTimeout', 'WriteTimeout', 'PoolTimeout']
                        assert r['metrics'] is None and r['order'] == r['input'] and r['response'] is None
                        extras['censored'].append(dict(round=rnd, mode=r['mode'], case_id=r['case_id'],
                            position=r.get('position'), candidates=r.get('candidates'), target_chars=r.get('target_chars'),
                            repeat=r.get('repeat'), elapsed_ms=r['elapsed_ms'], drain_ms=r['drain_ms'],
                            native_server_ms=event['elapsed_ms'], error=r['error']))
                    else:
                        assert r['response'] == event['output']
                        expected_order = [r['input'][v['index']] for v in sorted(event['output']['results'], key=lambda v: (-v['relevance_score'], v['index']))]
                        assert r['order'] == expected_order
                    r['_event'] = event
                r['_independent'] = metric(r['order'], r['expected']) if adapter or not r['error'] else None
                assert r['metrics'] == r['_independent'], (name, rnd, offset, 'metric')
                offset += 1
            assert cursor == len(by_seq) + 1, (name, rnd, cursor, len(by_seq))
            cpu_before = countertext(before['cpu.stat'])
            cpu_after = countertext(after['cpu.stat'])
            unit_audits.append(dict(model=name, round=rnd, unit=record['unit'], observations=len(rs),
                inferences=len(by_seq), actual_exit=ex['exit'], wall_seconds=record['wall_seconds'], systemd_properties=props,
                retained_cgroup_cpu_total_seconds=cpu_after['usage_usec'] / 1e6,
                retained_cgroup_cpu_delta_seconds=(cpu_after['usage_usec'] - cpu_before['usage_usec']) / 1e6,
                retained_cgroup_peak_mib=int(after['memory.peak']) / 1048576,
                peak_server_rss_mib=max(e['rss_peak_kib'] for e in events) / 1024,
                cpu_stat=cpu_after, memory_events=countertext(after['memory.events']),
                envelope_before=before, envelope_after=after,
                post_exit_port_connect_errno=record['post_exit_port_connect_errno']))
            for f in sorted(root.iterdir()):
                if f.is_file():
                    fingerprints[str(f.relative_to(ROOT))] = sha(f)
            rows += rs
            starts.append(startup)
            envelopes.append(after)
            all_events += events
        if not rows:
            continue
        rows_by_model[name] = rows
        primary = [r for r in rows if r['mode'] == 'quality' and r['permutation'] == 0]
        summary = dict(observations=len(rows), primary={}, splits={}, families={}, cross_language={},
                       long_context={}, perturbations={}, performance={}, adapter={}, concurrency={},
                       position_changes={}, unsupported={}, failures=[],
                       process_ready=timing([s['process_to_ready_ms'] for s in starts]),
                       first_request=timing([r['elapsed_ms'] for r in rows if r['mode'] == 'cold-first']),
                       resources=envelopes, native_score_order_changes=0, native_outside_0_1=0)
        for r in rows:
            if r.get('response'):
                native = r['response']['measurement']['native_scores']
                native_order = [r['input'][i] for i in sorted(range(len(native)), key=lambda i: (-native[i], i))]
                summary['native_score_order_changes'] += native_order != r['order']
                summary['native_outside_0_1'] += any(v < 0 or v > 1 for v in native)
        summary['peak_server_rss_mib'] = max(e['rss_peak_kib'] for e in all_events) / 1024
        summary['inference_count'] = sum(e['kind'] == 'inference' for e in all_events)
        for lang in ['de', 'en']:
            q = [r for r in primary if r['language'] == lang]
            summary['primary'][lang] = quality(q)
            for split in ['prior-diagnostic', 'new-unseen']:
                summary['splits'][lang + '/' + split] = quality([r for r in q if r['split'] == split])
            summary['cross_language'][lang] = quality([r for r in rows if r['mode'] == 'cross-language' and r['language'] == lang])
            reverse = {r['case_id']: r for r in rows if r['mode'] == 'quality' and r['permutation'] == 1 and r['language'] == lang}
            common = [r for r in q if r['_independent'] is not None and reverse[r['case_id']]['_independent'] is not None]
            summary['position_changes'][lang] = dict(n=len(q), both_scored_n=len(common),
                top1_changes=sum(r['order'][0] != reverse[r['case_id']]['order'][0] for r in common),
                full_order_changes=sum(r['order'] != reverse[r['case_id']]['order'] for r in common),
                reverse_quality=quality(list(reverse.values())))
            ar = [r for r in rows if r['mode'] == 'adapter' and r['language'] == lang]
            summary['adapter'][lang] = dict(quality=quality(ar), timing=timing([r['elapsed_ms'] for r in ar]),
                ranked_only_quality=quality([r for r in ar if r['diagnostics']['outcome'] == 'ranked']),
                outcomes=dict(collections.Counter(r['diagnostics']['outcome'] for r in ar)),
                errors=dict(collections.Counter(r['error'] for r in ar if r['error'])))
            unsupported = [r for r in rows if r['mode'] == 'unsupported' and r['language'] == lang]
            score_lists = [sorted([v['relevance_score'] for v in r['response']['results']], reverse=True) for r in unsupported if r['response']]
            tops = sorted(v[0] for v in score_lists)
            summary['unsupported'][lang] = dict(n=len(unsupported), scored_n=len(tops),
                top_score_min=min(tops) if tops else None, top_score_median=statistics.median(tops) if tops else None,
                top_score_max=max(tops) if tops else None, all_top_scores=tops,
                all_top_two_margins=[v[0] - v[1] for v in score_lists],
                interpretation='Uncalibrated; no threshold, cross-model confidence or answerability claim.')
        for r in primary:
            if r['_independent'] is None or not r['_independent']['top1'] or not r['_independent']['all_sources3']:
                failure = dict(case_id=r['case_id'], expected=r['expected'], order=r['order'], metrics=r['_independent'])
                summary['failures'].append(failure)
                c = next(c for c in cases if c['id'] == r['case_id'])
                texts = {p['id']: p['text'] for p in c['passages']}
                extras['all_misses'].append(dict(failure, query=c['query'], first_text=texts[r['order'][0]],
                    required_texts=[texts[i] for i in r['expected']], native_scores=r['response']['measurement']['native_scores'] if r['response'] else None,
                    bridge_scores=[v['relevance_score'] for v in r['response']['results']] if r['response'] else None))
        for family in sorted({r['family'] for r in primary}):
            summary['families'][family] = {lang: quality([r for r in primary if r['family'] == family and r['language'] == lang]) for lang in ['de', 'en']}
        for pos in ['beginning', 'middle', 'end']:
            summary['long_context'][pos] = {lang: quality([r for r in rows if r['mode'] == 'long-context' and r['position'] == pos and r['language'] == lang]) for lang in ['de', 'en']}
        original = {r['case_id']: r for r in primary}
        for variant in ['whitespace', 'umlaut-ascii', 'unicode-nfd']:
            subset = [r for r in rows if r['mode'] == 'perturbation' and r['variant'] == variant]
            common = [r for r in subset if r['_independent'] is not None and original[r['case_id']]['_independent'] is not None]
            summary['perturbations'][variant] = dict(quality=quality(subset), both_scored_n=len(common),
                top1_changes=sum(r['order'][0] != original[r['case_id']]['order'][0] for r in common),
                full_order_changes=sum(r['order'] != original[r['case_id']]['order'] for r in common))
        for n, length in GRID:
            subset = [r for r in rows if r['mode'] == 'performance' and r['candidates'] == n and r['target_chars'] == length]
            summary['performance'][f'{n}x{length}'] = dict(http=timing([r['elapsed_ms'] for r in subset]),
                successful_http=timing([r['elapsed_ms'] for r in subset if r['error'] is None]), timeouts=sum(bool(r['error']) for r in subset),
                per_round={str(i): timing([r['elapsed_ms'] for r in subset if r['round'] == i]) for i in range(3)},
                preparation=timing([r['response']['measurement']['prepare_ms'] for r in subset if r['response']]),
                preparation_scope='external pretruncation subtotal only' if name == 'jina-v3.5' else 'complete ONNX input preparation',
                over_1500ms=sum(r['elapsed_ms'] > 1500 for r in subset))
            extras['server_performance'][f'{n}x{length}'] = dict(
                all_native_request_handling=timing([r['_event']['elapsed_ms'] for r in subset]),
                client_success_native_request_handling=timing([r['_event']['elapsed_ms'] for r in subset if r['error'] is None]),
                native_queue_wait=timing([r['_event']['output']['measurement']['queue_wait_ms'] for r in subset if 'queue_wait_ms' in r['_event']['output']['measurement']]),
                native_preparation=timing([r['_event']['output']['measurement']['prepare_ms'] for r in subset]))
        for concurrency in [1, 2, 4]:
            subset = [r for r in rows if r['mode'] == 'concurrency' and r['concurrency'] == concurrency]
            batches = {r['repeat']: r for r in subset}
            summary['concurrency'][str(concurrency)] = dict(requests=len(subset), timing=timing([r['elapsed_ms'] for r in subset]),
                outcomes=dict(collections.Counter(r['diagnostics']['outcome'] for r in subset)),
                makespan=timing([r['makespan_ms'] for r in batches.values()]), native_drain=timing([r['drain_ms'] for r in batches.values()]))
            extras['concurrency_ranked_timing'][str(concurrency)] = timing([r['elapsed_ms'] for r in subset if r['diagnostics']['outcome'] == 'ranked'])
        summary.update(protocol_status='aborted-native-drain' if name == 'jina-v3.5' else 'all-three-starts-complete', planned_observations=672, unattempted_observations=672-len(rows), primary_http_timing=timing([r['elapsed_ms'] for r in primary]))
        summaries[name] = summary
        additional[name] = extras
    paired = {}
    for i, left in enumerate(rows_by_model):
        for right in list(rows_by_model)[i + 1:]:
            paired[left + ' vs ' + right] = {}
            for lang in ['de', 'en']:
                a = {r['case_id']: r for r in rows_by_model[left] if r['mode'] == 'quality' and r['permutation'] == 0 and r['language'] == lang}
                b = {r['case_id']: r for r in rows_by_model[right] if r['mode'] == 'quality' and r['permutation'] == 0 and r['language'] == lang}
                assert a.keys() == b.keys()
                common = [k for k in a if a[k]['_independent'] is not None and b[k]['_independent'] is not None]
                counts = collections.Counter((a[k]['_independent']['top1'], b[k]['_independent']['top1']) for k in common)
                paired[left + ' vs ' + right][lang] = dict(n=len(a), both_scored_n=len(common),
                    left_only_correct=counts[True, False], right_only_correct=counts[False, True],
                    both_correct=counts[True, True], both_wrong=counts[False, False])
    independent = dict(protocol_status='original-protocol-incomplete-model-runtime-failure', planned_observations=2688, unattempted_observations=350, models=summaries, paired=paired,
        total_observations=sum(len(rows) for rows in rows_by_model.values()),
        percentile='Linear interpolation at (n-1)*p; p99 of45 observations is descriptive, not stable tail capacity.')
    if not args.partial:
        assert independent['total_observations'] == 2338 and len(unit_audits) == 10 and len(failed_units) == 1
        compare(independent, read(ROOT / 'summary-final-audited.json'))
    output = dict(status='PARTIAL' if args.partial else 'COMPLETE',
        corpus=dict(sha256=sha(SRC / 'corpus.json'), questions=96, families=24, languages=language,
                    prior32_case_fields_unchanged=True, prior_corpus_sha256=sha(prior_path)),
        manifests=manifests, frozen_hashes=matrix_seal['frozen'], model_files_verified=verified_models,
        matrix_exit_sha256=sha(RUNS / 'matrix-exit.json') if matrix_exit else None,
        analyzer_sha256=sha(SRC / 'analyze_bounded.py'), analyzer_output_matches=not args.partial,
        independent_summary=independent, additional=additional, units=unit_audits, failed_units=failed_units,
        artifact_sha256=fingerprints)
    dest = ROOT / ('audit-final-bounded-partial.json' if args.partial else 'audit-final-bounded-reconstruction.json')
    dest.write_text(json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    print(output['status'], len(unit_audits), 'units', independent['total_observations'], 'observations')
    for n, m in summaries.items():
        print(n, 'DE', m['primary']['de']['top1_count'], '/', m['primary']['de']['scored_n'],
              'EN', m['primary']['en']['top1_count'], '/', m['primary']['en']['scored_n'],
              'adapter', {lang: v['outcomes'] for lang, v in m['adapter'].items()})
    print(str(dest), sha(dest))


if __name__ == '__main__':
    main()
