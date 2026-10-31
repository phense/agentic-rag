"""RAG-065 S4 (R65-02/03/06, R65-L4): commit-safe forward processing.

Forward synthesis records which eligible originals a terminal analysed run
actually processed, per policy enable epoch, instead of advancing an arrival
cursor. These tests use real simultaneous PostgreSQL connections and a
deterministic in-process provider; nothing leaves the process.
"""
from dataclasses import replace
import json

import pytest

from agentic_rag import db, llm, store, worker
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.domains import seed_defaults

PROJECT = '/synthetic/s4-forward'
MARK = 'DNS suffix'


class Recorder:
    """Suggests one pattern over at most four offered quotes containing MARK.

    Fewer than three such quotes: an explicit non-conclusion. `hook` runs
    inside the provider call, emulating concurrent operator activity.
    """

    def __init__(self, suggest=True, hook=None):
        self.calls, self.suggest, self.hook = [], suggest, hook

    def __call__(self, prompt, schema, cfg, *, system=None, timeout=None, **kwargs):
        offered = fx.candidates_from_prompt(prompt)
        self.calls.append({'chars': len(prompt) + len(system or ''), 'candidates': offered})
        if self.hook is not None:
            self.hook()
        matched = [c['id'] for c in offered if MARK in c['quote']][:4]
        if not self.suggest or len(matched) < 3:
            return {'suggestions': [], 'non_conclusions': [{'reason': 'insufficient_evidence', 'citations': []}]}
        return {'suggestions': [{'label': 'Recurring missing DNS suffix', 'statement': 'The DNS suffix goes missing.',
                                 'confidence': 'medium',
                                 'parts': [{'text': 'Several reports lose the DNS suffix.',
                                            'citations': [{'id': i, 'stance': 'supports'} for i in matched]}]}],
                'non_conclusions': []}


@pytest.fixture
def env(conn, cfg, monkeypatch):
    monkeypatch.setattr('agentic_rag.store.try_embed_texts', lambda *a, **k: None)
    seed_defaults(conn)
    conn.commit()
    return replace(cfg, synthesis_enabled=True, ollama_url='http://127.0.0.1:1')


def original(conn, cfg, n, quote, *, commit=True):
    return store.save_claim(conn, cfg, title=f's4 original {n}', body=quote, domain='general', dtype='memory',
                            project=PROJECT, claim_kind='stated', actor='cli', commit=commit,
                            evidence=[{'namespace': f'session:s4-{n}', 'source_id': f'evt-s4-{n}', 'role': 'user',
                                       'quote': quote, 'timestamp': '2026-10-20T10:00:00Z',
                                       'complete': True}]).doc_id


def enable(conn, cfg):
    return store.set_synthesis_policy(conn, cfg, domain='general', enabled=True, reason='s4', project=PROJECT)


def tick(conn, cfg):
    from agentic_rag import synthesis
    scheduled = synthesis.schedule(conn, cfg)['scheduled']
    worker.drain(conn, cfg)
    return scheduled


def runs(conn):
    rows = conn.execute('SELECT * FROM synthesis_runs ORDER BY created_at,id').fetchall()
    conn.commit()
    return rows


def snapshot_ids(run, role=None):
    return {m['document_id'] for m in run['snapshot']['memories'] if role is None or m.get('role', 'new') == role}


def forward_view(conn, cfg):
    from agentic_rag import synthesis
    view = synthesis.status(conn, cfg, domain='general', project=PROJECT)['policies'][0]['forward']
    conn.commit()
    return view


def test_late_commit_from_held_open_writer_transaction_is_processed(conn, env, monkeypatch):
    """R65-02: an original whose transaction started before later originals
    were analysed is still found after it commits; no settle window needed."""
    provider = Recorder()
    monkeypatch.setattr(llm, 'run_structured', provider)
    enable(conn, env)
    late = db.connect(env, role='writer')
    try:
        late_id = original(late, env, 'late', f'After the reconnect the {MARK} vanished on the late laptop.',
                           commit=False)  # created_at = this still-open transaction's start
        early = [original(conn, env, n, f'Report {n}: the {MARK} was missing after VPN reconnect.')
                 for n in range(3)]
        assert tick(conn, env) == 1
        first = runs(conn)[0]
        assert first['state'] in ('applied', 'non_conclusion') and late_id not in snapshot_ids(first)
        assert snapshot_ids(first, 'new') == set(early)
        late.commit()
    finally:
        late.close()
    created = conn.execute('SELECT created_at FROM documents WHERE id=%s', (late_id,)).fetchone()['created_at']
    assert created < first['created_at']  # it arrived "before" the analysed run, yet must not be lost
    assert forward_view(conn, env)['pending_memories'] == 1
    conn.execute('UPDATE synthesis_policies SET next_due_at=now()')  # emulate the elapsed interval
    assert tick(conn, env) == 1
    second = runs(conn)[-1]
    assert late_id in snapshot_ids(second, 'new')
    assert forward_view(conn, env)['pending_memories'] == 0
    assert len(provider.calls) == 2


def test_default_budget_fits_realistic_quotes_and_leaves_the_rest_pending(conn, env, monkeypatch):
    """R65-03: twelve 1,100-character quotes exceed the default 12,000-character
    input; the fitting group is analysed, the remainder stays pending."""
    provider = Recorder(suggest=False)
    monkeypatch.setattr(llm, 'run_structured', provider)
    assert env.synthesis_max_input_chars == 12000
    enable(conn, env)
    ids = []
    for n in range(12):
        quote = (f'Report {n}: after the VPN reconnect the {MARK} list was empty on laptop {n}. '
                 + f'Detail {n} ' * 120)[:1100]
        ids.append(original(conn, env, n, quote))
    assert tick(conn, env) == 1
    first = runs(conn)[0]
    assert first['code'] != 'input_budget_exceeded'
    included = snapshot_ids(first, 'new')
    assert 3 <= len(included) < 12 and len(provider.calls) == 1
    assert provider.calls[0]['chars'] <= env.synthesis_max_input_chars
    assert first['usage']['provider_calls'] == 1
    # Analysed group is consumed, the rest is still pending and due again at once.
    assert forward_view(conn, env)['pending_memories'] == 12 - len(included)
    assert tick(conn, env) == 1
    second = runs(conn)[-1]
    assert snapshot_ids(second, 'new') == set(ids) - included
    assert forward_view(conn, env)['pending_memories'] == 0
    # Exact quote bytes reached the provider unchanged.
    offered = {c['quote'] for call in provider.calls for c in call['candidates']}
    stored = {r['quote'] for r in conn.execute('SELECT quote FROM claim_evidence WHERE document_id=ANY(%s)',
                                               (ids,)).fetchall()}
    assert stored <= offered


def test_oversized_original_is_visible_blocked_and_never_consumed(conn, env, monkeypatch):
    provider = Recorder(suggest=False)
    monkeypatch.setattr(llm, 'run_structured', provider)
    small = replace(env, synthesis_max_input_chars=2000)
    enable(conn, small)
    big = original(conn, small, 'big', f'The {MARK} ' + 'x' * 1800)
    normal = [original(conn, small, n, f'Report {n}: {MARK} gone again.') for n in range(3)]
    assert tick(conn, small) == 1
    first = runs(conn)[0]
    assert snapshot_ids(first) == set(normal) and big not in snapshot_ids(first)
    view = forward_view(conn, small)
    assert view['pending_memories'] == 1 and view['blocked'] == {'oversized': 1}
    # No automatic paid retry for unchanged blocked context.
    conn.execute('UPDATE synthesis_policies SET next_due_at=now()')
    assert tick(conn, small) == 0 and len(provider.calls) == 1
    # Documented operator action: raise the budget; the original is then analysed.
    assert tick(conn, replace(env, synthesis_max_input_chars=4000)) == 1
    assert big in snapshot_ids(runs(conn)[-1], 'new') and len(provider.calls) == 2


def test_minimum_group_over_budget_waits_visibly_without_provider_or_consumption(conn, env, monkeypatch):
    install = fx.ForbiddenProvider()
    fx.ForbiddenProvider.calls = 0
    monkeypatch.setattr(llm, 'run_structured', install)
    small = replace(env, synthesis_max_input_chars=1000)
    enable(conn, small)
    [original(conn, small, n, f'Report {n}: the {MARK} disappeared after the VPN reconnect today.')
     for n in range(4)]
    assert tick(conn, small) == 0
    view = forward_view(conn, small)
    assert view['waiting'] == 'input_budget_below_floor' and view['pending_memories'] == 4
    assert runs(conn) == [] and fx.ForbiddenProvider.calls == 0
    monkeypatch.setattr(llm, 'run_structured', Recorder())
    assert tick(conn, env) == 1 and runs(conn)[0]['state'] == 'applied'


def test_recurrence_spanning_two_runs_uses_bounded_recent_context(conn, env, monkeypatch):
    """R65-06: two observations analysed in one run and a third arriving later
    form one pattern; context is counted separately from newly processed work."""
    provider = Recorder()
    monkeypatch.setattr(llm, 'run_structured', provider)
    enable(conn, env)
    d1 = original(conn, env, 'd1', f'Monday: the {MARK} was missing after the VPN came back.')
    d2 = original(conn, env, 'd2', f'Tuesday: again no {MARK} on the laptop after reconnecting.')
    u1 = original(conn, env, 'u1', 'The printer on floor two jams on thick paper.')
    assert tick(conn, env) == 1
    first = runs(conn)[0]
    assert first['state'] == 'non_conclusion' and conn.execute('SELECT count(*) n FROM synthesis_patterns').fetchone()['n'] == 0
    conn.execute('UPDATE synthesis_policies SET next_due_at=now()')
    d3 = original(conn, env, 'd3', f'Thursday: the {MARK} disappeared once more after VPN reconnect.')
    u2 = original(conn, env, 'u2', 'Coffee machine shows a descaling warning.')
    u3 = original(conn, env, 'u3', 'Meeting room screen flickers at 60 Hz.')
    assert tick(conn, env) == 1
    second = runs(conn)[-1]
    assert snapshot_ids(second, 'new') == {d3, u2, u3}
    assert {d1, d2} <= snapshot_ids(second, 'context') and u1 in snapshot_ids(second, 'context')
    assert second['state'] == 'applied' and len(provider.calls) == 2
    cited = {str(r['original_id']) for r in conn.execute('SELECT original_id FROM synthesis_dependencies').fetchall()}
    assert cited == {d1, d2, d3}
    from agentic_rag import synthesis
    view = synthesis.status(conn, env, domain='general', project=PROJECT)['runs'][0]
    assert (view['new_memories'], view['context_memories']) == (3, 3)
    # Context alone never triggers another paid call.
    conn.execute('UPDATE synthesis_policies SET next_due_at=now()')
    assert tick(conn, env) == 0 and len(provider.calls) == 2


def test_policy_change_during_provider_call_withholds_without_consuming(conn, env, monkeypatch):
    """R65-L4: every terminal recording re-checks policy, snapshot and authority."""
    def toggle():
        with db.connect(env, role='writer') as other:
            store.set_synthesis_policy(other, env, domain='general', enabled=False, reason='pause', project=PROJECT)
            store.set_synthesis_policy(other, env, domain='general', enabled=True, reason='resume', project=PROJECT)
    provider = Recorder(suggest=False, hook=toggle)
    monkeypatch.setattr(llm, 'run_structured', provider)
    enable(conn, env)
    [original(conn, env, n, f'Report {n}: {MARK} missing.') for n in range(3)]
    assert tick(conn, env) == 1
    run = runs(conn)[0]
    assert (run['state'], run['code']) == ('withheld', 'policy_changed') and len(provider.calls) == 1
    assert conn.execute('SELECT count(*) n FROM synthesis_processed').fetchone()['n'] == 0


def test_processed_membership_is_recorded_atomically_with_the_terminal_outcome(conn, env, monkeypatch):
    monkeypatch.setattr(llm, 'run_structured', Recorder())
    enable(conn, env)
    ids = [original(conn, env, n, f'Report {n}: {MARK} missing after reconnect.') for n in range(3)]
    tick(conn, env)
    run = runs(conn)[0]
    rows = conn.execute('SELECT * FROM synthesis_processed ORDER BY document_id').fetchall()
    assert {str(r['document_id']) for r in rows} == set(ids)
    assert {r['run_id'] for r in rows} == {run['id']} and run['state'] == 'applied'
    policy = conn.execute('SELECT forward_from FROM synthesis_policies').fetchone()
    assert {r['epoch_from'] for r in rows} == {policy['forward_from']}
    assert json.dumps(run['snapshot']).count('"role": "new"') == 3


def test_bounded_scan_rotates_past_a_long_excluded_prefix(conn, env, monkeypatch):
    """Excluded rows are never processed; the bounded examination must still reach
    eligible originals behind them instead of starving forever."""
    from agentic_rag import synthesis
    monkeypatch.setattr(synthesis, 'MAX_SCAN', 5)
    monkeypatch.setattr(llm, 'run_structured', Recorder())
    enable(conn, env)
    for n in range(6):
        store.save_document(conn, env, title=f'unmanaged {n}', body=f'Legacy note {n}', domain='general',
                            dtype='memory', project=PROJECT, actor='cli')
    conn.commit()
    ids = [original(conn, env, n, f'Report {n}: {MARK} missing after reconnect.') for n in range(3)]
    assert tick(conn, env) == 0 and forward_view(conn, env).get('more') is True
    assert tick(conn, env) == 1
    assert snapshot_ids(runs(conn)[0], 'new') == set(ids)


def test_backfill_batches_fit_the_budget_and_resume_at_the_first_unfitted_original(conn, env, monkeypatch):
    from datetime import datetime, timedelta
    provider = Recorder(suggest=False)
    monkeypatch.setattr(llm, 'run_structured', provider)
    ids = []
    for n in range(12):
        quote = (f'Report {n}: after the VPN reconnect the {MARK} list was empty on laptop {n}. '
                 + f'Detail {n} ' * 120)[:1100]
        ids.append(original(conn, env, n, quote))
    policy = enable(conn, env)
    end = datetime.fromisoformat(policy['forward_from'])
    store.request_synthesis_backfill(conn, env, domain='general', project=PROJECT, reason='history',
                                     start=(end - timedelta(days=1)).isoformat(), end=policy['forward_from'],
                                     max_batches=2)
    assert tick(conn, env) == 1
    first = runs(conn)[0]
    assert first['code'] != 'input_budget_exceeded' and 3 <= len(snapshot_ids(first)) < 12
    assert tick(conn, env) == 1
    second = runs(conn)[-1]
    assert snapshot_ids(first) | snapshot_ids(second) == set(ids)
    assert not snapshot_ids(first) & snapshot_ids(second)
    assert all(call['chars'] <= env.synthesis_max_input_chars for call in provider.calls)
    from agentic_rag import synthesis
    assert synthesis.status(conn, env, domain='general', project=PROJECT)['backfills'] == []  # done


def test_backfill_minimum_group_over_budget_waits_without_advancing_and_resumes(conn, env, monkeypatch, capsys):
    """N1: splitting a minimum group into budget-sized non-conclusions must
    neither consume its backfill window nor hide the operator's budget action."""
    from datetime import datetime, timedelta
    from agentic_rag import cli, synthesis

    provider = Recorder()
    monkeypatch.setattr(llm, 'run_structured', provider)
    for n in range(3):
        original(conn, env, n, (f'Report {n}: the {MARK} vanished. ' + f'Detail {n} ' * 100)[:600])
    policy = enable(conn, env)
    end = datetime.fromisoformat(policy['forward_from'])
    backfill = store.request_synthesis_backfill(
        conn, env, domain='general', project=PROJECT, reason='history',
        start=(end - timedelta(days=1)).isoformat(), end=policy['forward_from'], max_batches=5)
    small = replace(env, synthesis_max_input_chars=2100)
    before = conn.execute('SELECT * FROM synthesis_backfills WHERE id=%s', (backfill['id'],)).fetchone()
    conn.commit()
    for _ in range(2):
        assert tick(conn, small) == 0
        view = synthesis.status(conn, small, domain='general', project=PROJECT)['backfills'][0]
        assert (view['state'], view['batches'], view['waiting']) == ('pending', 0, 'input_budget_below_floor')
        row = conn.execute('SELECT * FROM synthesis_backfills WHERE id=%s', (backfill['id'],)).fetchone()
        assert (row['cursor_at'], row['cursor_id']) == (before['cursor_at'], before['cursor_id'])
        assert runs(conn) == [] and provider.calls == []
    monkeypatch.setattr(cli, 'load_config', lambda: small)
    assert cli.main(['pattern', 'status', '--domain', 'general', '--project', PROJECT]) == 0
    output = capsys.readouterr().out
    assert f"backfill {backfill['id']} pending" in output and 'input_budget_below_floor' in output
    assert tick(conn, env) == 1
    assert len(provider.calls) == 1 and runs(conn)[0]['state'] == 'applied'
    assert synthesis.status(conn, env, domain='general', project=PROJECT)['backfills'] == []
    row = conn.execute('SELECT * FROM synthesis_backfills WHERE id=%s', (backfill['id'],)).fetchone()
    assert (row['state'], row['batches'], row['waiting']) == ('done', 1, None)
