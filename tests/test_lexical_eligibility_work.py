"""A selective lexical query must not run truth gates on unrelated documents."""
import hashlib
import json
from pathlib import Path

import pytest

from agentic_rag import db, domains, embed, query_cache, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection


FIXTURE = Path(__file__).parent / 'fixtures/lexical-eligibility-92/workload.json'
assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == '081709346ddcee55ab7255d99e50e50a16b283f63777660b962d5b7a695887eb'
WORKLOAD = json.loads(FIXTURE.read_text())
FUNCTIONS = ('hybrid_search_candidates', 'hybrid_search_candidates_planned',
             'contextual_search_candidates', 'contextual_search_candidates_planned')
HIDDEN = 'rag_lifecycle_hidden(uuid,timestamptz,boolean)'


@pytest.fixture(scope='module')
def lexical_database():
    # Only inference is substituted. Real gateways, derived contexts, RLS and
    # PostgreSQL's actual function-call counters remain in the measured path.
    with pytest.MonkeyPatch.context() as patch, isolated_database(Config()) as cfg:
        patch.setattr(store, 'try_embed_texts', lambda texts, cfg: None)
        patch.setattr(embed, 'try_embed_texts', lambda texts, cfg: [[1.0] + [0.0] * 1023 for _ in texts])
        patch.setattr(query_cache, 'model_digest', lambda cfg: 'a' * 64)
        with db.connect(cfg) as owner:
            domains.add_domain(owner, 'general')
            records = [dict(title=WORKLOAD['background_title'].format(i=i),
                            body=WORKLOAD['background_body'].format(i=i))
                       for i in range(WORKLOAD['background_count'])] + WORKLOAD['documents']
            for record in records:
                fields = {key: record[key] for key in ('title', 'body')}
                saved = store.save_document(owner, cfg, **fields, domain='general', dtype='reference', scope='global')
                store.save_document(owner, cfg, **fields, domain='general', dtype='reference',
                                    doc_id=saved.doc_id, index_context=True)
            for table in ('documents', 'chunks', 'chunk_contexts'):
                owner.execute(f'ANALYZE {table}')
            owner.commit()
        yield cfg


@pytest.mark.parametrize('function', FUNCTIONS)
@pytest.mark.parametrize('case', WORKLOAD['queries'], ids=lambda case: case['query'])
def test_reader_lexical_work_is_bounded_by_matching_chunks(lexical_database, function, case):
    # Mutation: moving assertion_eligible back to a documents-first join leaves
    # result equality intact but executes it for all 162 unrelated originals.
    with db.connect(lexical_database) as reader:
        if not reader.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()['rolsuper']:
            pytest.skip('actual function work counters require a superuser test owner')
        reader.execute("SET track_functions = 'all'")
        reader.execute('SET ROLE rag_reader')
        principal = Principal('lexical-probe', 'owned', 'reader', frozenset({'general'}),
                              frozenset(), frozenset({'global'}), frozenset())
        apply_connection(reader, RequestScope(principal, lexical_database, True))
        before = reader.execute('SELECT COALESCE(pg_stat_get_xact_function_calls(%s::regprocedure),0) n',
                                (HIDDEN,)).fetchone()['n']
        rows = reader.execute(f'SELECT * FROM {function}(%s)', (case['query'],)).fetchall()
        after = reader.execute('SELECT COALESCE(pg_stat_get_xact_function_calls(%s::regprocedure),0) n',
                               (HIDDEN,)).fetchone()['n']
        assert [row['slug'] for row in rows] == case['slugs']
        assert after - before <= case['maximum_eligibility_calls'], {
            'function': function, 'eligibility_calls': after - before,
            'maximum': case['maximum_eligibility_calls'], 'matching_slugs': case['slugs']}
