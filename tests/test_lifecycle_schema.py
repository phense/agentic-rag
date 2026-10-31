"""RAG-066 T066-002: migration031 overlay, guard, grants/RLS and view-aware eligibility.

Direct INSERT/UPDATE here deliberately bypass the gateway: they prove that the
database itself rejects chains, cycles, identity edits and history rewrites from a
writer that does not use store.apply_lifecycle.
"""
import hashlib
import json

import psycopg
import pytest

from agentic_rag import db, store
from agentic_rag.benchmark import memory_lifecycle as fx

pytestmark = pytest.mark.usefixtures('conn')


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)


def raw_decision(c, member, target, operation='exact_duplicate', *, state=None, effective_at=None, proof='exact'):
    """Writer-shaped direct insert (no gateway checks, no locks)."""
    state = state or ('contested' if operation == 'contradiction' else 'active')
    key = hashlib.sha256(json.dumps([operation, member, target, state, str(effective_at)]).encode()).hexdigest()
    row = c.execute(
        "INSERT INTO lifecycle_decisions(action_key,operation,member_id,target_id,domain,project_scope,proof,reason,"
        " member_lv1,target_lv1,member_snapshot,target_snapshot,effective_at,state,created_by)"
        " SELECT %s,%s,m.id,t.id,m.domain,m.project_scope,%s,'test',rag_lifecycle_version(m.id),rag_lifecycle_version(t.id),"
        " rag_lifecycle_snapshot(m.id),rag_lifecycle_snapshot(t.id),%s,%s,'test'"
        " FROM documents m, documents t WHERE m.id=%s AND t.id=%s RETURNING id",
        (key, operation, proof, effective_at, state, member, target)).fetchone()
    c.execute("INSERT INTO lifecycle_events(decision_id,event,action_key,actor,reason,member_id,target_id,domain,project_scope)"
              " VALUES (%s,%s,%s,'test','test',%s,%s,'x','x')",
              (row['id'], 'recorded' if state == 'contested' else 'applied', key, member, member))
    return str(row['id'])


def eligible(c, doc, view=None, at=None, history=False):
    c.execute("SELECT set_config('rag_lifecycle.view',%s,true)", (view or '',))
    return c.execute("SELECT assertion_eligible(%s,COALESCE(%s::timestamptz,now()),%s) ok",
                     (doc, at, history)).fetchone()['ok']


def test_migration031_is_empty_additive_and_least_privilege(conn):
    tables = {r['relname']: r for r in conn.execute(
        "SELECT c.relname,c.relrowsecurity,(SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid"
        " AND p.polcmd='w' AND NOT p.polpermissive) guards FROM pg_class c"
        " WHERE c.relname IN ('lifecycle_decisions','lifecycle_events')")}
    assert set(tables) == {'lifecycle_decisions', 'lifecycle_events'}
    assert all(t['relrowsecurity'] and t['guards'] == 1 for t in tables.values())
    assert conn.execute("SELECT (SELECT count(*) FROM lifecycle_decisions)+(SELECT count(*) FROM lifecycle_events) n").fetchone()['n'] == 0
    privileges = {(r['grantee'], r['table_name'], r['privilege_type']) for r in conn.execute(
        "SELECT grantee,table_name,privilege_type FROM information_schema.role_table_grants"
        " WHERE table_name IN ('lifecycle_decisions','lifecycle_events') AND grantee IN ('rag_reader','rag_writer','PUBLIC')")}
    assert privileges == {('rag_reader', t, 'SELECT') for t in tables} | {
        ('rag_writer', t, p) for t in tables for p in ('SELECT', 'INSERT')}
    columns = {(r['grantee'], r['column_name']) for r in conn.execute(
        "SELECT grantee,column_name FROM information_schema.column_privileges WHERE table_name='lifecycle_decisions'"
        " AND privilege_type='UPDATE' AND grantee IN ('rag_reader','rag_writer')")}
    assert columns == {('rag_writer', 'state')}
    # Existing function signatures are redefined in place, never overloaded.
    assert conn.execute("SELECT count(*) n FROM pg_proc WHERE proname='assertion_eligible'").fetchone()['n'] == 1
    assert conn.execute("SELECT count(*) n FROM pg_proc WHERE proname='rag_pattern_current'").fetchone()['n'] == 1
    from agentic_rag.service.schema import validate_schema
    validate_schema(conn)


def test_guard_rejects_chains_cycles_and_identity_edits_from_a_direct_writer(cfg, conn):
    ids = fx.ingest(conn, cfg, {'M1', 'E1'})
    with db.connect(cfg, role='writer') as w:
        raw_decision(w, ids['M1-copy1'], ids['M1-canon'])
        w.commit()
        for member, target, code in [(ids['M1-canon'], ids['M1-copy1'], 'chain_conflict'),
                                     (ids['M1-canon'], ids['E1-keep'], 'chain_conflict'),
                                     (ids['M1-copy3'], ids['M1-copy1'], 'chain_conflict'),
                                     (ids['M1-copy1'], ids['E1-keep'], 'already_active')]:
            with pytest.raises(psycopg.errors.CheckViolation, match='lifecycle:' + code):
                raw_decision(w, member, target)
            w.rollback()
        decision = w.execute('SELECT id FROM lifecycle_decisions').fetchone()['id']
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # column grant: state only
            w.execute("UPDATE lifecycle_decisions SET state='corrected', member_id=%s WHERE id=%s", (ids['E1-copy'], decision))
        w.rollback()
        with db.connect(cfg, role='admin') as admin:  # even ALL privileges cannot move an identity
            with pytest.raises(psycopg.errors.CheckViolation, match='lifecycle:immutable_identity'):
                admin.execute("UPDATE lifecycle_decisions SET state='corrected', member_id=%s WHERE id=%s",
                              (ids['E1-copy'], decision))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w.execute("UPDATE lifecycle_decisions SET reason='rewritten' WHERE id=%s", (decision,))
        w.rollback()
        w.execute("UPDATE lifecycle_decisions SET state='corrected' WHERE id=%s", (decision,))
        w.commit()
        with pytest.raises(psycopg.errors.CheckViolation, match='lifecycle:invalid_transition'):
            w.execute("UPDATE lifecycle_decisions SET state='active' WHERE id=%s", (decision,))
        w.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w.execute('DELETE FROM lifecycle_events')
        w.rollback()
    conn.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match='append-only'):
        conn.execute("UPDATE lifecycle_events SET reason='x'")
    conn.rollback()


def test_guard_rejects_cross_scope_and_managed_anchors(cfg, conn):
    ids = fx.ingest(conn, cfg, {'S1', 'A1', 'Q1', 'S3'})
    with db.connect(cfg, role='writer') as w:
        for member, target, code in [(ids['S1-b'], ids['S1-a'], 'scope_mismatch'),
                                     (ids['A1-v1'], ids['A1-v2'], 'assertion_managed'),
                                     (ids['Q1-inferred'], ids['Q1-stated'], 'not_current'),
                                     (ids['S3-y'], ids['S3-x'], 'unknown_scope')]:
            with pytest.raises(psycopg.errors.CheckViolation):
                raw_decision(w, member, target)
            w.rollback()


def test_empty_overlay_and_decisions_leave_documents_and_ev1_untouched(cfg, conn):
    ids = fx.ingest(conn, cfg)

    def state():
        rows = conn.execute("SELECT id,rag_document_version(id) ev1,md5(to_jsonb(d)::text) row FROM documents d ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    before = state()
    # Empty overlay: the redefined predicate equals the 030 base for every document,
    # current and legacy-history, now and at a past time.
    mismatches = conn.execute(
        "SELECT count(*) n FROM documents d, (VALUES (now(),false),(now(),true),('2026-04-01'::timestamptz,false)) t(at,h)"
        " WHERE assertion_eligible(d.id,t.at,t.h) IS DISTINCT FROM rag_assertion_eligible_base(d.id,t.at,t.h)").fetchone()['n']
    assert mismatches == 0
    with db.connect(cfg, role='writer') as w:
        raw_decision(w, ids['E1-copy'], ids['E1-keep'])
        raw_decision(w, ids['P1-old'], ids['P1-new'], 'replacement', proof='event_order', effective_at='2026-06-01T08:00:00Z')
        w.commit()
    conn.commit()
    assert state() == before


def test_view_aware_predicate_follows_operation_semantics(cfg, conn):
    ids = fx.ingest(conn, cfg, {'E1', 'P1', 'C1'})
    with db.connect(cfg, role='writer') as w:
        raw_decision(w, ids['E1-copy'], ids['E1-keep'])
        raw_decision(w, ids['P1-old'], ids['P1-new'], 'replacement', proof='event_order', effective_at='2026-06-01T08:00:00Z')
        raw_decision(w, ids['C1-a'], ids['C1-b'], 'contradiction', proof='judgement')
        w.commit()
    conn.commit()
    expect = {  # (doc, view, at, history) -> eligible
        ('E1-copy', None, None, False): False, ('E1-copy', 'current', None, False): False,
        ('E1-copy', 'include_merged', None, False): True, ('E1-copy', 'historical', None, False): True,
        ('E1-copy', None, None, True): True,  # omitted legacy history keeps its contract
        ('E1-keep', None, None, False): True,
        ('P1-old', None, None, False): False, ('P1-old', 'include_merged', None, False): False,
        ('P1-old', 'historical', None, False): True, ('P1-old', 'current', '2026-04-01T00:00:00Z', False): True,
        ('C1-a', None, None, False): True, ('C1-b', None, None, False): True,
    }
    for (key, view, at, history), wanted in expect.items():
        assert eligible(conn, ids[key], view, at, history) is wanted, (key, view, at, history)
        conn.rollback()


def test_duplicate_staleness_and_replacement_persistence(cfg, conn):
    ids = fx.ingest(conn, cfg, {'D1', 'G1'})
    with db.connect(cfg, role='writer') as w:
        raw_decision(w, ids['D1-copy'], ids['D1-keep'])
        raw_decision(w, ids['G1-old'], ids['G1-new'], 'replacement', proof='event_order', effective_at='2026-02-05T08:00:00Z')
        w.commit()
    conn.commit()
    assert not eligible(conn, ids['D1-copy']) and not eligible(conn, ids['G1-old'])
    conn.rollback()
    # Content ABA on the member: same text again, but updated_at moved -> stale -> visible.
    for body in ('Plotter note under edit', 'The plotter is loaded with A0 rolls.'):
        store.save_document(conn, cfg, doc_id=ids['D1-copy'], title='Plotter paper size', body=body,
                            domain='general', dtype='memory')
    assert eligible(conn, ids['D1-copy'])
    conn.rollback()
    # Replacement target refuted and purged: the replaced value stays hidden.
    store.review_claim(conn, ids['G1-new'], state='refuted', reason='wrong server')
    conn.execute('DELETE FROM documents WHERE id=%s', (ids['G1-new'],))  # admin purge
    conn.commit()
    assert not eligible(conn, ids['G1-old'])
    assert eligible(conn, ids['G1-old'], 'historical')
    conn.rollback()
    assert conn.execute('SELECT count(*) n FROM lifecycle_decisions').fetchone()['n'] == 2
