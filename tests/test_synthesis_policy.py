"""RAG-065 T065-002: default-off, provider-free preview, scoped opt-in forward
boundary, explicit bounded backfill and scheduling through the existing worker.

Labels come from the frozen fixture (docs/benchmarks/2026-10-31-pattern-synthesis).
A provider call anywhere in these tests is a failure unless a test installs one.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agentic_rag import db, llm, worker
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.benchmark.rerank_evaluation import _snapshot
from agentic_rag.config import Config
from agentic_rag.domains import seed_defaults


@pytest.fixture
def forbidden(monkeypatch):
    provider = fx.ForbiddenProvider()
    fx.ForbiddenProvider.calls = 0
    monkeypatch.setattr(llm, 'run_structured', provider)
    monkeypatch.setattr('agentic_rag.store.try_embed_texts', lambda *a, **k: None)
    return provider


@pytest.fixture
def on(cfg):
    return replace(cfg, synthesis_enabled=True, ollama_url='http://127.0.0.1:1')


def synthesis_tables(conn):
    return {r['tablename'] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'synthesis_%'")}


def test_config_defaults_off_with_bounded_overrides(tmp_path):
    cfg = Config()
    assert cfg.synthesis_enabled is False
    assert (cfg.synthesis_timeout_seconds, cfg.synthesis_max_input_chars, cfg.synthesis_max_output_tokens,
            cfg.synthesis_max_runs_per_tick) == (30, 12000, 1024, 2)
    for bad in [dict(synthesis_enabled='yes'), dict(synthesis_timeout_seconds=0), dict(synthesis_timeout_seconds=301),
                dict(synthesis_max_input_chars=999), dict(synthesis_max_input_chars=24001),
                dict(synthesis_max_output_tokens=127), dict(synthesis_max_runs_per_tick=11),
                dict(synthesis_provider='other'), dict(synthesis_model='x' * 201)]:
        with pytest.raises(ValueError):
            Config(**bad)
    path = tmp_path / 'config.toml'
    path.write_text('[synthesis]\nenabled = true\ntimeout_seconds = 20\nmax_input_chars = 8000\n')
    from agentic_rag.config import load_config
    loaded = load_config(path)
    assert loaded.synthesis_enabled is True and loaded.synthesis_timeout_seconds == 20
    assert loaded.synthesis_max_input_chars == 8000


def test_migration_creates_empty_policy_storage_and_upgrade_accepts_actual_0_6_17(conn):
    assert synthesis_tables(conn) == {'synthesis_policies', 'synthesis_backfills', 'synthesis_runs',
                                      'synthesis_processed', 'synthesis_patterns', 'synthesis_dependencies'}
    assert conn.execute('SELECT count(*) n FROM synthesis_policies').fetchone()['n'] == 0
    from agentic_rag.service import upgrade
    # RAG-067 moved the refused running target from 0.6.19 to 0.6.20.
    assert '0.6.17' in upgrade.SUPPORTED_VERSIONS and '0.6.20' not in upgrade.SUPPORTED_VERSIONS


def test_default_off_ordinary_worker_and_reads_never_schedule_or_call_provider(conn, cfg, forbidden):
    from agentic_rag import synthesis
    seed_defaults(conn)
    conn.commit()
    fx.ingest(conn, cfg, {'K1', 'C1'})
    # Global switch off, no policy: nothing is due.
    assert synthesis.schedule(conn, cfg) == {'scheduled': 0, 'policies': 0}
    # Global switch on, but no scoped policy: still nothing.
    assert synthesis.schedule(conn, replace(cfg, synthesis_enabled=True)) == {'scheduled': 0, 'policies': 0}
    # The ordinary worker tick (scheduling hook plus drain of unrelated queued
    # embedding retries against an unreachable embedder) creates no synthesis work.
    dead = replace(cfg, ollama_url='http://127.0.0.1:1')
    worker._schedule_synthesis(conn, dead)
    worker.drain(conn, dead)
    worker._schedule_synthesis(conn, replace(dead, synthesis_enabled=True))
    counts = conn.execute("""SELECT (SELECT count(*) FROM synthesis_policies) policies,
        (SELECT count(*) FROM synthesis_backfills) backfills, (SELECT count(*) FROM synthesis_runs) runs,
        (SELECT count(*) FROM synthesis_processed) processed,
        (SELECT count(*) FROM synthesis_patterns) patterns, (SELECT count(*) FROM synthesis_dependencies) deps,
        (SELECT count(*) FROM mining_queue WHERE kind='synthesis') jobs,
        (SELECT count(*) FROM audit_log WHERE op LIKE 'synthesis%%') audits,
        (SELECT count(*) FROM documents WHERE dtype='synthesis') derived""").fetchone()
    assert dict(counts) == dict.fromkeys(counts, 0)
    conn.rollback()
    assert fx.ForbiddenProvider.calls == 0


@pytest.mark.parametrize('case', sorted(fx.cases('dev')))
def test_preview_matches_frozen_labels_and_is_provider_free_and_read_only(conn, cfg, forbidden, case):
    from agentic_rag import synthesis
    seed_defaults(conn)
    conn.commit()
    fx.ingest(conn, cfg)
    before = _snapshot(conn)
    conn.rollback()
    expected = fx.cases()[case]['preview']
    with db.connect(cfg, role='reader') as reader:
        view = synthesis.preview(reader, cfg, domain='general', project=fx.project(case))
    assert view['candidates']['memories'] == expected['eligible_memories']
    assert view['candidates']['independent_events'] == expected['independent_events']
    assert view['candidates']['sufficient'] is expected['sufficient']
    assert {k: v for k, v in view['excluded'].items() if v} == expected['excluded']
    assert view['policy'] == {'exists': False, 'enabled': False}
    assert view['budgets']['provider_calls'] == 0 and view['budgets']['max_memories'] == 12
    assert view['floor'] == {'independent_events': 3, 'memories': 3}
    for ref in view['references']:
        assert set(ref) == {'document_id', 'version', 'reference', 'source_version', 'event'}
        assert ref['version'].startswith('ev1:') and ref['source_version'].startswith('src1:')
    text = repr(view)
    assert 'session:' not in text and 'import:' not in text and 'evt-' not in text
    assert _snapshot(conn) == before
    conn.rollback()
    assert fx.ForbiddenProvider.calls == 0


def test_policy_scope_is_concrete_exact_and_audited(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    fx.ingest(conn, cfg, {'K1', 'F1'})
    with pytest.raises(ValueError, match='concrete'):
        store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='no scope')
    with pytest.raises(ValueError, match='concrete'):
        store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='unknown', scope='unknown')
    with pytest.raises(ValueError, match='unknown domain'):
        store.set_synthesis_policy(conn, on, domain='nope', enabled=True, reason='x', project='/synthetic/k1-vpn-dns')
    with pytest.raises(ValueError, match='reason'):
        store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason=' ', project='/synthetic/k1-vpn-dns')
    first = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='opt in K1',
                                       project='/synthetic/k1-vpn-dns')
    assert first['enabled'] is True and first['version'] == 1 and first['forward_from'] is not None
    off = store.set_synthesis_policy(conn, on, domain='general', enabled=False, reason='pause',
                                     project='/synthetic/k1-vpn-dns')
    assert off['version'] == 2 and off['enabled'] is False and off['forward_from'] == first['forward_from']
    audits = conn.execute("SELECT summary FROM audit_log WHERE op='synthesis_policy' ORDER BY id").fetchall()
    assert len(audits) == 2 and 'opt in K1' in audits[0]['summary']
    # A global policy never reaches project memories, and projects never mix.
    view = synthesis.preview(conn, cfg, domain='general', scope='global')
    assert view['candidates']['memories'] == 0
    assert synthesis.preview(conn, cfg, domain='general', project='/synthetic/f1-duplicates')['candidates']['memories'] == 3


def test_enable_records_forward_boundary_without_backfill(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    fx.ingest(conn, cfg, {'K1'})  # history before opt-in
    policy = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='forward only',
                                        project=fx.project('K1'))
    assert synthesis.schedule(conn, on) == {'scheduled': 0, 'policies': 1}
    status = synthesis.status(conn, on, domain='general', project=fx.project('K1'))
    assert status['policies'][0]['forward']['pending_memories'] == 0
    assert status['policies'][0]['forward_from'] == policy['forward_from']
    assert status['runs'] == []
    assert conn.execute("SELECT count(*) n FROM mining_queue WHERE kind='synthesis'").fetchone()['n'] == 0
    assert fx.ForbiddenProvider.calls == 0


def test_forward_scheduling_uses_existing_queue_and_waits_below_floor(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='forward', project=fx.project('K1'))
    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='forward', project=fx.project('F1'))
    fx.ingest(conn, cfg, {'K1', 'F1'})
    result = synthesis.schedule(conn, on)
    assert result == {'scheduled': 1, 'policies': 2}  # F1 has one event and fewer than a full batch: waits
    jobs = conn.execute("SELECT kind,payload FROM mining_queue WHERE kind='synthesis'").fetchall()
    assert len(jobs) == 1
    run = conn.execute('SELECT * FROM synthesis_runs').fetchone()
    assert run['state'] == 'pending' and run['candidates'] == 4 and run['kind'] == 'forward'
    assert str(run['id']) == jobs[0]['payload']['run']
    # One open run per policy: a second tick schedules nothing new.
    assert synthesis.schedule(conn, on)['scheduled'] == 0
    status = synthesis.status(conn, on, domain='general', project=fx.project('F1'))
    assert status['policies'][0]['forward'] == {'pending_memories': 3, 'waiting': 'insufficient_independent_support'}
    assert fx.ForbiddenProvider.calls == 0


def test_global_switch_off_stops_scheduling_and_policy_changes(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='on', project=fx.project('K1'))
    fx.ingest(conn, cfg, {'K1'})
    assert synthesis.schedule(conn, cfg) == {'scheduled': 0, 'policies': 0}
    with pytest.raises(ValueError, match='synthesis_disabled'):
        store.set_synthesis_policy(conn, cfg, domain='general', enabled=True, reason='x', project=fx.project('C1'))
    # Disabling stays possible while the global switch is off.
    store.set_synthesis_policy(conn, cfg, domain='general', enabled=False, reason='off', project=fx.project('K1'))


def test_disable_reenable_does_not_sweep_gap_and_backfill_is_explicit_and_bounded(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    project = fx.project('K1')
    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='on', project=project)
    store.set_synthesis_policy(conn, on, domain='general', enabled=False, reason='pause', project=project)
    fx.ingest(conn, cfg, {'K1'})  # arrives while disabled
    again = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='resume', project=project)
    assert synthesis.schedule(conn, on)['scheduled'] == 0
    forward_from = datetime.fromisoformat(again['forward_from'])
    start = (forward_from - timedelta(days=1)).isoformat()
    end = again['forward_from']
    for bad, code in [(dict(start=end, end=start), 'window'), (dict(start=start, end=(forward_from + timedelta(seconds=5)).isoformat()), 'forward'),
                      (dict(start=(forward_from - timedelta(days=400)).isoformat(), end=end), 'window'),
                      (dict(start=start, end=end, max_batches=0), 'max_batches'), (dict(start=start, end=end, max_batches=11), 'max_batches'),
                      (dict(start='yesterday', end=end), 'time')]:
        args = {'max_batches': 1, **bad}
        with pytest.raises(ValueError, match=code):
            store.request_synthesis_backfill(conn, on, domain='general', project=project, reason='bad', **args)
    with pytest.raises(ValueError, match='synthesis_disabled'):
        store.request_synthesis_backfill(conn, cfg, domain='general', project=project, reason='off', start=start, end=end)
    requested = store.request_synthesis_backfill(conn, on, domain='general', project=project, reason='gap',
                                                 start=start, end=end, max_batches=1)
    assert requested['state'] == 'pending' and requested['max_batches'] == 1
    assert synthesis.schedule(conn, on)['scheduled'] == 1
    run = conn.execute('SELECT kind,candidates,backfill_id FROM synthesis_runs').fetchone()
    assert run['kind'] == 'backfill' and run['candidates'] == 4 and str(run['backfill_id']) == requested['id']
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='synthesis_backfill'").fetchone()['n'] == 1
    # A backfill on a disabled policy is refused.
    store.set_synthesis_policy(conn, on, domain='general', enabled=False, reason='stop', project=project)
    with pytest.raises(ValueError, match='policy_disabled'):
        store.request_synthesis_backfill(conn, on, domain='general', project=project, reason='x', start=start, end=end)
    assert fx.ForbiddenProvider.calls == 0


def test_scheduler_caps_new_runs_per_tick(conn, cfg, on, forbidden):
    from agentic_rag import store, synthesis
    seed_defaults(conn)
    conn.commit()
    capped = replace(on, synthesis_max_runs_per_tick=1)
    for case in ('K1', 'C1', 'I1'):
        store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='on', project=fx.project(case))
    fx.ingest(conn, cfg, {'K1', 'C1', 'I1'})
    assert synthesis.schedule(conn, capped)['scheduled'] == 1
    assert synthesis.schedule(conn, capped)['scheduled'] == 1
    assert synthesis.schedule(conn, on)['scheduled'] == 1
    assert conn.execute('SELECT count(*) n FROM synthesis_runs').fetchone()['n'] == 3
    assert fx.ForbiddenProvider.calls == 0
