"""Generic vector plans must preserve results without scanning every document."""
import re
import hashlib
from pathlib import Path

import pytest

from agentic_rag import db, domains, embed, query_cache, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection


FUNCTIONS = ('hybrid_search_candidates', 'contextual_search_candidates')
DIGEST = 'a' * 64
HIDDEN = 'rag_lifecycle_hidden(uuid,timestamptz,boolean)'
BASELINE = Path(__file__).parent / 'fixtures/vector-work-92/before-target.sql'
assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == '8a8c7da221b7f64c43281200cd6d9ba020c39a4180f340566fa4d7beb5176957'


def vectors(texts, cfg):
    # Only the external inference boundary is replaced. Keep distinct distances
    # and real HNSW, truth gates, scoped SQL and gateway writes in the test.
    return [[1.0, int(re.search(r'vector-marker-(\d+)', text)[1]) / 800]
            + [0.0] * 1022 for text in texts]


@pytest.fixture(scope='module')
def vector_database():
    with pytest.MonkeyPatch.context() as patch, isolated_database(Config()) as cfg:
        patch.setattr(store, 'try_embed_texts', vectors)
        patch.setattr(embed, 'try_embed_texts', vectors)
        patch.setattr(query_cache, 'model_digest', lambda cfg: DIGEST)
        with db.connect(cfg) as owner:
            domains.add_domain(owner, 'general')
            for function in FUNCTIONS:
                definition = re.search(r'CREATE OR REPLACE FUNCTION ' + function + r'\(.*?\$\$;',
                    BASELINE.read_text(), re.S).group()
                owner.execute(definition.replace('FUNCTION ' + function + '(',
                    'FUNCTION vector_before92_' + function + '(', 1))
            for i in range(1, 601):
                saved = store.save_document(owner, cfg, title=f'vector-marker-{i:04}',
                    body=f'Synthetic independent vector-marker-{i:04} observation.',
                    domain='general', dtype='reference', scope='global')
                store.save_document(owner, cfg, title=f'vector-marker-{i:04}',
                    body=f'Synthetic independent vector-marker-{i:04} observation.',
                    domain='general', dtype='reference', doc_id=saved.doc_id,
                    index_context=True)
            for table in ('documents', 'chunks', 'chunk_contexts'):
                owner.execute(f'ANALYZE {table}')
            owner.commit()
        yield cfg


@pytest.mark.parametrize('function', FUNCTIONS)
def test_generic_vector_work_is_bounded_by_ann_candidates(vector_database, function):
    # Mutation: flattening the correlated document gate lets the generic plan
    # check all600 originals even though it returns only50 ranked candidates.
    with db.connect(vector_database) as reader:
        assert reader.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()['rolsuper'], \
            'the vector-work regression requires real PostgreSQL function counters'
        reader.execute("SET track_functions='all'")
        reader.execute('SET jit=off')
        reader.execute('SET plan_cache_mode=force_generic_plan')
        reader.execute('SET ROLE rag_reader')
        principal = Principal('vector-probe', 'owned', 'reader', frozenset({'general'}),
                              frozenset(), frozenset({'global'}), frozenset())
        apply_connection(reader, RequestScope(principal, vector_database, True))
        args = ('unfindablevector92', '[1,0,' + ','.join(['0'] * 1022) + ']', None,
                150, None, '2026-11-01T00:00:00Z', False)
        placeholders = '%s,%s::halfvec,%s,%s,%s,%s,%s'
        if function.startswith('contextual'):
            args += (DIGEST,)
            placeholders += ',%s'
        expected = reader.execute(f'SELECT * FROM vector_before92_{function}({placeholders})', args).fetchall()
        before = reader.execute('SELECT COALESCE(pg_stat_get_xact_function_calls(%s::regprocedure),0) n',
                                (HIDDEN,)).fetchone()['n']
        actual = reader.execute(f'SELECT * FROM {function}({placeholders})', args).fetchall()
        after = reader.execute('SELECT COALESCE(pg_stat_get_xact_function_calls(%s::regprocedure),0) n',
                               (HIDDEN,)).fetchone()['n']
        assert actual == expected  # Full rows, scores, order and exact original ids.
        assert [row['slug'] for row in actual[:3]] == ['vector-marker-0001', 'vector-marker-0002', 'vector-marker-0003']
        assert len(actual) == 50
        assert after - before <= 384, {'function': function, 'calls': after-before, 'limit': 384}
