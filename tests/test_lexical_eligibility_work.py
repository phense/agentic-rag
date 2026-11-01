"""A selective lexical query must not run truth gates on unrelated documents."""
import hashlib
import json
from pathlib import Path
import re

import pytest

from agentic_rag import db, domains, embed, evidence, lifecycle, query_cache, store
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


@pytest.fixture(scope='module')
def parity_database(lexical_database):
    cfg = lexical_database
    with db.connect(cfg) as owner:
        # Executable published SQL is the comparison arm, not an expectation
        # computed from the changed implementation or its helper functions.
        files = ('013_retrieval_quality.sql', '016_filter_aware_search.sql',
                 '015_contextual_chunks.sql', '016_filter_aware_search.sql')
        for name, filename in zip(FUNCTIONS, files):
            source = (db.SQL_DIR / filename).read_text()
            original = re.search(r'CREATE FUNCTION ' + name + r'\(.*?\$\$;', source, re.S).group()
            owner.execute(original.replace('CREATE FUNCTION ' + name, 'CREATE FUNCTION before92_' + name, 1))
        owner.commit()
        domains.add_domain(owner, 'foreign-domain')
        ids = {}
        fields = dict(body='boundarymarker original observation.', domain='general', dtype='memory', scope='global')
        for key, overrides in (
            ('visible', {}), ('archived', {'status': 'archived'}),
            ('foreign-project', {'scope': None, 'project': '/synthetic/foreign'}),
            ('foreign-domain', {'domain': 'foreign-domain'}),
            ('member', {}), ('canonical', {}),
        ):
            ids[key] = store.save_document(owner, cfg, title='Boundary ' + key, **(fields | overrides)).doc_id
        seen = lifecycle.preview(owner, ids['member'], ids['canonical'], operation='semantic_duplicate')
        owner.rollback()
        store.apply_lifecycle(owner, cfg, member=ids['member'], target=ids['canonical'],
                              operation='semantic_duplicate', expected_member_version=seen['member']['version'],
                              expected_target_version=seen['target']['version'], reviewed=True,
                              reason='Synthetic parity fixture', actor='cli')
        for key, options in (
            ('withdrawn', {}),
            ('expired', {'expires_at': '2026-02-01T00:00:00Z'}),
            ('future', {'event_at': '2027-01-01T00:00:00Z'}),
        ):
            ids[key] = store.save_assertion(owner, cfg, entity='boundarymarker ' + key, attribute='mode',
                value='blue', domain='general', scope='global', event_at=options.get('event_at', '2026-01-01T00:00:00Z'),
                expires_at=options.get('expires_at'), evidence={'source_id': key, 'role': 'user', 'quote': 'blue'}).doc_id
        store.set_source_state(owner, evidence.sources(owner, ids['withdrawn'])[0]['source_key'],
                               state='removed', reason='Synthetic withdrawal')
        # A replacement supported only by quarantined generated prose must not
        # hide the true original (schema033), even through a historical reader.
        for key, value, at in (('blue', 'blue', '2026-01-01T00:00:00Z'),
                               ('generated-red', 'red', '2026-02-01T00:00:00Z')):
            ids[key] = store.save_assertion(owner, cfg, entity='boundarymarker sensor', attribute='mode',
                value=value, domain='general', scope='global', event_at=at,
                relation='replacement' if key == 'generated-red' else 'assertion',
                evidence={'source_id': key, 'role': 'user', 'quote': value}).doc_id
        assert not owner.execute('SELECT assertion_eligible(%s) ok', (ids['blue'],)).fetchone()['ok']
        store.set_source_state(owner, evidence.sources(owner, ids['generated-red'])[0]['source_key'],
                               state='removed', reason='native_generated_origin:synthetic')
        assert owner.execute('SELECT assertion_eligible(%s) ok', (ids['blue'],)).fetchone()['ok']
        for doc in owner.execute('SELECT id,title,body,domain,dtype FROM documents').fetchall():
            store.save_document(owner, cfg, **{k: doc[k] for k in ('title', 'body', 'domain', 'dtype')},
                                doc_id=str(doc['id']), index_context=True)
        owner.commit()
    return cfg, ids


@pytest.mark.parametrize('function', FUNCTIONS)
@pytest.mark.parametrize('query', ['unfindablequasar', 'quasar observatory', 'Pflanze Garten',
                                  'background', 'boundarymarker'])
@pytest.mark.parametrize('view,at,history', [
    ('current', '2026-11-01T00:00:00Z', False),
    ('include_merged', '2026-11-01T00:00:00Z', False),
    ('current', '2026-01-15T00:00:00Z', False),
    ('historical', '2026-11-01T00:00:00Z', True),
])
def test_reader_results_scores_and_order_match_published_sql(parity_database, function, query, view, at, history):
    cfg, ids = parity_database
    with db.connect(cfg) as reader:
        reader.execute('SET ROLE rag_reader')
        principal = Principal('parity-probe', 'owned', 'reader', frozenset({'general'}),
                              frozenset(), frozenset({'global'}), frozenset())
        apply_connection(reader, RequestScope(principal, cfg, True))
        with lifecycle.view_scope(reader, view):
            args = (query, None, None, 150, None, at, history)
            before = reader.execute(f'SELECT * FROM before92_{function}(%s,%s::halfvec,%s,%s,%s,%s,%s)', args).fetchall()
            after = reader.execute(f'SELECT * FROM {function}(%s,%s::halfvec,%s,%s,%s,%s,%s)', args).fetchall()
        assert after == before  # Every field, score, chunk id and position.
        if query == 'boundarymarker' and view == 'current':
            expected = {'visible', 'canonical', 'blue'}
            if at == '2026-01-15T00:00:00Z':
                expected.add('expired')
            assert {str(row['document_id']) for row in after} == {ids[key] for key in expected}
