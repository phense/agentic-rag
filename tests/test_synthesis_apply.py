"""RAG-065 T065-003: bounded structured provider use, exact versioned citations,
accepted-before-applied durability, stable application identity and atomic
inference/dependency/audit application. Labels come from the frozen fixture.
"""
from dataclasses import replace
from datetime import datetime, timedelta
import threading

import pytest

from agentic_rag import db, llm, worker
from agentic_rag import evidence_contract as contract
from agentic_rag.benchmark import pattern_synthesis as fx
from agentic_rag.domains import seed_defaults
from agentic_rag.llm import LLMUnavailableError


@pytest.fixture
def env(conn, cfg, monkeypatch):
    from agentic_rag import synthesis
    monkeypatch.setattr(synthesis, 'SETTLE_SECONDS', 0)
    monkeypatch.setattr('agentic_rag.store.try_embed_texts', lambda *a, **k: None)
    seed_defaults(conn)
    conn.commit()
    return replace(cfg, synthesis_enabled=True, ollama_url='http://127.0.0.1:1')


def install(monkeypatch, provider):
    monkeypatch.setattr(llm, 'run_structured', provider)
    return provider


def forward(conn, on, case):
    from agentic_rag import store, synthesis
    store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='fixture', project=fx.project(case))
    keys = fx.ingest(conn, on, {case})
    assert synthesis.schedule(conn, on)['scheduled'] == 1
    return keys


def backfill(conn, on, case):
    from agentic_rag import store, synthesis
    keys = fx.ingest(conn, on, {case})
    policy = store.set_synthesis_policy(conn, on, domain='general', enabled=True, reason='fixture',
                                       project=fx.project(case))
    end = datetime.fromisoformat(policy['forward_from'])
    store.request_synthesis_backfill(conn, on, domain='general', project=fx.project(case), reason='fixture',
                                     start=(end - timedelta(days=1)).isoformat(), end=policy['forward_from'])
    assert synthesis.schedule(conn, on)['scheduled'] == 1
    return keys


def synthesis_job(conn):
    row = conn.execute("SELECT * FROM mining_queue WHERE kind='synthesis' ORDER BY id DESC LIMIT 1").fetchone()
    conn.commit()
    return {**dict(row), 'attempts': 1}


def run_row(conn):
    row = conn.execute('SELECT * FROM synthesis_runs ORDER BY created_at DESC LIMIT 1').fetchone()
    conn.commit()
    return row


def counts(conn):
    row = conn.execute("""SELECT (SELECT count(*) FROM synthesis_patterns) patterns,
        (SELECT count(*) FROM documents WHERE dtype='synthesis' AND provenance->>'origin'='pattern-synthesis') documents,
        (SELECT count(*) FROM audit_log WHERE op='synthesis_apply') audits,
        (SELECT count(*) FROM synthesis_dependencies) dependencies""").fetchone()
    conn.commit()
    return dict(row)


def originals(conn, keys):
    versions = {k: contract.document_version(conn, v) for k, v in keys.items()}
    rows = conn.execute('SELECT count(*) n FROM claim_evidence WHERE document_id=ANY(%s)',
                        (list(keys.values()),)).fetchone()['n']
    conn.commit()
    return versions, rows


def test_known_pattern_applies_one_inferred_suggestion_with_exact_versioned_citations(conn, env, monkeypatch):
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    keys = forward(conn, env, 'K1')
    before = originals(conn, keys)
    worker.drain(conn, env)
    run = run_row(conn)
    expected = fx.cases()['K1']['oracle']
    assert run['state'] == 'applied' and len(provider.calls) == expected['provider_calls']
    call = provider.calls[0]
    assert call['chars'] <= env.synthesis_max_input_chars and call['timeout'] == env.synthesis_timeout_seconds
    assert call['schema']['additionalProperties'] is False
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}
    pattern = conn.execute('SELECT p.*,d.dtype,d.domain,d.project_scope,c.kind,c.review_state FROM synthesis_patterns p'
                           ' JOIN documents d ON d.id=p.document_id JOIN claim_records c ON c.document_id=d.id').fetchone()
    assert (pattern['dtype'], pattern['kind'], pattern['review_state']) == ('synthesis', 'inference', 'unreviewed')
    assert (pattern['domain'], pattern['project_scope']) == ('general', fx.project('K1'))
    assert pattern['events'] == expected['cited_events'] and pattern['memories'] == expected['cited_memories']
    assert len(pattern['parts']) == expected['supported_parts'] and pattern['confidence'] == 'medium'
    # Every dependency is an exact original span at its current portable versions.
    for dep in conn.execute('SELECT * FROM synthesis_dependencies').fetchall():
        assert dep['original_id'] in {__import__('uuid').UUID(v) for v in keys.values()}
        assert dep['original_version'] == contract.document_version(conn, str(dep['original_id']))
        assert dep['source_version'] == contract.source_version(conn, dep['source_key'])['version']
        assert conn.execute('SELECT 1 FROM claim_evidence WHERE document_id=%s AND source_key=%s AND span_hash=%s',
                            (dep['original_id'], dep['source_key'], dep['span_hash'])).fetchone()
    view = contract.inspect(conn, str(pattern['document_id']))
    assert view['claim']['kind'] == 'inference' and view['claim']['support_basis'] == 'none'
    assert view['verification'] == {'independent': False, 'origin': 'none'}
    conn.commit()
    # Originals are untouched: same versions and spans.
    assert originals(conn, keys) == before


@pytest.mark.parametrize('case,variant', [(c, v) for c, labels in sorted(fx.cases('dev').items())
                                          for v in ('oracle', 'adversarial', 'worker') if v in labels])
def test_false_conflicting_and_injected_outputs_become_explicit_non_conclusions(conn, env, monkeypatch, case, variant):
    from agentic_rag import synthesis
    labels = fx.cases()[case]
    expected = labels[variant]
    if variant == 'worker':
        provider = install(monkeypatch, fx.ForbiddenProvider())
        fx.ForbiddenProvider.calls = 0
        backfill(conn, env, case)
        worker.drain(conn, env)
        run = run_row(conn)
        assert (run['state'], run['code']) == ('non_conclusion', expected['reason'])
        assert fx.ForbiddenProvider.calls == expected['provider_calls'] == 0
    elif labels['preview']['sufficient']:
        provider = install(monkeypatch, fx.ScriptedProvider(case, variant))
        forward(conn, env, case)
        worker.drain(conn, env)
        run = run_row(conn)
        assert len(provider.calls) == expected['provider_calls']
        if expected['outcome'] == 'applied':
            assert run['state'] == 'applied' and counts(conn)['patterns'] == expected['applied']
            return
        assert (run['state'], run['code']) == ('non_conclusion', expected['reason'])
    else:
        # Below the floor no provider is called; the validator still rejects an
        # over-claiming response that cites duplicate imports of one event.
        fx.ingest(conn, env, {case})
        selection = synthesis.candidates(conn, 'general', fx.project(case))
        offered = synthesis.offered(selection)
        response = fx.resolve(fx.ScriptedProvider(case, variant).template,
                              [{'id': cid, 'quote': c['quote']} for cid, c in offered.items()])
        outcome = synthesis.validate(response, offered)
        assert outcome['suggestions'] == [] and outcome['rejected'][0]['code'] == expected['reason']
    assert counts(conn) == {'patterns': 0, 'documents': 0, 'audits': 0, 'dependencies': 0}


def test_validator_rejects_unbounded_or_foreign_output_before_persisting(conn, env):
    from agentic_rag import synthesis
    fx.ingest(conn, env, {'K1'})
    offered = synthesis.offered(synthesis.candidates(conn, 'general', fx.project('K1')))
    ids = sorted(offered)
    part = {'text': 'x', 'citations': [{'id': i, 'stance': 'supports'} for i in ids[:3]]}
    good = {'label': 'l', 'statement': 's', 'confidence': 'low', 'parts': [part]}
    assert len(synthesis.validate({'suggestions': [good], 'non_conclusions': []}, offered)['suggestions']) == 1
    for bad in [{'suggestions': [good] * 4, 'non_conclusions': []},
                {'suggestions': [{**good, 'label': 'x' * 121}], 'non_conclusions': []},
                {'suggestions': [{**good, 'confidence': 'certain'}], 'non_conclusions': []},
                {'suggestions': [{**good, 'parts': []}], 'non_conclusions': []},
                {'suggestions': [{**good, 'parts': [{**part, 'citations': []}]}], 'non_conclusions': []},
                {'suggestions': [{**good, 'scope': 'global'}], 'non_conclusions': []},
                {'suggestions': [good]}, [], 'text']:
        with pytest.raises(synthesis.InvalidOutput):
            synthesis.validate(bad, offered)


def test_accepted_output_survives_apply_failure_and_retry_reuses_it(conn, env, monkeypatch):
    from agentic_rag import synthesis
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    forward(conn, env, 'K1')
    real = synthesis._register
    def crash(*args, **kwargs):
        raise RuntimeError('injected failure after the derived document was written')
    monkeypatch.setattr(synthesis, '_register', crash)
    report = worker.drain(conn, env)
    assert report['failed'] >= 1
    run = run_row(conn)
    assert run['state'] == 'accepted' and run['accepted']['suggestions'] and len(provider.calls) == 1
    # The half-written pattern document rolled back with its spans and audits.
    assert counts(conn) == {'patterns': 0, 'documents': 0, 'audits': 0, 'dependencies': 0}
    monkeypatch.setattr(synthesis, '_register', real)
    job = synthesis_job(conn)
    assert synthesis.process(conn, env, job) == 'applied'
    assert len(provider.calls) == 1  # no second paid call
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}
    # Duplicate submission of the same job is a no-op.
    assert synthesis.process(conn, env, job) == 'applied'
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}


def test_concurrent_application_of_accepted_work_creates_one_pattern(conn, env, monkeypatch):
    from agentic_rag import synthesis
    from agentic_rag.service.engine import JobBlocked
    install(monkeypatch, fx.ScriptedProvider('K1'))
    forward(conn, env, 'K1')
    real = synthesis._register
    monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('stop')))
    worker.drain(conn, env)
    monkeypatch.setattr(synthesis, '_register', real)
    install(monkeypatch, fx.ForbiddenProvider())
    job = synthesis_job(conn)
    barrier, outcomes = threading.Barrier(2), []

    def attempt():
        with db.connect(env, role='writer') as own:
            barrier.wait()
            try:
                outcomes.append(synthesis.process(own, env, job))
            except JobBlocked as exc:
                outcomes.append('blocked:' + str(exc))
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert 'applied' in outcomes and len(outcomes) == 2
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}


def test_application_identity_is_stable_across_disable_reenable_and_backfill(conn, env, monkeypatch):
    from agentic_rag import store, synthesis
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    keys = fx.ingest(conn, env, {'K1'})
    project = fx.project('K1')
    policy = store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='a', project=project)
    end = datetime.fromisoformat(policy['forward_from'])
    window = dict(start=(end - timedelta(days=1)).isoformat(), end=policy['forward_from'])
    store.request_synthesis_backfill(conn, env, domain='general', project=project, reason='first', **window)
    synthesis.schedule(conn, env)
    worker.drain(conn, env)
    assert counts(conn)['patterns'] == 1
    store.set_synthesis_policy(conn, env, domain='general', enabled=False, reason='pause', project=project)
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='resume', project=project)
    store.request_synthesis_backfill(conn, env, domain='general', project=project, reason='again', **window)
    synthesis.schedule(conn, env)
    worker.drain(conn, env)
    run = run_row(conn)
    assert run['state'] == 'non_conclusion' and run['code'] == 'duplicate_application'
    assert len(provider.calls) == 2
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}
    assert len(keys) == 4


def test_policy_disable_or_source_change_after_acceptance_withholds_without_applying(conn, env, monkeypatch):
    from agentic_rag import store, synthesis
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    keys = forward(conn, env, 'K1')
    real = synthesis._register
    monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('stop')))
    worker.drain(conn, env)
    assert run_row(conn)['state'] == 'accepted'
    monkeypatch.setattr(synthesis, '_register', real)
    # A source change after acceptance withholds the run; accepted output is kept.
    key = contract.inspect(conn, keys['k1-b'])['sources']['items'][0]['source_key']
    conn.commit()
    store.set_source_state(conn, key, state='refuted', reason='wrong machine')
    assert synthesis.process(conn, env, synthesis_job(conn)) == 'withheld'
    run = run_row(conn)
    assert (run['state'], run['code']) == ('withheld', 'source_changed') and run['accepted'] is not None
    assert counts(conn)['patterns'] == 0 and len(provider.calls) == 1


def test_disabled_policy_before_provider_call_withholds_and_spends_nothing(conn, env, monkeypatch):
    from agentic_rag import store
    provider = install(monkeypatch, fx.ForbiddenProvider())
    fx.ForbiddenProvider.calls = 0
    forward(conn, env, 'K1')
    store.set_synthesis_policy(conn, env, domain='general', enabled=False, reason='stop', project=fx.project('K1'))
    worker.drain(conn, env)
    run = run_row(conn)
    assert (run['state'], run['code']) == ('withheld', 'policy_disabled')
    assert fx.ForbiddenProvider.calls == 0 and counts(conn)['patterns'] == 0
    # Global switch off while a job is queued: withheld, no call.
    store.set_synthesis_policy(conn, env, domain='general', enabled=True, reason='again', project=fx.project('C1'))
    fx.ingest(conn, env, {'C1'})
    from agentic_rag import synthesis
    synthesis.schedule(conn, env)
    worker.drain(conn, replace(env, synthesis_enabled=False))
    assert (run_row(conn)['state'], run_row(conn)['code']) == ('withheld', 'synthesis_disabled')
    assert fx.ForbiddenProvider.calls == 0 and provider is not None


def test_provider_outage_keeps_run_pending_then_completes_once(conn, env, monkeypatch):
    from agentic_rag import synthesis
    outage = install(monkeypatch, fx.ScriptedProvider('K1', fail=LLMUnavailableError('synthetic outage')))
    forward(conn, env, 'K1')
    report = worker.drain(conn, env)
    assert report['provider_unavailable'] == 1
    assert run_row(conn)['state'] == 'pending' and len(outage.calls) == 1
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    assert synthesis.process(conn, env, synthesis_job(conn)) == 'applied'
    assert len(provider.calls) == 1 and counts(conn)['patterns'] == 1


def test_input_budget_is_enforced_before_any_provider_call(conn, env, monkeypatch):
    install(monkeypatch, fx.ForbiddenProvider())
    fx.ForbiddenProvider.calls = 0
    small = replace(env, synthesis_max_input_chars=1000)
    forward(conn, small, 'K1')
    worker.drain(conn, small)
    run = run_row(conn)
    assert (run['state'], run['code']) == ('non_conclusion', 'input_budget_exceeded')
    assert fx.ForbiddenProvider.calls == 0


def test_unusable_provider_output_is_a_terminal_non_conclusion(conn, env, monkeypatch):
    from agentic_rag.llm import LLMJobError
    provider = install(monkeypatch, fx.ScriptedProvider('K1', fail=LLMJobError('provider output is not valid JSON')))
    forward(conn, env, 'K1')
    worker.drain(conn, env)
    run = run_row(conn)
    assert (run['state'], run['code']) == ('non_conclusion', 'invalid_output') and len(provider.calls) == 1
    assert run['usage']['provider_calls'] == 1


def test_exhausted_apply_retries_park_accepted_work_for_explicit_recovery(conn, env, monkeypatch):
    from agentic_rag import store, synthesis
    provider = install(monkeypatch, fx.ScriptedProvider('K1'))
    forward(conn, env, 'K1')
    real = synthesis._register
    monkeypatch.setattr(synthesis, '_register', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('stop')))
    worker.drain(conn, env)
    # The job exhausts its finite attempts (existing worker backoff), then the
    # next tick parks the run instead of blocking the policy forever.
    conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'")
    conn.commit()
    synthesis.schedule(conn, env)
    run = run_row(conn)
    assert (run['state'], run['code']) == ('error', 'apply_failed') and run['accepted'] is not None
    status = synthesis.status(conn, env, domain='general', project=fx.project('K1'))
    assert status['runs'][0]['state'] == 'error' and status['runs'][0]['recoverable'] is True
    with pytest.raises(ValueError, match='reason'):
        store.recover_synthesis_run(conn, env, str(run['id']), reason='')
    monkeypatch.setattr(synthesis, '_register', real)
    recovered = store.recover_synthesis_run(conn, env, str(run['id']), reason='apply bug fixed')
    assert recovered['state'] == 'accepted'
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='synthesis_recover'").fetchone()['n'] == 1
    conn.commit()
    worker.drain(conn, env)
    assert run_row(conn)['state'] == 'applied' and len(provider.calls) == 1
    assert counts(conn) == {'patterns': 1, 'documents': 1, 'audits': 1, 'dependencies': 4}
    with pytest.raises(ValueError, match='not_recoverable'):
        store.recover_synthesis_run(conn, env, str(run['id']), reason='again')


def test_stuck_pending_run_without_live_job_is_closed_so_the_policy_continues(conn, env, monkeypatch):
    from agentic_rag import synthesis
    install(monkeypatch, fx.ForbiddenProvider())
    forward(conn, env, 'K1')
    conn.execute("UPDATE mining_queue SET status='error',finished_at=now() WHERE kind='synthesis'")
    conn.commit()
    synthesis.schedule(conn, env)
    first = conn.execute("SELECT state,code FROM synthesis_runs ORDER BY created_at LIMIT 1").fetchone()
    assert (first['state'], first['code']) == ('error', 'job_failed')
