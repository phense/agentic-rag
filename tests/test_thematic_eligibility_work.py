"""Theme membership must not evaluate truth for unrelated or repeated chunks."""
import hashlib
from pathlib import Path

import pytest

from agentic_rag import db, domains, lifecycle, store, thematic
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection

BEFORE = Path(__file__).parent / 'fixtures/thematic-work-92/before.sql'
assert hashlib.sha256(BEFORE.read_bytes()).hexdigest() == 'c358ec24e25f730dfe2cf8d7ff312a2b855ccbb763d57358ac8e63c0ebbc5e22'


@pytest.fixture(scope='module')
def theme_workload():
    with pytest.MonkeyPatch.context() as patch, isolated_database(Config()) as cfg:
        patch.setattr(store, 'try_embed_texts', lambda *a: None)
        with db.connect(cfg) as owner:
            domains.add_domain(owner, 'general')
            expected = []
            for i in range(62):
                matching = i >= 60
                body = (''.join(f'## Part {j}\n\n' + 'Maintenance inspection report. ' * 50 + '\n\n'
                                for j in range(8)) if matching else 'Unrelated engineering background manual.')
                saved = store.save_document(owner, cfg, title=f'Manual {i}', body=body,
                    domain='general', dtype='reference', scope='global')
                if matching:
                    expected.append(saved.doc_id)
            for table in ('documents', 'chunks'):
                owner.execute(f'ANALYZE {table}')
            owner.commit()
        yield cfg, set(expected)


@pytest.mark.parametrize('memoize', ['on', 'off'])
@pytest.mark.parametrize('history', [False, True])
@pytest.mark.parametrize('query', ['unfindablequasar92', 'maintenance inspection'])
def test_theme_truth_work_follows_distinct_matching_documents(theme_workload, query, history, memoize):
    # Mutation: a documents-first join evaluates truth for every unrelated
    # document; per-chunk gating repeats the same work for long matching notes.
    cfg, expected = theme_workload
    with db.connect(cfg) as reader:
        reader.execute("SET track_functions='all'")
        reader.execute('SET enable_memoize=' + memoize)
        reader.execute('SET ROLE rag_reader')
        principal = Principal('theme-probe', 'owned', 'reader', frozenset({'general'}),
                              frozenset(), frozenset({'global'}), frozenset())
        apply_connection(reader, RequestScope(principal, cfg, True))
        with lifecycle.view_scope(reader, 'current'):
            scopes = ['global']
            params = dict(query=query, scopes=scopes, domain=None, history=history, key='synthetic')
            baseline = reader.execute(BEFORE.read_text(), params).fetchone()
            candidates = baseline['candidates']
            for item in candidates:
                item.pop('rank')
                item['source_version'] = thematic._digest(item)
            counter = "SELECT COALESCE(pg_stat_get_xact_function_calls('claim_eligible(uuid)'::regprocedure),0) n"
            before = reader.execute(counter).fetchone()['n']
            actual = thematic._state(reader, query, scopes, None, history, 'synthetic')
            calls = reader.execute(counter).fetchone()['n'] - before
        assert actual == (baseline['cache'], candidates[:24], len(candidates) > 24)
        assert {x['document_id'] for x in actual[1]} == (expected if query == 'maintenance inspection' else set())
        # Current assertion eligibility rechecks claim trust as well as the
        # explicit theme guard; at most four calls per distinct matching doc.
        assert calls <= (8 if expected and query == 'maintenance inspection' else 0), {'calls': calls}
