"""RAG-067 T067-003: migration032 policy bindings, grants, RLS and atomic binding."""
import threading

import psycopg
import pytest

from agentic_rag import db, extraction_policy as ep, mining
from test_extraction_policy_fixtures import FIXTURES

pytestmark = pytest.mark.usefixtures('conn')
DOMAINS = ['programming', 'operations']


def bundle(name='policy-a.toml', project='/synthetic/team-a'):
    return ep.build_bundle(ep.load_file(FIXTURES / 'policies' / name), project, DOMAINS)


def test_migration032_is_additive_immutable_and_least_privilege(conn):
    table = conn.execute("""SELECT c.relrowsecurity,
        (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid AND starts_with(p.polname,'service_')) policies,
        (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid AND p.polcmd='w' AND NOT p.polpermissive) guards
        FROM pg_class c WHERE c.oid='public.extraction_policy_bindings'::regclass""").fetchone()
    assert table['relrowsecurity'] and table['policies'] >= 2 and table['guards'] == 1
    privileges = {(r['grantee'], r['privilege_type']) for r in conn.execute(
        "SELECT grantee,privilege_type FROM information_schema.role_table_grants"
        " WHERE table_name='extraction_policy_bindings' AND grantee IN ('rag_reader','rag_writer','PUBLIC')")}
    assert privileges == {('rag_reader', 'SELECT'), ('rag_writer', 'SELECT'), ('rag_writer', 'INSERT')}
    assert conn.execute("SELECT count(*) n FROM extraction_policy_bindings").fetchone()['n'] == 0
    from agentic_rag.service.schema import SCOPED_TABLES, validate_schema
    assert 'extraction_policy_bindings' in SCOPED_TABLES
    validate_schema(conn)


def test_bindings_reject_rewrites_bad_digests_and_oversized_snapshots(conn):
    b = bundle()
    conn.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                 " VALUES ('s','c',%s,%s,'direct')", (b.digest, ep.canonical(b.snapshot)))
    conn.commit()
    for statement in ("UPDATE extraction_policy_bindings SET origin='queue'",
                      "DELETE FROM extraction_policy_bindings"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)
        conn.rollback()
    for digest, snapshot, origin in [('xb1:00', '{}', 'direct'), (b.digest, '[]', 'direct'),
                                     (b.digest, '{"x":"' + 'y' * 70000 + '"}', 'direct'), (b.digest, '{}', 'other')]:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                         " VALUES ('s2','c',%s,%s,%s)", (digest, snapshot, origin))
        conn.rollback()


def test_bind_commits_binding_with_audit_and_reuses_the_winner(cfg, conn):
    a, b = bundle(), bundle('policy-b.toml')
    with db.connect(cfg, role='writer') as w:
        winner, created = mining.bind_policy(w, session_id='s', input_cursor='', bundle=a, origin='queue')
        assert created and winner.digest == a.digest
        again, created = mining.bind_policy(w, session_id='s', input_cursor='', bundle=b, origin='queue')
        assert not created and again.digest == a.digest
        lazy = mining.bind_policy(w, session_id='s', input_cursor='', origin='direct',
                                  bundle=lambda: pytest.fail('an existing binding must win before file resolution'))
        assert lazy[0].digest == a.digest
    audits = conn.execute("SELECT summary FROM audit_log WHERE op='extraction_policy_bind'").fetchall()
    assert [r['summary'] for r in audits] == [f'bound extraction policy {a.digest} (queue)']


def test_binding_audit_failure_leaves_no_unaudited_binding(cfg, conn, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(mining, '_audit', broken)
    with db.connect(cfg, role='writer') as w:
        with pytest.raises(RuntimeError):
            mining.bind_policy(w, session_id='s', input_cursor='c', bundle=bundle(), origin='direct')
    assert conn.execute("SELECT count(*) n FROM extraction_policy_bindings").fetchone()['n'] == 0


def test_concurrent_binders_have_one_committed_winner(cfg, conn):
    a, b = bundle(), bundle('policy-b.toml')
    first = db.connect(cfg, role='writer')
    first.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                  " VALUES ('race','c',%s,%s,'direct')", (a.digest, ep.canonical(a.snapshot)))
    result = {}

    def second():
        with db.connect(cfg, role='writer') as w:
            result['winner'] = mining.bind_policy(w, session_id='race', input_cursor='c', bundle=b, origin='direct')
    thread = threading.Thread(target=second)
    thread.start()
    thread.join(1.0)
    assert thread.is_alive(), 'the second binder must wait for the first transaction'
    first.commit()
    first.close()
    thread.join(10)
    winner, created = result['winner']
    assert winner.digest == a.digest and not created
    rows = conn.execute("SELECT digest FROM extraction_policy_bindings WHERE session_id='race'").fetchall()
    assert [r['digest'] for r in rows] == [a.digest]


def test_corrupted_binding_blocks_instead_of_falling_back(cfg, conn):
    a = bundle()
    tampered = {**a.snapshot, 'project': '/synthetic/team-b'}
    conn.execute("INSERT INTO extraction_policy_bindings(session_id,input_cursor,digest,snapshot,origin)"
                 " VALUES ('bad','c',%s,%s,'direct')", (a.digest, ep.canonical(tampered)))
    conn.commit()
    with db.connect(cfg, role='writer') as w:
        with pytest.raises(ep.PolicySnapshotError):
            mining.bind_policy(w, session_id='bad', input_cursor='c', bundle=a, origin='direct')


def test_upgrade_accepts_0_6_19_and_restore_allows_the_new_table():
    from agentic_rag.service import upgrade
    assert {'0.6.19', '0.6.20', '0.6.21'} <= upgrade.SUPPORTED_VERSIONS
    assert '0.6.22' not in upgrade.SUPPORTED_VERSIONS
    assert 'extraction_policy_bindings' in upgrade.RESTORE_ADDED_TABLES
    assert {'lifecycle_decisions', 'lifecycle_events', 'service_windows'} <= upgrade.RESTORE_ADDED_TABLES


def test_current_release_backup_records_the_actual_source_version(cfg, conn, tmp_path):
    # Operators must never relabel the current 0.6.21 store as an older release.
    from agentic_rag.service import upgrade
    mining.bind_policy(conn, session_id='current-backup', input_cursor='', bundle=bundle(), origin='direct')
    proof = upgrade.verified_backup(cfg, '0.6.21', tmp_path / 'current-release.dump')
    assert proof['restore_verified']
    assert proof['manifest']['source_version'] == '0.6.21'
    assert proof['manifest']['tables']['extraction_policy_bindings']['rows'] == 1
