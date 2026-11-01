"""Filtered vector recall must survive a nearer, entirely ineligible ANN pool."""
import re
import hashlib
from pathlib import Path

import pytest

from agentic_rag import db, domains, embed, query_cache, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection


AXES = ('scope', 'domain', 'archived', 'expired', 'future', 'stale', 'model')
DIGEST = 'a' * 64
BASELINE = Path(__file__).parent / 'fixtures/vector-work-92/before-target.sql'
assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == '8a8c7da221b7f64c43281200cd6d9ba020c39a4180f340566fa4d7beb5176957'


def synthetic_vectors(texts, cfg):
    result = []
    for text in texts:
        marker = re.search(r'vmk(\d)x(\d{4})', text)
        assert marker, 'the fixture must never embed copied or unmarked content'
        vector = [0.0] * 1024
        vector[1 + int(marker[1])] = 1.0
        vector[0] = 0.02 + int(marker[2]) / 800
        result.append(vector)
    return result


@pytest.fixture(scope='module')
def gated_vectors(request):
    axis = request.param
    axis_index = AXES.index(axis)
    with pytest.MonkeyPatch.context() as patch, isolated_database(Config()) as cfg:
        patch.setattr(store, 'try_embed_texts', synthetic_vectors)
        patch.setattr(embed, 'try_embed_texts', synthetic_vectors)
        patch.setattr(query_cache, 'model_digest', lambda cfg: DIGEST)
        originals = {}
        with db.connect(cfg) as owner:
            domains.add_domain(owner, 'general')
            domains.add_domain(owner, 'foreign')
            # Exact oracle keeps B-tree/GIN and changes only the vector sort.
            # Disabling every index would turn RLS lookups into quadratic scans.
            for function, alias in (('hybrid_search_candidates', 'c'), ('contextual_search_candidates', 'x')):
                definition = re.search(r'CREATE OR REPLACE FUNCTION ' + function + r'\(.*?\$\$;',
                                       BASELINE.read_text(), re.S).group()
                definition = definition.replace('FUNCTION ' + function + '(', 'FUNCTION exact92_' + function + '(', 1)
                definition = definition.replace('SET hnsw.ef_search = 256 AS', 'SET hnsw.ef_search = 256 SET jit=off AS')
                definition = definition.replace('ORDER BY ' + alias + '.embedding <=> query_vec LIMIT 256',
                    'ORDER BY (' + alias + '.embedding <=> query_vec)+0 LIMIT 256')
                owner.execute(definition)
            originals[axis] = {'near': [], 'far': []}
            for group, indices in (('near', range(270)), ('far', range(300, 355))):
                for index in indices:
                    marker = f'vmk{axis_index}x{index:04}'
                    kwargs = {'domain': 'general', 'scope': 'global'}
                    if group == 'near' and axis == 'scope':
                        kwargs = {'domain': 'general', 'project': '/synthetic/other'}
                    elif group == 'near' and axis == 'domain':
                        kwargs['domain'] = 'foreign'
                    if group == 'near' and axis in ('expired', 'future'):
                        dates = ({'event_at': '2026-01-01T00:00:00Z',
                                  'expires_at': '2026-02-01T00:00:00Z'}
                                 if axis == 'expired' else {'event_at': '2027-01-01T00:00:00Z'})
                        saved = store.save_assertion(owner, cfg, entity=f'{axis} {marker}',
                            attribute='mode', value=marker,
                            evidence={'source_id': marker, 'role': 'user', 'quote': marker},
                            **kwargs, **dates)
                    else:
                        saved = store.save_document(owner, cfg, title=f'{axis} {marker}',
                            body=f'Synthetic observation {marker}.', dtype='reference',
                            status='archived' if group == 'near' and axis == 'archived' else 'active',
                            **kwargs)
                    row = owner.execute('SELECT title,body,domain,dtype FROM documents WHERE id=%s',
                                        (saved.doc_id,)).fetchone()
                    store.save_document(owner, cfg, **dict(row), doc_id=saved.doc_id, index_context=True)
                    originals[axis][group].append(str(saved.doc_id))
            owner.commit()
            # Deliberate stale/corrupt derived-index injection, not original writes.
            # The original document, evidence and gateway/audit history stay intact.
            owner.execute("""UPDATE chunk_contexts x SET source_hash='stale-'||x.source_hash
                FROM chunks c WHERE c.id=x.chunk_id AND c.document_id=ANY(%s::uuid[])""",
                (originals.get('stale', {}).get('near', []),))
            owner.execute("""UPDATE chunk_contexts x SET model_digest=%s FROM chunks c
                WHERE c.id=x.chunk_id AND c.document_id=ANY(%s::uuid[])""",
                ('b' * 64, originals.get('model', {}).get('near', [])))
            other_scope = owner.execute('SELECT project_scope FROM documents WHERE id=%s',
                                        (originals[axis]['near'][0],)).fetchone()['project_scope']
            for table in ('documents', 'chunks', 'chunk_contexts'):
                owner.execute(f'ANALYZE {table}')
            owner.commit()
        yield cfg, originals, other_scope


CASES = [(axis, mode) for axis in AXES for mode in ('restricted', 'filter', 'broad')]
CASES += [('expired', 'history'), ('future', 'later'), ('scope', 'capped'), ('stale', 'capped')]


@pytest.mark.parametrize('contextual', [False, True], ids=['raw', 'contextual'])
@pytest.mark.parametrize('gated_vectors,mode', CASES, indirect=['gated_vectors'], scope='module')
def test_hidden_nearest_vectors_do_not_starve_allowed_results(gated_vectors, contextual, mode):
    # Mutation: an HNSW scan limited to the nearest256 ends before any of the
    # 55 allowed originals. A speed gain must never turn the expected50 into0.
    cfg, originals, other_scope = gated_vectors
    axis = next(iter(originals))
    broad = mode in ('filter', 'broad')
    principal = Principal('gated-vector', 'owned', 'reader',
        frozenset({'general', 'foreign'} if broad else {'general'}), frozenset(),
        frozenset({'global', other_scope} if broad else {'global'}), frozenset())
    query = [0.0] * 1024
    query[1 + AXES.index(axis)] = 1.0
    args = ('unfindablevector92zz', '[' + ','.join(map(str, query)) + ']',
            'general' if mode == 'filter' else None, 150,
            ['global'] if mode == 'filter' else None,
            '2027-06-01T00:00:00Z' if mode == 'later' else '2026-11-01T00:00:00Z',
            mode == 'history')
    placeholders = '%s,%s::halfvec,%s,%s,%s,%s,%s'
    function = 'contextual_search_candidates' if contextual else 'hybrid_search_candidates'
    if contextual:
        args += (DIGEST,)
        placeholders += ',%s'
    near_allowed = ((axis in ('scope', 'domain') and mode == 'broad')
                    or (axis == 'expired' and mode == 'history')
                    or (axis == 'future' and mode == 'later')
                    or (axis in ('stale', 'model') and not contextual))
    expected_ids = originals[axis]['near' if near_allowed else 'far'][:50]
    with db.connect(cfg) as reader:
        reader.execute('SET jit=off')
        if mode == 'capped':
            reader.execute('SET hnsw.max_scan_tuples=1')
        reader.execute('SET ROLE rag_reader')
        apply_connection(reader, RequestScope(principal, cfg, True))
        statement = f'SELECT * FROM {function}({placeholders})'
        actual = reader.execute(statement, args).fetchall()
        exact = reader.execute(f'SELECT * FROM exact92_{function}({placeholders})', args).fetchall()
        # Hand-built literal cohort first; the exact-plan control cannot bless
        # a shared eligibility bug. Full records also check scores and order.
        assert [str(row['document_id']) for row in exact] == expected_ids
        assert actual == exact
        assert [str(row['document_id']) for row in actual] == expected_ids


@pytest.mark.parametrize('gated_vectors', ['scope'], indirect=True, scope='module')
def test_absent_iterative_capability_uses_exact_scoped_fallback(gated_vectors):
    # Simulate only capability discovery, not query results or an old binary.
    # The real migration branch and SQL functions execute on an isolated store.
    cfg, originals, _ = gated_vectors
    migration = (Path(__file__).resolve().parents[1] / 'sql/034_lexical_eligibility_work.sql').read_text()
    simulated_legacy = migration.replace('IF can_iterate THEN', 'IF false THEN')
    assert simulated_legacy != migration
    principal = Principal('gated-vector', 'owned', 'reader', frozenset({'general'}),
                          frozenset(), frozenset({'global'}), frozenset())
    query = '[0,1,' + ','.join(['0'] * 1022) + ']'
    args = ('unfindablevector92zz', query, None, 150, None, '2026-11-01T00:00:00Z', False)
    with db.connect(cfg) as owner:
        owner.execute('SET ROLE rag_reader')
        apply_connection(owner, RequestScope(principal, cfg, True))
        owner.execute('RESET ROLE')
        with owner.transaction(force_rollback=True):
            owner.execute(simulated_legacy)
            configs = owner.execute("SELECT proconfig FROM pg_proc WHERE proname IN ('hybrid_search_candidates','contextual_search_candidates')").fetchall()
            assert all('rag.iterative_vectors=off' in row['proconfig'] for row in configs)
            assert all(not any(setting.startswith('enable_') for setting in row['proconfig']) for row in configs)
            owner.execute('SET LOCAL ROLE rag_reader')
            for contextual in (False, True):
                name = 'contextual_search_candidates' if contextual else 'hybrid_search_candidates'
                suffix = ',%s' if contextual else ''
                rows = owner.execute(f'SELECT * FROM {name}(%s,%s::halfvec,%s,%s,%s,%s,%s{suffix})',
                                     args + ((DIGEST,) if contextual else ())).fetchall()
                assert [str(row['document_id']) for row in rows] == originals['scope']['far'][:50]
