"""RAG-066 AF-066-009: automatic exact curation needs identical title, body and dtype.

Frozen fixture expectations (docs/benchmarks/2026-10-31-memory-lifecycle) decide the
outcome; the existing archive/duplicate_of/audit semantics stay for justified copies.
"""
import pytest

from agentic_rag import curation, store
from agentic_rag.benchmark import memory_lifecycle as fx

pytestmark = pytest.mark.usefixtures('conn')


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)


def _names(ids):
    return {v: k for k, v in ids.items()}


def test_automatic_exact_policy_matches_frozen_labels(conn, cfg):
    ids = fx.ingest(conn, cfg)
    labels = fx.load('labels.json')['automatic_curation']
    report = curation.run_pass(conn, cfg, budget=labels['budget'], runner=None)
    names = _names(ids)
    archived = sorted(names[str(r['id'])] for r in conn.execute("SELECT id FROM documents WHERE status='archived'"))
    assert archived == labels['policy_0_6_19']['archived']
    assert report.merged == len(archived)
    # Existing evidence of a justified merge: duplicate_of edge to the kept copy and one audit row.
    for key, keep in labels['keep'].items():
        edge = conn.execute("SELECT dst_id FROM edges WHERE src_id=%s AND predicate='duplicate_of'", (ids[key],)).fetchone()
        assert str(edge['dst_id']) == ids[keep]
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='curation_merge' AND document_id=%s",
                            (ids[key],)).fetchone()['n'] == 1


@pytest.mark.parametrize('case,kept_active', [('T1', 2), ('T2', 2), ('T3', 2), ('S1', 2), ('S2', 2), ('S3', 2)])
def test_different_title_type_or_scope_is_never_archived(conn, cfg, case, kept_active):
    ids = fx.ingest(conn, cfg, {case})
    curation.run_pass(conn, cfg, budget=50, runner=None)
    rows = conn.execute("SELECT status FROM documents WHERE id=ANY(%s::uuid[])", (list(ids.values()),)).fetchall()
    assert [r['status'] for r in rows].count('active') == kept_active
    assert not conn.execute("SELECT 1 FROM edges WHERE predicate='duplicate_of'").fetchone()


def test_title_change_after_planning_is_revalidated_under_lock(conn, cfg, monkeypatch):
    ids = fx.ingest(conn, cfg, {'E1'})
    real = curation._lock_scope_pair

    def edit_then_lock(c, first, second, *args, **kwargs):
        # A concurrent writer renames the newer copy after the candidate query.
        c.execute("UPDATE documents SET title='VPN reconnect (other site)' WHERE id=%s", (ids['E1-copy'],))
        return real(c, first, second, *args, **kwargs)
    monkeypatch.setattr(curation, '_lock_scope_pair', edit_then_lock)
    curation.run_pass(conn, cfg, budget=5, runner=None)
    assert conn.execute("SELECT status FROM documents WHERE id=%s", (ids['E1-copy'],)).fetchone()['status'] == 'active'
