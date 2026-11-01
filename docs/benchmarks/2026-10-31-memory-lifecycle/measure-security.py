"""Compare suppression overhead on one owned store without concurrent pytest.

The prior function is extracted from reviewed commit 1fc0628. Only the function
in the disposable database is changed; the checkout and production are untouched.
Run from the repository root with PGPORT=55460 and PGHOST/PGSERVICE unset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from agentic_rag import db, lifecycle, search, store  # noqa: E402
from agentic_rag.benchmark import memory_lifecycle as fx  # noqa: E402
from agentic_rag.benchmark.database import isolated_database  # noqa: E402
from agentic_rag.config import Config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    other_pytest = []
    for process in Path('/proc').iterdir():
        if process.name.isdigit():
            try:
                parts = (process / 'cmdline').read_bytes().split(b'\0')
                if any(p == b'pytest' or p.endswith(b'/pytest') for p in parts):
                    other_pytest.append(int(process.name))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
    if other_pytest:
        raise RuntimeError(f'wait for pytest to finish: {other_pytest}')
    store.try_embed_texts = search.try_embed_texts = lambda *a, **k: None
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    prior_sql = subprocess.check_output(['git', 'show', '1fc0628:sql/031_memory_lifecycle.sql'], text=True)
    prior = re.search(r'CREATE FUNCTION public\.rag_lifecycle_hidden\(.*?\$\$;', prior_sql, re.S).group()
    prior = prior.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1)
    paths = ('agentic_rag/lifecycle.py', 'sql/031_memory_lifecycle.sql')
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    result = {'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'source_tree_clean': not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip(),
              'prior_revision': '1fc062832e4d40051ad3a5833077e4b39d77512e',
              'source_hashes': hashes, 'other_pytest_pids': other_pytest,
              'load_average_start': os.getloadavg(), 'provider_calls': 0,
              'pairs': 150, 'rounds': 7, 'phases': {},
              'limits': ['synthetic data, owner-role comparison, PostgreSQL on one shared host',
                         'no competing pytest or review benchmark; other system load is uncontrolled',
                         'prior function is a pre-security-correction comparator, not an approved fallback',
                         'timings include local SQL/rollback or lexical-search overhead; not production latency']}
    with isolated_database(cfg) as owned:
        name = owned.db_name
        with db.connect(owned) as conn:
            fx.ingest(conn, owned)
            made = []
            for n in range(150):
                pair = [store.save_document(conn, owned, title=f'Note {n}',
                            body=f'Widget {n} needs gasket model G{n}.', domain='general',
                            dtype='memory', project=fx.project('a')).doc_id for _ in range(2)]
                made.append((pair[1], pair[0]))
            conn.commit()
            current = conn.execute("SELECT pg_get_functiondef('public.rag_lifecycle_hidden(uuid,timestamptz,boolean)'::regprocedure) d").fetchone()['d']
            result['postgres'] = conn.execute('SELECT version() v').fetchone()['v']
            result['documents'] = conn.execute('SELECT count(*) n FROM documents').fetchone()['n']
            conn.rollback()
            for phase in ('empty_overlay', '150_merged_members'):
                if phase != 'empty_overlay':
                    for member, target in made:
                        seen = lifecycle.preview(conn, member, target)
                        conn.rollback()
                        store.apply_lifecycle(conn, owned, member=member, target=target,
                            operation='exact_duplicate', expected_member_version=seen['member']['version'],
                            expected_target_version=seen['target']['version'], reason='scale', actor='cli')
                conn.execute('ANALYZE'); conn.commit()
                series = {tag: {k: [] for k in ('eligibility_count_ms', 'lexical_ms', 'nonmember_10000_ms')}
                          for tag in ('current', 'prior')}
                counts = {}
                for iteration in range(7):
                    order = ('current', 'prior') if iteration % 2 == 0 else ('prior', 'current')
                    for tag in order:
                        conn.execute(current if tag == 'current' else prior); conn.commit()
                        info = conn.execute("SELECT prosecdef,proconfig FROM pg_proc WHERE oid='public.rag_lifecycle_hidden(uuid,timestamptz,boolean)'::regprocedure").fetchone()
                        assert info['prosecdef'] is (tag == 'current')
                        assert (info['proconfig'] is not None) is (tag == 'current')
                        conn.rollback()
                        started = time.perf_counter()
                        counts[tag] = conn.execute('SELECT count(*) n FROM documents WHERE assertion_eligible(id)').fetchone()['n']
                        conn.rollback()
                        series[tag]['eligibility_count_ms'].append((time.perf_counter() - started) * 1000)
                        started = time.perf_counter()
                        search.search(conn, owned, 'widget gasket', domain='general', k=8, project=fx.project('a'),
                                      strategy='lexical', rerank_mode='off', context_mode='off')
                        conn.rollback()
                        series[tag]['lexical_ms'].append((time.perf_counter() - started) * 1000)
                        started = time.perf_counter()
                        assert conn.execute('SELECT count(*) n FROM generate_series(1,10000) WHERE rag_lifecycle_hidden(gen_random_uuid())').fetchone()['n'] == 0
                        conn.rollback()
                        series[tag]['nonmember_10000_ms'].append((time.perf_counter() - started) * 1000)
                assert counts['current'] == counts['prior']
                result['phases'][phase] = {tag: {metric: {'median_ms': round(statistics.median(values), 3),
                                                          'samples_ms': [round(v, 3) for v in values]}
                                                for metric, values in data.items()}
                                           for tag, data in series.items()}
                result['phases'][phase]['eligible_count'] = counts['current']
                conn.execute(current); conn.commit()
                assert conn.execute("SELECT prosecdef FROM pg_proc WHERE oid='public.rag_lifecycle_hidden(uuid,timestamptz,boolean)'::regprocedure").fetchone()['prosecdef']
                conn.rollback()
    with db.connect(cfg, dbname='postgres') as admin:
        assert admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone() is None
    result['owned_database_removed'] = True
    result['source_hashes_unchanged'] = hashes == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    assert result['source_hashes_unchanged']
    result['load_average_end'] = os.getloadavg()
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('source_revision', 'documents', 'pairs', 'rounds', 'phases', 'owned_database_removed')}))


if __name__ == '__main__':
    main()
