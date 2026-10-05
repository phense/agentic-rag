"""Atomic fact writes and temporal readers must respect exact domain boundaries."""
from concurrent.futures import ThreadPoolExecutor
import itertools

import pytest
from agentic_rag import db, domains, entities, search, store, validity

PROJECT = '/synthetic/domain-facts'


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    domains.seed_defaults(conn)
    domains.add_domain(conn, 'programming')
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    monkeypatch.setattr(search, 'try_embed_texts', lambda *a: None)


def put(conn, cfg, domain, value='running', when='2026-01-01T00:00:00Z', **kwargs):
    return store.save_assertion(conn, cfg, entity='Public server', attribute='status', value=value,
        domain=domain, project=PROJECT, event_at=when,
        evidence={'source_id':domain+'-'+value+'-'+when, 'role':'user',
                  'quote':'Public server status is now '+value}, **kwargs)


@pytest.mark.parametrize('order', [('general', 'programming'), ('programming', 'general')])
@pytest.mark.parametrize('values', [('running', 'running'), ('running', 'stopped')])
def test_equal_time_cross_domain_facts_are_distinct_and_accepted(conn, cfg, order, values):
    records = [put(conn, cfg, domain, value) for domain, value in zip(order, values)]
    assert len({r.doc_id for r in records}) == 2
    assert all(r.disposition == 'accepted' and not r.duplicate for r in records)
    for domain, value, record in zip(order, values, records):
        assert put(conn, cfg, domain, value).doc_id == record.doc_id
        assert entities.read(conn, 'Public server', domain=domain, project=PROJECT)['facts'][0]['document_id'] == record.doc_id
        attached = conn.execute('SELECT count(*) n FROM assertion_sources WHERE document_id=%s', (record.doc_id,)).fetchone()['n']
        assert attached == 1


@pytest.mark.parametrize('order', list(itertools.permutations(['programming-old', 'general-old', 'general-new'])))
def test_replacement_never_suppresses_foreign_domain_current_or_history(conn, cfg, order):
    records = {}
    for case in order:
        domain = case.split('-')[0]
        new = case.endswith('new')
        records[case] = put(conn, cfg, domain, 'running' if new else 'stopped',
            '2026-02-01T00:00:00Z' if new else '2026-01-01T00:00:00Z',
            relation='replacement' if new else 'assertion')
    programming = records['programming-old'].doc_id
    general_new = records['general-new'].doc_id
    assert programming != records['general-old'].doc_id
    assert conn.execute('SELECT assertion_eligible(%s) eligible', (programming,)).fetchone()['eligible'] is True
    for domain, expected in [('programming', programming), ('general', general_new)]:
        hits, _ = search.search(conn, cfg, 'server', domain=domain, project=PROJECT, strategy='lexical')
        assert {h.document_id for h in hits} == {expected}
        assert [f['document_id'] for f in entities.read(conn, 'Public server', domain=domain, project=PROJECT)['facts']] == [expected]
    before, _ = search.search(conn, cfg, 'server', domain='programming', project=PROJECT,
                             strategy='lexical', as_of='2026-01-15T00:00:00Z')
    assert [h.document_id for h in before] == [programming]
    history, _ = search.search(conn, cfg, 'server', domain='general', project=PROJECT, strategy='lexical', history=True)
    assert {h.document_id for h in history} == {records['general-old'].doc_id, general_new}
    assert conn.execute('SELECT count(*) n FROM edges e JOIN documents s ON s.id=e.src_id '
                        'JOIN documents d ON d.id=e.dst_id WHERE s.domain<>d.domain '
                        "AND e.predicate IN ('supersedes','extends')").fetchone()['n'] == 0


@pytest.mark.parametrize('domains_pair, expected_count', [(('general', 'general'), 1), (('general', 'programming'), 2)])
def test_concurrent_writers_deduplicate_only_inside_domain(conn, cfg, domains_pair, expected_count):
    def writer(domain):
        with db.connect(cfg, role='writer') as writer_conn:
            return put(writer_conn, cfg, domain)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, domains_pair))
    assert len({r.doc_id for r in results}) == expected_count
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n'] == expected_count
    assert all(r.disposition == 'accepted' for r in results)


def test_expiry_does_not_reactivate_own_domain_or_expire_another(conn, cfg):
    original = put(conn, cfg, 'programming', 'stopped')
    put(conn, cfg, 'general', 'stopped')
    put(conn, cfg, 'general', 'running', '2026-02-01T00:00:00Z', relation='replacement', expires_at='2026-03-01T00:00:00Z')
    at = validity.parse_time('2026-04-01T00:00:00Z')
    eligible = conn.execute('SELECT a.document_id,d.domain FROM fact_assertions a JOIN documents d ON d.id=a.document_id '
                            'WHERE assertion_eligible(a.document_id,%s,false)', (at,)).fetchall()
    assert [(str(r['document_id']), r['domain']) for r in eligible] == [(original.doc_id, 'programming')]


def test_simultaneous_cross_domain_slug_allocation_keeps_gateway_atomic(conn, cfg, monkeypatch):
    """Force the real equal-title SELECT/INSERT race without replacing the gateway."""
    from threading import Barrier, local
    barrier, seen = Barrier(2), local()
    allocate = store._unique_slug
    def interleaved(connection, base):
        result = allocate(connection, base)
        if not getattr(seen, 'started', False):
            seen.started = True
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(store, '_unique_slug', interleaved)
    def writer(domain):
        with db.connect(cfg, role='writer') as writer_conn:
            writer_conn.execute("SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='8s'")
            return put(writer_conn, cfg, domain)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ['general', 'programming']))
    assert len({r.doc_id for r in results}) == 2
    assert {r.slug for r in results} == {'public-server-status', 'public-server-status-2'}
    assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n'] == 2
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='save_assertion'").fetchone()['n'] == 2
    assert conn.execute('SELECT count(*) n FROM assertion_sources').fetchone()['n'] == 2
