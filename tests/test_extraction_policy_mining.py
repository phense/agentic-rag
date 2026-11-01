"""RAG-067 T067-004: local admission capture, binding before the provider, retry,
replay, legacy work and deterministic enforcement on all eight channels.

Every case runs actual mining: transcript file -> read_window -> real prompt ->
mock provider -> unchanged grounding -> enforcement -> audited gateways.
"""
from dataclasses import replace
import json

import pytest

from agentic_rag import domains, extraction_policy as ep, jobs, llm, mining, store, worker
from agentic_rag.benchmark import extraction_policy as fx
from agentic_rag.mining import MineResult
from test_extraction_policy_fixtures import frozen

LABELS = frozen()[1]['cases']


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)


@pytest.fixture
def base(cfg, conn):
    for name in ('programming', 'operations'):
        domains.add_domain(conn, name)
    return replace(cfg, ollama_url='http://127.0.0.1:1', mine_debounce_seconds=0)


def configured(cfg, name):
    return replace(cfg, mine_policy_file=fx.policy_path(name))


def admit(conn, cfg, case, tmp_path, session=None):
    path = fx.write_transcript(tmp_path / f"{session or case['session']}.jsonl", case['events'])
    assert jobs.enqueue_mine(conn, cfg, session_id=session or case['session'], transcript_path=path, project=case['project'])
    return job(conn, session or case['session'])


def job(conn, session):
    row = conn.execute("SELECT id,kind,session_id,transcript_path,payload,last_uuid,attempts FROM mining_queue"
                       " WHERE session_id=%s ORDER BY id DESC LIMIT 1", (session,)).fetchone()
    conn.commit()
    return dict(row)


def run(conn, cfg, queued):
    queued = {**queued, 'attempts': queued['attempts'] + 1}
    result = worker.process_job(conn, cfg, queued)
    worker._complete(conn, queued['id'], result)
    return result


def provider(monkeypatch, case_id, outputs=None):
    case = fx.case(case_id)
    mock = fx.MockProvider(case['provider'] if outputs is None else outputs, case['events'])
    monkeypatch.setattr(mining, 'run_structured', mock)
    return mock


@pytest.mark.parametrize('case_id', ['R1', 'L1', 'D1', 'S1'])
def test_frozen_cases_through_local_queue(case_id, base, conn, tmp_path, monkeypatch):
    case, label = fx.case(case_id), LABELS[case_id]
    cfg = configured(base, case['policy'])
    queued = admit(conn, cfg, case, tmp_path)
    captured = queued['payload']['extraction_policy']
    assert ep.validate_capture(captured).digest == captured['digest']
    mock = provider(monkeypatch, case_id)
    result = run(conn, cfg, queued)
    assert mock.calls == label['provider_calls']
    assert fx.retained(conn, case['session']) == label['retained']
    policy = fx.batch_policy(conn, case['session'])
    assert policy['digest'] == captured['digest'] and policy['rejected'] == label['rejected']
    rows = {r['title']: r for r in conn.execute(
        "SELECT d.title,d.body,d.provenance,c.kind,(SELECT json_agg(e.quote ORDER BY e.quote) FROM claim_evidence e"
        " WHERE e.document_id=d.id) quotes FROM documents d JOIN claim_records c ON c.document_id=d.id"
        " WHERE d.provenance->>'session_id'=%s", (case['session'],))}
    for title, kind in label.get('claim_kinds', {}).items():
        assert rows[title]['kind'] == kind, title
    for title, quote in label.get('exact_quotes', {}).items():
        assert rows[title]['quotes'] == [quote] and any(quote in e['text'] for e in case['events'])
    for title, links in label.get('evidence_links', {}).items():
        assert len(rows[title]['quotes'] or []) == links
    if 'secret_absent' in label:
        assert all(label['secret_absent'] not in json.dumps(r, default=str) for r in rows.values())
    assert all(r['provenance']['extraction_policy'] == captured['digest'] for r in rows.values())
    foreign = conn.execute("SELECT count(*) n FROM documents WHERE provenance->>'session_id'=%s"
                           " AND (project_scope<>%s OR domain NOT IN ('programming','operations'))",
                           (case['session'], case['project'])).fetchone()['n']
    assert foreign == label['foreign_writes'] == 0
    assert result.new_last_uuid is not None
    binding = conn.execute("SELECT digest,origin FROM extraction_policy_bindings WHERE session_id=%s",
                           (case['session'],)).fetchone()
    assert binding == {'digest': captured['digest'], 'origin': 'queue'}
    prompt = mock.prompts[0]
    assert 'OPERATOR EXTRACTION PREFERENCES' in prompt
    assert prompt.index('OPERATOR EXTRACTION PREFERENCES') < prompt.index(fx.SOURCE_MARKER.strip())


@pytest.mark.parametrize('replacement', ['replacement_policy', 'malformed_policy'])
def test_policy_change_during_provider_failure_retry_keeps_the_admitted_policy(replacement, base, conn, tmp_path, monkeypatch):
    case, label = fx.case('P1'), LABELS['P1']
    cfg_a = configured(base, case['policy'])
    queued = admit(conn, cfg_a, case, tmp_path)
    admitted = queued['payload']['extraction_policy']['digest']
    mock = provider(monkeypatch, 'P1')
    with pytest.raises(llm.LLMUnavailableError):
        worker.process_job(conn, cfg_a, {**queued, 'attempts': 1})
    conn.rollback()
    # The binding committed before the failed call; no batch, no cursor movement.
    assert conn.execute("SELECT digest FROM extraction_policy_bindings WHERE session_id=%s",
                        (case['session'],)).fetchone()['digest'] == admitted
    assert conn.execute("SELECT count(*) n FROM mining_batches WHERE session_id=%s", (case['session'],)).fetchone()['n'] == 0
    # The operator replaces the file (B disables lessons; or a malformed file): the retry keeps A.
    monkeypatch.setattr(ep, 'load_file', lambda *a, **k: pytest.fail('a retry must not read the file'))
    result = worker.process_job(conn, configured(base, case[replacement]), {**queued, 'attempts': 2})
    assert result.saved == 1
    assert mock.calls == label['provider_calls_until_accepted']
    assert fx.retained(conn, case['session']) == label['retained_on_retry']
    assert fx.batch_policy(conn, case['session'])['digest'] == admitted
    replay = provider(monkeypatch, 'P1', outputs=[])
    assert worker.process_job(conn, configured(base, case[replacement]), {**queued, 'attempts': 3}).saved == 1
    assert replay.calls == label['provider_calls_on_replay'] == 0


def test_new_admission_after_replacement_uses_the_new_policy_and_malformed_fails_visibly(base, conn, tmp_path, monkeypatch):
    case, label = fx.case('P1'), LABELS['P1']
    first = admit(conn, configured(base, case['policy']), case, tmp_path)['payload']['extraction_policy']['digest']
    cfg_b = configured(base, case['replacement_policy'])
    queued = admit(conn, cfg_b, case, tmp_path, session=case['new_session'])
    assert queued['payload']['extraction_policy']['digest'] != first
    provider(monkeypatch, 'P1', outputs=[fx.case('P1')['provider'][1]])
    run(conn, cfg_b, queued)
    assert fx.batch_policy(conn, case['new_session'])['rejected'] == label['new_admission_after_replacement']['rejected']
    before = conn.execute("SELECT count(*) n FROM mining_queue").fetchone()['n']
    with pytest.raises(ep.PolicyError):
        jobs.enqueue_mine(conn, configured(base, case['malformed_policy']), session_id='rag067-p1-malformed',
                          transcript_path=str(tmp_path / 'x.jsonl'), project=case['project'])
    assert conn.execute("SELECT count(*) n FROM mining_queue").fetchone()['n'] - before == 0


def test_replay_after_acceptance_makes_no_provider_call(base, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    cfg = configured(base, case['policy'])
    queued = admit(conn, cfg, case, tmp_path)
    provider(monkeypatch, 'R1')
    with pytest.raises(RuntimeError):
        mining.mine_session(conn, cfg, session_id=case['session'], transcript_path=queued['transcript_path'],
                            last_uuid=None, project=case['project'], policy=queued['payload']['extraction_policy'],
                            policy_origin='queue', before_apply=lambda: (_ for _ in ()).throw(RuntimeError('crash')))
    replay = provider(monkeypatch, 'R1', outputs=[])
    monkeypatch.setattr(ep, 'load_file', lambda *a, **k: pytest.fail('accepted output wins before reading files'))
    result = worker.process_job(conn, configured(base, 'policy-invalid.toml'), {**queued, 'attempts': 2})
    assert result.saved == 1 and replay.calls == 0


def test_rerun_and_has_more_continuation_retain_one_bundle(base, conn, tmp_path):
    case = fx.case('R1')
    queued = admit(conn, configured(base, 'policy-a.toml'), case, tmp_path)
    captured = queued['payload']['extraction_policy']
    assert not jobs.enqueue_mine(conn, configured(base, 'policy-b.toml'), session_id=case['session'],
                                 transcript_path=queued['transcript_path'], project=case['project'])
    worker._complete(conn, queued['id'], MineResult(new_last_uuid='next', has_more=True))
    again = job(conn, case['session'])
    assert again['id'] == queued['id'] and again['payload']['extraction_policy'] == captured
    assert 'rerun_requested' not in again['payload']


def test_without_a_policy_file_payload_and_prompt_are_unchanged(base, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    queued = admit(conn, base, case, tmp_path)
    assert queued['payload'] == {'project': case['project']}
    seen = []
    monkeypatch.setattr(mining, 'run_structured', lambda prompt, schema, cfg, **kw: seen.append((prompt, schema, kw['system'])) or {})
    run(conn, base, queued)
    window = mining.read_window(queued['transcript_path'], after_uuid=None, max_chars=base.mine_max_digest_chars,
                                per_block=base.mine_per_block_chars)
    names = ['operations', 'programming']
    assert seen == [(mining.build_prompt(window.text, names, []) + fx.SOURCE_MARKER + json.dumps(window.events, ensure_ascii=False),
                     mining.build_schema(names), mining.SYSTEM)]
    binding = conn.execute("SELECT origin,digest FROM extraction_policy_bindings WHERE session_id=%s", (case['session'],)).fetchone()
    assert binding['origin'] == 'legacy' and binding['digest'] == ep.builtin_bundle('/synthetic/team-a', names).digest


def test_legacy_job_never_uses_todays_file(base, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    queued = admit(conn, base, case, tmp_path)  # admitted without a policy file (legacy payload)
    mock = provider(monkeypatch, 'R1')
    monkeypatch.setattr(ep, 'load_file', lambda *a, **k: pytest.fail('legacy work must not read the file'))
    run(conn, configured(base, 'policy-disabled.toml'), queued)
    assert mock.calls == 1
    assert fx.retained(conn, case['session']) == {'memories': ['HNSW decision'], 'lessons': ['IVFFlat experiment'],
                                                  'signals': ['Index row size']}
    assert 'OPERATOR EXTRACTION PREFERENCES' not in mock.prompts[0]


def test_all_disabled_policy_accepts_an_empty_batch_without_a_provider_call(base, conn, tmp_path, monkeypatch):
    case, label = fx.case('Z1'), LABELS['Z1']
    cfg = configured(base, case['policy'])
    queued = admit(conn, cfg, case, tmp_path)
    mock = provider(monkeypatch, 'Z1')
    result = run(conn, cfg, queued)
    assert mock.calls == label['provider_calls'] == 0
    assert result.skipped == label['skip_reason'] and result.saved == 0
    batch = conn.execute("SELECT output_cursor,applied_at FROM mining_batches WHERE session_id=%s", (case['session'],)).fetchone()
    assert batch['applied_at'] is not None and batch['output_cursor'] == result.new_last_uuid is not None


def test_malformed_captured_snapshot_blocks_without_consuming_the_cursor(base, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    queued = admit(conn, configured(base, 'policy-a.toml'), case, tmp_path)
    broken = json.loads(json.dumps(queued['payload']['extraction_policy']))
    broken['snapshot']['project'] = '/elsewhere'
    mock = provider(monkeypatch, 'R1')
    with pytest.raises(ep.PolicySnapshotError):
        worker.process_job(conn, base, {**queued, 'payload': {**queued['payload'], 'extraction_policy': broken}, 'attempts': 1})
    conn.rollback()
    assert mock.calls == 0
    assert conn.execute("SELECT count(*) n FROM extraction_policy_bindings").fetchone()['n'] == 0
    assert conn.execute("SELECT last_uuid FROM mining_queue WHERE id=%s", (queued['id'],)).fetchone()['last_uuid'] is None


def test_direct_mining_binds_once_and_reuses_the_binding(base, conn, tmp_path, monkeypatch):
    case = fx.case('P1')
    path = fx.write_transcript(tmp_path / 'direct.jsonl', case['events'])
    provider(monkeypatch, 'P1')
    with pytest.raises(llm.LLMUnavailableError):
        mining.mine_session(conn, configured(base, 'policy-a.toml'), session_id='direct', transcript_path=path,
                            last_uuid=None, project=case['project'])
    monkeypatch.setattr(ep, 'load_file', lambda *a, **k: pytest.fail('a bound direct cursor must not reread the file'))
    result = mining.mine_session(conn, configured(base, 'policy-b.toml'), session_id='direct', transcript_path=path,
                                 last_uuid=None, project=case['project'])
    assert result.saved == 1
    assert conn.execute("SELECT origin FROM extraction_policy_bindings WHERE session_id='direct'").fetchone()['origin'] == 'direct'


@pytest.mark.parametrize('new_project', [None, '/synthetic/team-b'])
def test_new_job_cannot_silently_use_an_older_failed_jobs_policy(new_project, base, conn, tmp_path, monkeypatch):
    # Mutation caught: returning the old binding despite a new admitted digest.
    case = fx.case('P1')
    cfg_a = replace(configured(base, 'policy-a.toml'), worker_max_attempts=1)
    first = admit(conn, cfg_a, case, tmp_path)
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('provider outage')))
    assert worker.drain(conn, cfg_a, max_jobs=1)['failed'] == 1
    assert conn.execute('SELECT status FROM mining_queue WHERE id=%s', (first['id'],)).fetchone()['status'] == 'error'
    conn.commit()
    cfg_b = replace(configured(base, 'policy-b.toml'), worker_max_attempts=1)
    second = admit(conn, cfg_b, {**case, 'project': new_project or case['project']}, tmp_path)
    mock = provider(monkeypatch, 'P1', outputs=[case['provider'][1]])
    report = worker.drain(conn, cfg_b, max_jobs=1)
    state = conn.execute('SELECT status,last_error,last_uuid FROM mining_queue WHERE id=%s', (second['id'],)).fetchone()
    assert report['done'] == 0 and report['failed'] == 1
    assert state == {'status': 'error', 'last_error': 'extraction_policy_conflict', 'last_uuid': None}
    assert mock.calls == 0
    assert conn.execute('SELECT count(*) n FROM mining_batches').fetchone()['n'] == 0
    assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n'] == 0
    assert conn.execute('SELECT digest FROM extraction_policy_bindings').fetchone()['digest'] == first['payload']['extraction_policy']['digest']
    conn.commit()
    # Supported recovery: restore the original policy and project for a new
    # ordinary admission; preserve both failed jobs and the immutable binding.
    recovery = admit(conn, cfg_a, case, tmp_path)
    assert worker.drain(conn, cfg_a, max_jobs=1)['done'] == 1
    assert mock.calls == 1
    assert conn.execute('SELECT status FROM mining_queue WHERE id=%s', (recovery['id'],)).fetchone()['status'] == 'done'
    assert conn.execute('SELECT status FROM mining_queue WHERE id=%s', (second['id'],)).fetchone()['status'] == 'error'


def test_valid_snapshot_for_another_project_is_rejected_before_binding(base, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    cfg = configured(base, 'policy-a.toml')
    queued = admit(conn, cfg, case, tmp_path)
    foreign = ep.capture(cfg, '/synthetic/foreign', ['operations', 'programming'])
    mock = provider(monkeypatch, 'R1')
    with pytest.raises(ep.PolicySnapshotError, match='policy_snapshot_invalid'):
        worker.process_job(conn, cfg, {**queued, 'payload': {**queued['payload'], 'extraction_policy': foreign}})
    conn.rollback()
    assert mock.calls == 0
    assert conn.execute('SELECT count(*) n FROM extraction_policy_bindings').fetchone()['n'] == 0


def test_direct_retry_cannot_apply_a_bound_policy_to_another_project(base, conn, tmp_path, monkeypatch):
    case = fx.case('P1')
    path = fx.write_transcript(tmp_path / 'direct-project.jsonl', case['events'])
    mock = provider(monkeypatch, 'P1')
    with pytest.raises(llm.LLMUnavailableError):
        mining.mine_session(conn, configured(base, 'policy-a.toml'), session_id='direct-project',
                            transcript_path=path, last_uuid=None, project=case['project'])
    with pytest.raises(ValueError, match='^extraction_policy_conflict$'):
        mining.mine_session(conn, configured(base, 'policy-b.toml'), session_id='direct-project',
                            transcript_path=path, last_uuid=None, project='/synthetic/team-b')
    assert mock.calls == 1
    assert conn.execute('SELECT count(*) n FROM mining_batches').fetchone()['n'] == 0


@pytest.mark.parametrize('captured', [False, True])
def test_domain_add_does_not_strand_builtin_retry_or_unchanged_policy_recovery(captured, base, conn, tmp_path, monkeypatch):
    # Mutation caught: comparing the whole bundle digest, including domain set.
    case = fx.case('R1')
    cfg = replace(configured(base, 'policy-a.toml') if captured else base, worker_max_attempts=1)
    first = admit(conn, cfg, case, tmp_path)
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('provider outage')))
    assert worker.drain(conn, cfg, max_jobs=1)['failed'] == 1
    before = dict(conn.execute('SELECT xmin::text revision,* FROM extraction_policy_bindings').fetchone())
    domains.add_domain(conn, 'gamma')
    conn.commit()
    if captured:
        # A newly admitted job captures the unchanged file over a larger set.
        queued = admit(conn, cfg, case, tmp_path)
        assert queued['payload']['extraction_policy']['digest'] != before['digest']
    else:
        # Retry the exact same legacy job, not merely a new admission.
        queued = {**first, 'attempts': 2}
    mock = provider(monkeypatch, 'R1')
    result = worker.process_job(conn, cfg, queued)
    worker._complete(conn, queued['id'], result)
    assert result.saved >= 1 and mock.calls == 1
    assert conn.execute('SELECT status FROM mining_queue WHERE id=%s', (queued['id'],)).fetchone()['status'] == 'done'
    after = dict(conn.execute('SELECT xmin::text revision,* FROM extraction_policy_bindings').fetchone())
    assert after == before
    batch = conn.execute('SELECT domains,extraction FROM mining_batches').fetchone()
    assert set(batch['domains']) == {'operations', 'programming'}
    assert batch['extraction']['_policy']['digest'] == before['digest']


@pytest.mark.parametrize('change', ['common_domain', 'domainless', 'legacy_downgrade'])
def test_domain_set_tolerance_still_refuses_real_policy_changes(change, base, conn, tmp_path, monkeypatch):
    case = fx.case('P1')
    queued = admit(conn, base, case, tmp_path)
    original = {'version': 1, 'rules': [{'domain': 'programming', 'categories': ['memories']}]}
    first = ep.build_bundle(ep.parse_document(original), case['project'], ['operations', 'programming']).capture()
    queued = {**queued, 'payload': {**queued['payload'], 'extraction_policy': first}}
    mock = provider(monkeypatch, 'P1')
    with pytest.raises(llm.LLMUnavailableError):
        worker.process_job(conn, base, queued)
    before = dict(conn.execute('SELECT xmin::text revision,* FROM extraction_policy_bindings').fetchone())
    if change == 'legacy_downgrade':
        payload = {'project': case['project']}
    else:
        altered = json.loads(json.dumps(original))
        if change == 'common_domain':
            altered['rules'][0]['categories'] = ['lessons']
        else:
            altered['global'] = {'guidance': 'Changed pin and domainless preferences.'}
        second = ep.build_bundle(ep.parse_document(altered), case['project'], ['operations', 'programming', 'gamma']).capture()
        payload = {**queued['payload'], 'extraction_policy': second}
    with pytest.raises(ValueError, match='^extraction_policy_conflict$'):
        worker.process_job(conn, base, {**queued, 'payload': payload})
    assert mock.calls == 1
    assert dict(conn.execute('SELECT xmin::text revision,* FROM extraction_policy_bindings').fetchone()) == before
    assert conn.execute('SELECT count(*) n FROM mining_batches').fetchone()['n'] == 0


def test_enforcement_filters_all_eight_channels_deterministically():
    policy = ep.parse_document({'version': 1, 'global': {'categories': ['memories', 'assertions', 'contradictions',
                                                                       'pin_suggestions'], 'max_items_per_category': 1,
                                                        'max_body_chars': 20}})
    bundle = ep.build_bundle(policy, '/p', ['alpha'])
    item = lambda domain, body='short': {'title': 't', 'body': body, 'domain': domain}
    data = {'memories': [item('alpha'), item('alpha'), item('beta'), item('alpha', 'x' * 21)],
            'lessons': [item('alpha')], 'signals': [item('alpha')],
            'assertions': [{'entity': 'e', 'attribute': 'a', 'value': 'v', 'domain': 'alpha'}],
            'contradictions': [{'slug': 's', 'statement': 'st', 'quote': 'q', 'domain': 'alpha'}],
            'pin_suggestions': [{'body': 'b', 'scope': 'global', 'reason': 'r'}] * 2,
            'contradictions_with_pins': [{'pin': 'p', 'statement': 's', 'quote': 'q'}],
            'domain_proposals': [{'name': 'n', 'description': 'd', 'reason': 'r'}]}
    kept, report = ep.enforce(data, bundle)
    assert {k: len(v) for k, v in kept.items()} == {'memories': 1, 'lessons': 0, 'signals': 0, 'assertions': 1,
                                                    'contradictions': 1, 'pin_suggestions': 1,
                                                    'contradictions_with_pins': 0, 'domain_proposals': 0}
    assert report['rejected'] == {'memories': {'item_limit': 1, 'domain_not_bound': 1, 'body_limit': 1},
                                  'lessons': {'category_disabled': 1}, 'signals': {'category_disabled': 1},
                                  'pin_suggestions': {'item_limit': 1},
                                  'contradictions_with_pins': {'category_disabled': 1},
                                  'domain_proposals': {'category_disabled': 1}}
    assert 'short' not in json.dumps(report)
    assert ep.all_disabled(ep.build_bundle(ep.parse_document({'version': 1, 'global': {'categories': []}}), '/p', ['alpha']), ['alpha'])
    assert not ep.all_disabled(bundle, ['alpha'])
