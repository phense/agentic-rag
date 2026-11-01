"""RAG-067 T067-004: central admission captures a service-owned, permitted policy
bundle; the worker binds it before the provider and keeps it across retries."""
from dataclasses import replace

import pytest

from agentic_rag import db, extraction_policy as ep, llm, mining
from agentic_rag.service.auth import Policy
from agentic_rag.service.engine import ServiceError
from agentic_rag.service.ingest import accept, retry_receipt
from .test_auth import policy_file
from .test_ingest import envelope
from .test_scope import service_store  # noqa: F401

KEY = 'one.synthetic-long-random-machine-secret'
POLICY_A = '''version = 1
[global]
guidance = "Keep confirmed decisions."
[[rules]]
domain = "alpha"
categories = ["memories", "assertions"]
'''
POLICY_B = 'version = 1\n[global]\ncategories = []\n'


def output():
    return {'memories': [{'title': 'Port declaration', 'body': 'server port is now 9000', 'domain': 'alpha', 'edges': [],
                          'claim_kind': 'stated', 'evidence': [{'source_id': 'event-1', 'quote': 'server port is now 9000'}]},
                         {'title': 'Foreign', 'body': 'server port is now 9000', 'domain': 'beta', 'edges': [],
                          'claim_kind': 'stated', 'evidence': [{'source_id': 'event-1', 'quote': 'server port is now 9000'}]}],
            'lessons': [{'title': 'Disabled lesson', 'body': 'server port is now 9000', 'domain': 'alpha', 'edges': [],
                         'claim_kind': 'inference', 'evidence': [{'source_id': 'event-1', 'quote': 'server port is now 9000'}]}]}


@pytest.fixture
def central(service_store, tmp_path):
    cfg, _ = service_store
    auth = policy_file(tmp_path)
    rules = tmp_path / 'extraction.toml'
    rules.write_text(POLICY_A)
    cfg = replace(cfg, service_auth_file=auth, mine_policy_file=rules)
    policy = Policy.load(auth)
    return cfg, policy, policy.authenticate_key(KEY), rules, auth


def queued(cfg, receipt):
    with db.connect(cfg) as conn:
        return dict(conn.execute('SELECT q.* FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id'
                                 ' WHERE w.id=%s', (receipt,)).fetchone())


def window(cfg, receipt):
    with db.connect(cfg) as conn:
        return dict(conn.execute('SELECT * FROM service_windows WHERE id=%s', (receipt,)).fetchone())


def test_admission_captures_only_permitted_domains_and_clients_cannot_supply_policy(central):
    cfg, policy, principal, _, _ = central
    receipt = accept(cfg, principal, policy, envelope(session='capture'))['receipt']
    captured = window(cfg, receipt)['payload']['_extraction_policy']
    bundle = ep.validate_capture(captured)
    assert bundle.domains == {'alpha'} and 'beta' not in repr(captured)
    for field in ('_extraction_policy', 'extraction_policy'):
        forged = envelope(session='forged-' + field)
        forged[field] = captured
        with pytest.raises(ServiceError) as caught:
            accept(cfg, principal, policy, forged)
        assert caught.value.code == 'invalid_window'


def test_invalid_file_fails_admission_visibly_without_consuming_the_cursor(central):
    cfg, policy, principal, rules, _ = central
    rules.write_text('version = 1\n[[rules]]\ndomain = "alpha"\nwrite_domains = ["*"]\n')
    with pytest.raises(ServiceError) as caught:
        accept(cfg, principal, policy, envelope(session='invalid'))
    assert (caught.value.code, caught.value.status) == ('extraction_policy_invalid', 503)
    assert 'write_domains' not in str(caught.value)
    session = principal.session_id('invalid')
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM service_windows WHERE session_id=%s', (session,)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) n FROM service_streams WHERE session_id=%s', (session,)).fetchone()['n'] == 0
    rules.write_text(POLICY_A)
    assert accept(cfg, principal, policy, envelope(session='invalid'))['durable'] is True


def test_worker_binds_before_provider_enforces_and_keeps_policy_across_retry(central, monkeypatch):
    from agentic_rag.service.worker import process_source
    cfg, policy, principal, rules, _ = central
    receipt = accept(cfg, principal, policy, envelope(session='retry'))['receipt']
    admitted = window(cfg, receipt)['payload']['_extraction_policy']['digest']
    calls = []

    def flaky(prompt, *args, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise llm.LLMUnavailableError('synthetic outage')
        return output()
    monkeypatch.setattr(mining, 'run_structured', flaky)
    job = queued(cfg, receipt)
    with db.connect(cfg) as conn:
        with pytest.raises(llm.LLMUnavailableError):
            process_source(conn, cfg, job)
    assert window(cfg, receipt)['state'] == 'blocked'
    rules.write_text(POLICY_B)  # every category disabled now; the admitted job keeps A
    retry_receipt(cfg, principal, policy, receipt)
    with db.connect(cfg) as conn:
        result = process_source(conn, cfg, queued(cfg, receipt))
        assert result.saved == 1 and len(calls) == 2
        assert 'Keep confirmed decisions.' in calls[1]
        session = principal.session_id('retry')
        rows = conn.execute("SELECT title,domain,project_scope,provenance->>'extraction_policy' p FROM documents"
                            " WHERE provenance->>'session_id'=%s", (session,)).fetchall()
        assert [dict(r) for r in rows] == [{'title': 'Port declaration', 'domain': 'alpha',
                                            'project_scope': '/projects/a', 'p': admitted}]
        batch = conn.execute('SELECT extraction FROM mining_batches WHERE session_id=%s', (session,)).fetchone()['extraction']['_policy']
        assert batch['digest'] == admitted and batch['rejected'] == {'lessons': {'category_disabled': 1}}
        binding = conn.execute('SELECT origin,digest FROM extraction_policy_bindings WHERE session_id=%s', (session,)).fetchone()
        assert binding == {'origin': 'window', 'digest': admitted}
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: pytest.fail('replay must not call the provider'))
    with db.connect(cfg) as conn:
        assert process_source(conn, cfg, queued(cfg, receipt)).saved == 1


def test_new_admission_after_change_uses_the_new_policy_and_all_disabled_skips_the_provider(central, monkeypatch):
    from agentic_rag.service.worker import process_source
    cfg, policy, principal, rules, _ = central
    rules.write_text(POLICY_B)
    receipt = accept(cfg, principal, policy, envelope(session='disabled'))['receipt']
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: pytest.fail('all-disabled policy must not call'))
    with db.connect(cfg) as conn:
        result = process_source(conn, cfg, queued(cfg, receipt))
    assert result.saved == 0 and result.skipped == 'extraction disabled by policy'
    assert window(cfg, receipt)['state'] == 'applied'


def test_revoked_domain_after_admission_writes_nothing(central, monkeypatch):
    from agentic_rag.service.worker import JobBlocked, process_source
    cfg, policy, principal, _, auth = central
    receipt = accept(cfg, principal, policy, envelope(session='narrowed'))['receipt']
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: output())
    # The machine may now write only 'beta': the admitted bundle has 'alpha' only.
    auth.write_text(auth.read_text().replace('read_domains = ["alpha"]\nwrite_domains = ["alpha"]',
                                             'read_domains = ["alpha", "beta"]\nwrite_domains = ["beta"]'))
    with db.connect(cfg) as conn:
        with pytest.raises(JobBlocked):
            process_source(conn, cfg, queued(cfg, receipt))
        assert conn.execute("SELECT count(*) n FROM documents WHERE provenance->>'session_id'=%s",
                            (principal.session_id('narrowed'),)).fetchone()['n'] == 0


def test_legacy_window_without_metadata_uses_builtin_rules(central, monkeypatch):
    from agentic_rag.service.worker import process_source
    cfg, policy, principal, rules, _ = central
    receipt = accept(replace(cfg, mine_policy_file=None), principal, policy, envelope(session='legacy'))['receipt']
    assert '_extraction_policy' not in window(cfg, receipt)['payload']
    rules.write_text(POLICY_B)
    prompts = []
    monkeypatch.setattr(mining, 'run_structured', lambda prompt, *a, **k: prompts.append(prompt) or output())
    with db.connect(cfg) as conn:
        result = process_source(conn, cfg, queued(cfg, receipt))
        assert result.saved == 2  # builtin keeps the alpha memory and lesson; beta stays outside authority
        assert conn.execute('SELECT origin FROM extraction_policy_bindings WHERE session_id=%s',
                            (principal.session_id('legacy'),)).fetchone()['origin'] == 'legacy'
    assert 'OPERATOR EXTRACTION PREFERENCES' not in prompts[0]
