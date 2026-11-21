"""Timestamps read back from PostgreSQL in a DST fold must equal their UTC input.

psycopg returns timestamptz in the session TimeZone. Inside the autumn fold
(Europe/Berlin, 2026-10-25 00:00-01:00Z and 01:00-02:00Z) Python's == between
datetimes with different tzinfo objects is always False (PEP 495).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agentic_rag import evidence, source_origin, store, validity
from agentic_rag.domains import seed_defaults

FOLD = '2026-10-25T00:32:37.612Z'
BERLIN = ZoneInfo('Europe/Berlin')


@pytest.fixture(autouse=True)
def berlin(conn, monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a: None)
    conn.execute("SET TimeZone='Europe/Berlin'")
    conn.commit()


def test_same_instant_ignores_tzinfo_and_handles_none():
    utc = validity.parse_time(FOLD)
    local = utc.astimezone(BERLIN)
    utc_fold1 = validity.parse_time('2026-10-25T01:32:37.612Z')
    local_fold1 = utc_fold1.astimezone(BERLIN)
    assert local != utc  # the PEP 495 inter-zone fold rule this guards against
    assert local_fold1 != utc_fold1
    assert local == local_fold1  # PEP 495 same-zone fold equality trap
    assert validity.same_instant(local, utc)
    assert validity.same_instant(local_fold1, utc_fold1)
    assert not validity.same_instant(local, local_fold1)
    assert validity.same_instant(FOLD, local)
    assert not validity.same_instant(local, utc + timedelta(microseconds=1))
    assert validity.same_instant(None, None)
    assert not validity.same_instant(None, utc)
    assert not validity.same_instant(utc, None)
    with pytest.raises(ValueError):
        validity.same_instant(datetime(2026, 10, 25), utc)
    with pytest.raises(ValueError):
        validity.same_instant(None, datetime(2026, 10, 25))


def test_database_round_trip_is_berlin_in_fold(conn):
    value = conn.execute('SELECT %s::timestamptz AS v', (validity.parse_time(FOLD),)).fetchone()['v']
    assert value.utcoffset() == timedelta(hours=2) and value.fold == 0
    assert value != validity.parse_time(FOLD)


def source(identity, quote):
    return {'source_id': identity, 'namespace': 'session:fold', 'role': 'user', 'quote': quote,
            'complete': True, 'timestamp': FOLD}


def test_reattaching_a_fold_hour_source_is_not_a_metadata_conflict(conn, cfg):
    first = store.save_claim(conn, cfg, title='TLS', body='Server uses TLS.', domain='general',
                             dtype='memory', project='/synthetic/a', claim_kind='stated',
                             evidence=[source('event1', 'Server uses TLS.')])
    second = store.save_claim(conn, cfg, title='Port', body='Server listens on 443.',
                              domain='general', dtype='memory', project='/synthetic/a',
                              claim_kind='stated',
                              evidence=[source('event1', 'Server listens on 443.')])
    assert first.doc_id != second.doc_id
    keys = {s['source_key'] for d in (first, second) for s in evidence.sources(conn, d.doc_id)}
    assert len(keys) == 1


def test_fold_hour_source_with_other_instant_still_conflicts(conn, cfg):
    store.save_claim(conn, cfg, title='TLS', body='Server uses TLS.', domain='general',
                     dtype='memory', project='/synthetic/a', claim_kind='stated',
                     evidence=[source('event1', 'Server uses TLS.')])
    moved = {**source('event1', 'Server listens on 443.'), 'timestamp': '2026-10-25T01:32:37.612Z'}
    with pytest.raises(ValueError, match='conflicting metadata'):
        store.save_claim(conn, cfg, title='Port', body='Server listens on 443.', domain='general',
                         dtype='memory', project='/synthetic/a', claim_kind='stated', evidence=[moved])


def put(conn, cfg, value, when=FOLD, **kw):
    # Evidence carries no source timestamp, so only the assertion time is in the fold.
    return store.save_assertion(conn, cfg, entity='server', attribute='port', value=value,
        event_at=when, evidence={'source_id': 'source-' + value + kw.pop('tag', ''),
        'role': 'user', 'quote': f'server port {value}'},
        project='/synthetic/a', domain='general', **kw)


def test_fold_hour_assertion_duplicate_is_reused(conn, cfg):
    one = put(conn, cfg, '7000', expires_at='2026-10-25T01:32:37.612Z')
    again = put(conn, cfg, '7000', expires_at='2026-10-25T01:32:37.612Z', tag='b')
    assert again.duplicate and again.doc_id == one.doc_id
    assert conn.execute('SELECT count(*) n FROM fact_assertions').fetchone()['n'] == 1


def test_fold_hour_replacement_at_same_time_goes_to_review(conn, cfg):
    put(conn, cfg, '7000')
    result = put(conn, cfg, '8000', relation='replacement')
    assert result.disposition == 'review'
    assert result.reason == 'conflicting values at the same event time'


def test_source_origin_quarantine_and_coverage_accept_fold_hour_sources(conn, cfg):
    store.save_claim(conn, cfg, title='TLS', body='Server uses TLS.', domain='general',
                     dtype='memory', project='/synthetic/a', claim_kind='stated',
                     evidence=[source('event1', 'Server uses TLS.')])
    conn.commit()
    sources = [{'source_id': 'event1', 'role': 'user', 'source_at': validity.parse_time(FOLD)}]
    preflight = source_origin._coverage(conn, 'session:fold', sources, {'event1': {}})
    conn.rollback()
    assert preflight['metadata_conflicts'] == []
    assert source_origin.quarantine(conn, 'session:fold', sources, proof='synthetic') == 1
    conn.commit()
    state = conn.execute("SELECT state FROM knowledge_sources WHERE source_id='event1'").fetchone()
    assert state['state'] == 'removed'
