"""Characterize source permissions before a plan-only SQL helper refactor.

Catches cached authorization decisions, a dropped all-dependents check, a
session-prefix shortcut and changed NULL semantics on reused connections.
"""
from pathlib import Path
import hashlib
import json

import pytest

from agentic_rag import db, store
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import RequestScope, apply_connection, request_scope


def principal(domains=('alpha',), projects=('/projects/a',), *, readonly=False):
    return Principal('alice', 'vm1', 'one', frozenset(domains),
                     frozenset() if readonly else frozenset(domains),
                     frozenset(projects), frozenset() if readonly else frozenset(projects))


@pytest.fixture(params=['frozen_baseline', 'current'])
def sources(monkeypatch, request):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    with isolated_database(Config()) as cfg:
        with db.connect(cfg) as conn:
            frozen = Path(__file__).parents[1]/'fixtures/source-guard-plan'
            original = (frozen/'before.sql').read_bytes()
            assert hashlib.sha256(original).hexdigest() == json.loads((frozen/'FROZEN.json').read_text())['before_sha256']
            if request.param == 'frozen_baseline':
                conn.execute(original.decode().replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
            for name in ('alpha', 'beta'):
                conn.execute('INSERT INTO domains(name) VALUES (%s)', (name,))
            def save(title, domain, project, events):
                return store.save_claim(conn, cfg, title=title, body=title+' synthetic statement',
                    domain=domain, dtype='memory', project=project, claim_kind='stated',
                    evidence=[{'namespace': 'session:'+name, 'source_id': 'event',
                               'quote': name+' synthetic statement', 'role': 'user',
                               'complete': True} for name in events])
            own = save('own', 'alpha', '/projects/a', ('shared', 'alpha'))
            foreign = save('foreign', 'beta', '/projects/b', ('shared', 'beta'))
            keys = {r['namespace'].split(':', 1)[1]: r['source_key'] for r in
                    conn.execute('SELECT namespace,source_key FROM knowledge_sources')}
        yield cfg, keys, own, foreign


def allowed(conn, key, namespace):
    return conn.execute('SELECT public.rag_service_source_write(%s,%s) ok',
                        (key, namespace)).fetchone()['ok']


def test_same_connection_rechecks_scopes_and_readonly_after_plan_warmup(sources):
    cfg, keys, *_ = sources
    cases = [
        (principal(), (False, True, False), {'shared', 'alpha'}),
        (principal(('beta',), ('/projects/b',)), (False, False, True), {'shared', 'beta'}),
        (principal(('*',), ('*',)), (True, True, True), {'shared', 'alpha', 'beta'}),
        (principal(readonly=True), (False, False, False), {'shared', 'alpha'}),
        (principal(projects=('/projects/revoked',)), (False, False, False), set()),
    ]
    with db.connect(cfg, role='reader') as conn:
        for _ in range(8):
            for who, expected, visible in cases:
                apply_connection(conn, RequestScope(who, cfg, who.readonly))
                assert tuple(allowed(conn, keys[name], 'session:'+name)
                             for name in ('shared', 'alpha', 'beta')) == expected
                seen = {r['source_key'] for r in conn.execute('SELECT source_key FROM knowledge_sources')}
                assert seen == {keys[name] for name in visible}


def test_namespace_unknown_and_null_parameters_keep_three_valued_semantics(sources):
    cfg, keys, *_ = sources
    who = principal()
    own_namespace = 'svc1:'+who.namespace+':event'
    with db.connect(cfg, role='reader') as conn:
        apply_connection(conn, RequestScope(who, cfg, False))
        for _ in range(12):
            assert allowed(conn, 'absent-source', own_namespace) is True
            assert allowed(conn, 'absent-source', 'svc1:someone-else:event') is False
            assert allowed(conn, 'absent-source', None) is None
            assert allowed(conn, None, None) is None
            # Session ownership never overrides a foreign dependent.
            assert allowed(conn, keys['shared'], own_namespace) is False
        conn.execute("SELECT set_config('rag_service.active','0',false)")
        assert allowed(conn, None, None) is True
        conn.execute("SELECT set_config('rag_service.active','1',false)")
        assert allowed(conn, None, None) is None


def test_new_foreign_dependent_invalidates_warmed_permission(sources):
    cfg, keys, *_ = sources
    with db.connect(cfg, role='reader') as reader:
        apply_connection(reader, RequestScope(principal(), cfg, False))
        for _ in range(12):
            assert allowed(reader, keys['alpha'], 'session:alpha') is True
        reader.commit()
        with db.connect(cfg) as conn:
            store.save_claim(conn, cfg, title='second foreign', body='A new synthetic dependent',
                domain='beta', dtype='memory', project='/projects/b', claim_kind='stated',
                evidence=[{'namespace': 'session:alpha', 'source_id': 'event',
                           'quote': 'alpha synthetic statement', 'role': 'user', 'complete': True}])
        assert allowed(reader, keys['alpha'], 'session:alpha') is False


def test_source_write_still_requires_every_dependent(sources):
    cfg, keys, *_ = sources
    with request_scope(principal(), cfg):
        with pytest.raises(ValueError, match='source not found'):
            with db.connect(cfg, role='writer') as conn:
                store.set_source_state(conn, keys['shared'], state='removed', reason='not all writable')
    with request_scope(principal(('*',), ('*',)), cfg):
        with db.connect(cfg, role='writer') as conn:
            store.set_source_state(conn, keys['shared'], state='removed', reason='all writable')
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT state FROM knowledge_sources WHERE source_key=%s',
                            (keys['shared'],)).fetchone()['state'] == 'removed'
        assert conn.execute('SELECT count(*) n FROM source_history WHERE source_key=%s',
                            (keys['shared'],)).fetchone()['n'] == 1


def test_helper_keeps_definer_scope_and_execute_boundary(sources):
    cfg, *_ = sources
    with db.connect(cfg) as conn:
        row = conn.execute("""SELECT prosecdef,provolatile,proisstrict,proparallel,proconfig,
            EXISTS(SELECT 1 FROM pg_catalog.aclexplode(proacl) a
                   WHERE a.grantee=0 AND a.privilege_type='EXECUTE') public_execute
            FROM pg_catalog.pg_proc
            WHERE oid='public.rag_service_source_write(text,text)'::regprocedure""").fetchone()
        assert row == {'prosecdef': True, 'provolatile': 's', 'proisstrict': False,
                       'proparallel': 'u', 'proconfig': ['search_path=pg_catalog, public, pg_temp'],
                       'public_execute': False}
        for role in ('rag_reader', 'rag_writer', 'rag_admin'):
            assert conn.execute("""SELECT pg_catalog.has_function_privilege(%s,
                'public.rag_service_source_write(text,text)','EXECUTE') ok""", (role,)).fetchone()['ok']
