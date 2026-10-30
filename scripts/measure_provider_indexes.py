#!/usr/bin/env python3
"""Measure three synthetic provider/index transitions in an owned disposable DB.

No production mode exists. Only local PostgreSQL port55460 is allowed. Every
inference request uses MockTransport; this measures plumbing, never real models.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time
import tomllib
from unittest.mock import patch

import httpx

from agentic_rag import db, embed, indexes, providers, search, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config

ROOT = Path(__file__).resolve().parents[1]
PORT = '55460'
URL = 'http://127.0.0.1:11434'
TOPICS = ('astronomy', 'botany', 'ceramics', 'acoustics', 'geology',
          'cartography', 'robotics', 'weaving')
QUERIES = ('luminous orbital survey', 'chlorophyll leaf exchange', 'kiln glaze vessels',
           'standing wave resonance', 'tectonic mineral layers', 'coordinate bearing atlas',
           'actuator feedback machine', 'loom fiber tension')
LIFECYCLE_PROBE = 'Synthetic connectivity probe; no stored knowledge.'
MODELS = {'synthetic-legacy': (1024, 'd'*64), 'synthetic-three-a': (3, 'a'*64),
          'synthetic-three-b': (3, 'b'*64), 'synthetic-five': (5, 'c'*64)}


class MeasurementFailure(RuntimeError):
    """Only public fixed error codes are exported, never exception contents."""


def require(condition, code):
    if not condition:
        raise MeasurementFailure(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def runtime_manifest():
    paths = sorted((ROOT/'agentic_rag').rglob('*.py')) + sorted((ROOT/'sql').glob('*.sql'))
    paths.append(Path(__file__).resolve())
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in paths}


def git_state():
    def command(*args):
        return subprocess.run(['git', '--no-optional-locks', '-C', str(ROOT), *args],
                              capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return {'head': command('rev-parse', 'HEAD'),
            'branch': command('branch', '--show-current'),
            'dirty': bool(command('status', '--porcelain'))}


def samples(values):
    ordered = sorted(values)
    return {'count': len(values), 'raw_ms': [round(v, 6) for v in values],
            'median_ms': round(statistics.median(values), 6),
            'p95_ms': round(ordered[max(0, math.ceil(.95*len(ordered))-1)], 6),
            'p95_definition': 'nearest-rank ceil(0.95*n), no interpolation'}


def usage():
    used = resource.getrusage(resource.RUSAGE_SELF)
    resident_pages = int(Path('/proc/self/statm').read_text().split()[1])
    return {'user_cpu_seconds': used.ru_utime, 'system_cpu_seconds': used.ru_stime,
            'rss_bytes': resident_pages*os.sysconf('SC_PAGE_SIZE'),
            'cumulative_peak_rss_bytes': used.ru_maxrss*1024}


def database_sizes(cfg):
    with db.connect(cfg) as conn:
        rows = conn.execute("""SELECT c.relname,
            pg_relation_size(c.oid)::bigint relation_bytes,
            pg_indexes_size(c.oid)::bigint index_bytes,
            pg_total_relation_size(c.oid)::bigint total_bytes
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname""").fetchall()
        index_rows = conn.execute("""SELECT relname table_name,indexrelname index_name,
            pg_relation_size(indexrelid)::bigint index_bytes
            FROM pg_stat_user_indexes ORDER BY relname,indexrelname""").fetchall()
        return {'database_bytes': conn.execute('SELECT pg_database_size(current_database()) bytes').fetchone()['bytes'],
                'relations': rows,
                'indexes': index_rows,
                'public_relation_bytes': sum(r['relation_bytes'] for r in rows),
                'public_index_bytes': sum(r['index_bytes'] for r in rows),
                'public_total_bytes': sum(r['total_bytes'] for r in rows)}


def source_snapshot(cfg):
    with db.connect(cfg) as conn:
        docs = conn.execute('SELECT id,title,body,slug,domain,dtype,project_scope,status FROM documents ORDER BY id').fetchall()
        chunks = conn.execute('SELECT id,document_id,idx,content FROM chunks ORDER BY id').fetchall()
    return {'sha256': sha256(canonical([docs, chunks]).encode()).hexdigest(),
            'documents': len(docs), 'chunks': len(chunks),
            'document_ids': sorted(str(row['id']) for row in docs)}


class SyntheticAdapters:
    """Patch transport boundaries only, restoring every patched global on exit."""
    def __init__(self):
        self.phase = 'unassigned'
        self.counts = {}
        self.destinations = set()

    def handler(self, request):
        require(request.url.host == '127.0.0.1' and request.url.port == 11434,
                'unexpected_mock_destination')
        self.destinations.add(str(request.url.copy_with(path='', query=None)))
        count = self.counts.setdefault(self.phase, Counter())
        count['requests'] += 1
        count[request.method] += 1
        count[request.method+' '+request.url.path] += 1
        if request.method == 'GET' and request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [
                {'name': model+':latest', 'digest': digest} for model, (_, digest) in MODELS.items()]})
        require(request.method == 'POST' and request.url.path == '/api/embed', 'unexpected_mock_request')
        body = json.loads(request.content)
        model = body['model']
        require(model in MODELS, 'unknown_synthetic_model')
        texts = body['input']
        count['inputs'] += len(texts)
        count['input_characters'] += sum(len(text) for text in texts)
        count['input_utf8_bytes'] += sum(len(text.encode()) for text in texts)
        count['model:'+model+':inputs'] += len(texts)
        vectors = []
        for text in texts:
            if text in QUERIES:
                topic = QUERIES.index(text)
                count['query_inputs'] += 1
            elif text == LIFECYCLE_PROBE:
                # Selection now proves capability even when coverage is empty.
                # Accept only this exact public fixture, never arbitrary input.
                topic = 0
                count['lifecycle_synthetic_inputs'] += 1
                count['lifecycle_synthetic_characters'] += len(text)
            else:
                found = [i for i, name in enumerate(TOPICS) if name in text.casefold()]
                require(len(found) == 1, 'fixture_topic_not_unique')
                topic = found[0]
                count['corpus_inputs'] += 1
            angle = topic*2*math.pi/len(TOPICS) + .071
            # Revision changes the coordinate frame, preserving fixture meaning.
            angle += {'synthetic-three-b': .19, 'synthetic-five': .37}.get(model, 0)
            dim = MODELS[model][0]
            vectors.append([math.cos(angle), math.sin(angle)]+[0.0]*(dim-2))
        return httpx.Response(200, json={'embeddings': vectors})

    @contextmanager
    def installed(self):
        original = httpx.Client
        def provider_client(**kwargs):
            return original(transport=httpx.MockTransport(self.handler), **kwargs)
        def legacy_client():
            return original(transport=httpx.MockTransport(self.handler), trust_env=False,
                            follow_redirects=False, timeout=30)
        with patch.object(providers, '_http_client', provider_client), patch.object(embed, '_client', legacy_client):
            yield self


class Recorder:
    def __init__(self, cfg, adapters, output):
        self.cfg, self.adapters, self.output = cfg, adapters, output

    @contextmanager
    def phase(self, name):
        require(name not in self.output['phases'], 'duplicate_phase_name')
        self.adapters.phase = name
        before, started = usage(), time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter()-started)*1000
            after = usage()
            self.output['phases'][name] = {
                'elapsed_ms': round(elapsed, 6),
                'adapter_counts': counter_snapshot(self.adapters.counts.get(name, Counter())),
                'resource_samples': {'before': before, 'after': after,
                    'user_cpu_delta_seconds': after['user_cpu_seconds']-before['user_cpu_seconds'],
                    'system_cpu_delta_seconds': after['system_cpu_seconds']-before['system_cpu_seconds']},
                'postgres_bytes_after': database_sizes(self.cfg)}


def profiles():
    return {name: providers.EmbeddingProfile(provider='ollama', model=model,
        revision=MODELS[model][1], url=URL, dimensions=MODELS[model][0])
        for name, model in [('three-a', 'synthetic-three-a'), ('three-b', 'synthetic-three-b'),
                            ('five', 'synthetic-five')]}


def lifecycle(cfg, operation, *args, **kwargs):
    with db.connect(cfg) as conn:
        return operation(conn, cfg, *args, **kwargs)


def build_all(cfg, name, *, limit=5):
    progress = []
    for _ in range(32):
        result = lifecycle(cfg, store.build_embedding_index, name, limit=limit, allow_corpus=True)
        require(0 <= result['written'] <= limit, 'unbounded_build_batch')
        progress.append(result)
        if result['remaining'] == 0:
            return progress
        require(result['written'] > 0, 'build_made_no_progress')
    raise MeasurementFailure('build_iteration_limit')


def counter_snapshot(counter):
    return {**{key: 0 for key in ('requests', 'GET', 'POST', 'inputs', 'input_characters', 'input_utf8_bytes')}, **counter}


def read_mode(cfg, golden, repeats, adapters):
    """Fresh connection first pass; subsequent passes reuse it, without query cache."""
    result = {'cold_connection_first_pass': {}, 'warm_same_connection': {}}
    with db.connect(cfg, role='reader') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        selected = indexes.active(conn, cfg)
        result['selected_mode'] = 'managed:'+selected.name if selected else 'legacy-untagged-1024'
        for label, passes in [('cold_connection_first_pass', 1), ('warm_same_connection', repeats)]:
            counters_before = Counter(adapters.counts.get(adapters.phase, {}))
            resources_before = usage()
            elapsed, rows, correct = [], [], 0
            for iteration in range(passes):
                for topic, query in zip(TOPICS, QUERIES):
                    start = time.perf_counter()
                    hits, warnings = search.search(conn, cfg, query, domain='general', scope='global',
                        k=3, rerank_mode='off', context_mode='off')
                    elapsed.append((time.perf_counter()-start)*1000)
                    require(not warnings, 'search_warning_invalidates_measurement')
                    hit_ids = [hit.document_id for hit in hits]
                    good = bool(hit_ids) and hit_ids[0] in golden[topic]
                    correct += int(good)
                    rows.append({'pass': iteration, 'topic': topic, 'query': query,
                                 'top_document_ids': hit_ids, 'correct_at_1': good})
            resources_after = usage()
            counters_after = Counter(adapters.counts.get(adapters.phase, {}))
            result[label] = {'latency': samples(elapsed), 'correct_at_1': correct,
                             'adapter_counts': counter_snapshot(counters_after-counters_before),
                             'resource_samples': {'before': resources_before, 'after': resources_after,
                                 'user_cpu_delta_seconds': resources_after['user_cpu_seconds']-resources_before['user_cpu_seconds'],
                                 'system_cpu_delta_seconds': resources_after['system_cpu_seconds']-resources_before['system_cpu_seconds']},
                             'total': passes*len(QUERIES), 'queries': rows}
    return result


@contextmanager
def safe_environment():
    # Never inherit a production connection alias, even when called interactively.
    require(os.environ.get('PGPORT', PORT) == PORT, 'only_owned_port_55460_allowed')
    changes = {'PGPORT': PORT, 'TMPDIR': '/dev/shm/agentic-rag-issue61-20261030/test-artifacts',
               'RAG061_SYNTHETIC_TOKEN': 'synthetic-public-fixture-value'}
    names = set(changes) | {'PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'}
    original = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(changes)
        Path(changes['TMPDIR']).mkdir(parents=True, exist_ok=True)
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def measure(args, output):
    cfg = Config(db_host='127.0.0.1', embed_model='synthetic-legacy', ollama_url=URL,
                 embedding_profiles=profiles())
    adapters = SyntheticAdapters()
    with safe_environment(), adapters.installed(), isolated_database(cfg) as owned:
        output['owned_database'] = owned.db_name
        record = Recorder(owned, adapters, output)
        with db.connect(owned) as conn:
            output['postgres'] = conn.execute('SELECT version() version,inet_server_port() port').fetchone()
            require(output['postgres']['port'] == int(PORT), 'wrong_postgres_port')
            output['pgvector'] = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
        golden = {name: [] for name in TOPICS}
        with record.phase('fixture-audited-ingestion'):
            with db.connect(owned) as conn:
                for topic in TOPICS:
                    for variant in range(3):
                        saved = store.save_document(conn, owned, title=f'Topic {topic} specimen {variant+1}',
                            body=f'{topic.capitalize()} catalog specimen {variant+1}. '
                                 'Public synthetic reference. This generated entry is used only for an isolated plumbing measurement.',
                            domain='general', dtype='reference', scope='global',
                            provenance={'source': 'public-generated-fixture', 'measurement': 'RAG-061'})
                        require(not saved.warnings and saved.n_chunks == 1, 'fixture_ingestion_invalid')
                        golden[topic].append(str(saved.doc_id))
        output['fixture'] = {'documents': 24, 'topics': list(TOPICS), 'golden_topic_document_ids': golden,
                             'queries_not_stored_in_corpus': list(QUERIES), 'query_count': 8}
        fixed = source_snapshot(owned)
        require(fixed['documents'] == 24 and fixed['chunks'] == 24, 'fixture_snapshot_invalid')

        first = {'name': 'legacy1024-to-managed3', 'source_snapshot_before': fixed}
        with record.phase('case1-before-legacy-search'):
            first['before'] = read_mode(owned, golden, args.repeats, adapters)
        with record.phase('case1-create-build-select-three-a'):
            generation_a = lifecycle(owned, store.create_embedding_index, 'three-a', 'three-a')
            first['build_progress'] = build_all(owned, 'three-a')
            lifecycle(owned, store.select_embedding_index, 'three-a', expected_active=None)
        with record.phase('case1-after-managed-search'):
            first['after'] = read_mode(owned, golden, args.repeats, adapters)
        first['source_snapshot_after'] = source_snapshot(owned)
        require(first['source_snapshot_after'] == fixed, 'case1_canonical_source_changed')
        output['cases'].append(first)

        second = {'name': 'same-dimension-new-revision-and-compatible-config', 'source_snapshot_before': fixed}
        with record.phase('case2-before-three-a-search'):
            second['before'] = read_mode(owned, golden, args.repeats, adapters)
        with record.phase('case2-create-build-select-three-b'):
            generation_b = lifecycle(owned, store.create_embedding_index, 'three-b', 'three-b')
            require(generation_a.dimensions == generation_b.dimensions and generation_a.identity != generation_b.identity,
                    'same_dimension_revision_not_distinct')
            second['build_progress'] = build_all(owned, 'three-b')
            lifecycle(owned, store.select_embedding_index, 'three-b', expected_active=generation_a)
        with record.phase('case2-after-three-b-search'):
            second['after'] = read_mode(owned, golden, args.repeats, adapters)
        rotated = replace(owned, embedding_profiles={**owned.embedding_profiles, 'three-b':
            replace(owned.embedding_profiles['three-b'], credential_env='RAG061_SYNTHETIC_TOKEN', timeout=25)})
        with record.phase('case2-compatible-config-no-rebuild'):
            require(rotated.embedding_profiles['three-b'].identity == generation_b.identity, 'credential_changed_space_identity')
            unchanged = lifecycle(rotated, store.create_embedding_index, 'three-b', 'three-b')
            no_work = lifecycle(rotated, store.build_embedding_index, 'three-b', limit=5, allow_corpus=True)
            require(unchanged.id == generation_b.id and no_work['written'] == 0 and no_work['remaining'] == 0,
                    'compatible_config_rebuilt_vectors')
            second['compatible_configuration'] = {'same_generation_id': True, 'same_identity': True,
                'changed_fields': ['credential_env', 'timeout'], 'build_result': no_work}
        second['source_snapshot_after'] = source_snapshot(owned)
        require(second['source_snapshot_after'] == fixed, 'case2_canonical_source_changed')
        output['cases'].append(second)

        third = {'name': 'three-to-five-interrupt-resume-catchup-rollback', 'source_snapshot_before': fixed}
        with record.phase('case3-before-three-b-search'):
            third['before'] = read_mode(owned, golden, args.repeats, adapters)
        with record.phase('case3-create-five-first-batch'):
            generation_five = lifecycle(owned, store.create_embedding_index, 'five', 'five')
            first_batch = lifecycle(owned, store.build_embedding_index, 'five', limit=5, allow_corpus=True)
            require(first_batch['written'] == 5 and first_batch['remaining'] == 19, 'interruption_boundary_invalid')
            third['interrupted_after_committed_batch'] = first_batch
        with record.phase('case3-fresh-connection-resume-select'):
            # Every lifecycle() opens and closes a real connection; the first batch
            # committed before this independent status query and resumed work.
            interrupted = lifecycle(owned, indexes.status, 'five')
            require(interrupted['remaining'] == 19 and not interrupted['active'], 'resume_lost_progress')
            third['fresh_connection_interrupted_status'] = interrupted
            try:
                lifecycle(owned, store.select_embedding_index, 'five', expected_active=generation_b)
            except ValueError:
                third['partial_activation_refused'] = True
            else:
                raise MeasurementFailure('partial_generation_activated')
            third['resume_build_progress'] = build_all(owned, 'five')
            lifecycle(owned, store.select_embedding_index, 'five', expected_active=generation_b)
        with record.phase('case3-after-five-search'):
            third['after'] = read_mode(owned, golden, args.repeats, adapters)
        third['source_snapshot_after'] = source_snapshot(owned)
        require(third['source_snapshot_after'] == fixed, 'case3_comparison_source_changed')

        with record.phase('case3-post-cutover-audited-write'):
            with db.connect(owned) as conn:
                saved = store.save_document(conn, owned, title='Topic astronomy post cutover',
                    body='Astronomy extra catalog entry created after selecting the five-dimensional space. '
                         'Public generated rollback preservation fixture.',
                    domain='general', dtype='reference', scope='global',
                    provenance={'source': 'public-generated-fixture', 'measurement': 'RAG-061-after-cutover'})
                require(not saved.warnings, 'postcutover_write_warning')
            newer = source_snapshot(owned)
            require(newer['documents'] == 25 and set(fixed['document_ids']) < set(newer['document_ids']),
                    'new_canonical_document_missing')
            third['new_write'] = {'document_id': str(saved.doc_id), 'snapshot': newer}
        with record.phase('case3-stale-rollback-refusal'):
            try:
                lifecycle(owned, store.select_embedding_index, 'three-b', rollback=True, expected_active=generation_five)
            except ValueError:
                third['stale_rollback_refused'] = True
            else:
                raise MeasurementFailure('stale_rollback_accepted')
            with db.connect(owned) as conn:
                require(indexes.active(conn, owned).id == generation_five.id, 'refused_rollback_changed_selection')
        with record.phase('case3-catchup-and-rollback'):
            third['catchup_five'] = build_all(owned, 'five')
            third['catchup_three_b'] = build_all(owned, 'three-b')
            lifecycle(owned, store.select_embedding_index, 'three-b', rollback=True, expected_active=generation_five)
            with db.connect(owned, role='reader') as conn:
                conn.execute('SET TRANSACTION READ ONLY')
                hits, warnings = search.search(conn, owned, str(saved.doc_id), domain='general', scope='global',
                                               rerank_mode='off', context_mode='off')
                require(not warnings and hits and hits[0].document_id == str(saved.doc_id), 'rollback_lost_new_document')
                require(indexes.active(conn, owned).id == generation_b.id, 'rollback_did_not_select_retained_space')
            require(source_snapshot(owned) == newer, 'rollback_changed_canonical_sources')
            third['retained_status_after_rollback'] = lifecycle(owned, indexes.status)
            selected_status = next(s for s in third['retained_status_after_rollback'] if s['active'])
            require(selected_status['indexed'] == 25 and selected_status['remaining'] == 0, 'rollback_coverage_not_current')
            third['new_document_survives_and_is_indexed'] = True
        output['cases'].append(third)
        output['final_source_snapshot'] = newer
        with db.connect(owned) as conn:
            output['audit_operations'] = conn.execute('SELECT op,count(*)::int count FROM audit_log GROUP BY op ORDER BY op').fetchall()
        output['intercepted_http_destinations'] = sorted(adapters.destinations)
        output['real_inference_http_calls'] = 0
    # Reaching here means the owned database context finished its checked cleanup.
    output['owned_database_cleanup_completed'] = True
    require(len(output['cases']) == 3, 'comparison_case_count_invalid')
    for case in output['cases']:
        for side in ('before', 'after'):
            for run in ('cold_connection_first_pass', 'warm_same_connection'):
                score = case[side][run]
                require(score['correct_at_1'] == score['total'], 'synthetic_correct_at_1_regression')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='JSON evidence path; synthetic data only')
    parser.add_argument('--repeats', type=int, default=3, help='warm passes of eight queries, bounded 1 through 5')
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error('--repeats must be 1 through 5')
    before = runtime_manifest()
    output = {'schema': 'RAG-061-synthetic-measurement-v1', 'started_at': datetime.now(timezone.utc).isoformat(),
        'git_before': git_state(), 'runtime_sql_sha256_before': before,
        'command': [sys.executable, 'scripts/measure_provider_indexes.py', '--output', str(args.output), '--repeats', str(args.repeats)],
        'environment': {'PGPORT': PORT, 'PGHOST': 'unset', 'PGHOSTADDR': 'unset', 'PGSERVICE': 'unset',
                        'PGSERVICEFILE': 'unset', 'TMPDIR': '/dev/shm/agentic-rag-issue61-20261030/test-artifacts'},
        'platform': {'description': platform.platform(), 'python': sys.version,
                     'cpu_count': os.cpu_count(), 'machine': platform.machine(),
                     'installed_distribution_version': importlib.metadata.version('agentic-rag'),
                     'declared_project_version': tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']},
        'definitions': {
            'comparison': 'same runtime, same canonical source snapshot per before/after pair; never an old-release timing baseline',
            'cold': 'first eight searches on a fresh connection; OS/PostgreSQL buffers and process state are not reset',
            'warm': 'repeated eight-query passes on the same connection; no query inference cache on either route',
            'latency': 'search call wall time only, including adapter and SQL work; excludes connection opening and PG size snapshots',
            'quality': 'correct@1 against three generated document IDs per topic; fixture routing correctness, not real-model quality',
            'resource': 'shared Python process user/system CPU deltas and RSS samples; peak RSS is cumulative since process start; PostgreSQL CPU/RSS excluded',
            'storage': 'actual PostgreSQL relation/index/database bytes, including normal allocation overhead; no compression or quality claim',
            'inference': 'real adapter logic with synthetic MockTransport responses; no remote model execution or measured monetary cost',
            'interruption': 'committed bounded batch, connection closed, fresh-connection resume; no process kill or durability/crash claim'},
        'repeats': args.repeats, 'cases': [], 'phases': {}, 'errors': [], 'valid': False}
    exit_code = 0
    try:
        measure(args, output)
        output['valid'] = True
    except Exception as error:
        exit_code = 1
        output['errors'].append({'type': type(error).__name__,
            'code': str(error) if isinstance(error, MeasurementFailure) else getattr(error, 'code', 'measurement_failed'),
            'details': 'No provider/request/response/DSN diagnostics exported.'})
    finally:
        after = runtime_manifest()
        output['runtime_sql_sha256_after'] = after
        output['git_after'] = git_state()
        output['runtime_changed_paths'] = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        if output['runtime_changed_paths'] or output['git_before']['head'] != output['git_after']['head']:
            output['valid'] = False
            exit_code = 1
            output['errors'].append({'code': 'runtime_changed_during_measurement'})
        output['finished_at'] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, default=str)+'\n')
    print(json.dumps({'valid': output['valid'], 'cases': len(output['cases']),
                      'error_codes': [e['code'] for e in output['errors']],
                      'runtime_changed_paths': output['runtime_changed_paths'], 'output': str(args.output)}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
