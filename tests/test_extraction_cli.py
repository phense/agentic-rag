"""RAG-067 T067-005: `rag extraction validate|inspect|dry-run` through the public CLI."""
from dataclasses import replace
import json

import pytest

from agentic_rag import cli, domains, extraction_policy as ep, jobs, llm, mining, store
from agentic_rag.benchmark import extraction_policy as fx
from agentic_rag.config import Config
from test_extraction_policy_fixtures import frozen


@pytest.fixture
def rag(cfg, conn, tmp_path, monkeypatch, capsys):
    for name in ('programming', 'operations'):
        domains.add_domain(conn, name)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('no provider call without --evaluate')
    monkeypatch.setattr(mining, 'run_structured', forbidden)
    monkeypatch.setattr(llm, 'run_structured', forbidden)
    state = {'cfg': replace(cfg, ollama_url='http://127.0.0.1:1')}
    monkeypatch.setattr(cli, 'load_config', lambda *a, **k: state['cfg'])

    def call(*argv, config=None):
        if config is not None:
            state['cfg'] = config
        code = cli.main(['extraction', *argv])
        out = capsys.readouterr()
        return code, (json.loads(out.out) if out.out.strip() else None), out.err
    call.calls = calls
    call.state = state
    return call


def writes(conn):
    return conn.execute("SELECT (SELECT count(*) FROM audit_log)+(SELECT count(*) FROM documents)"
                        "+(SELECT count(*) FROM mining_queue)+(SELECT count(*) FROM extraction_policy_bindings) n").fetchone()['n']


def test_validate_reports_identity_caps_and_safe_errors(rag, conn):
    before = writes(conn)
    code, out, _ = rag('validate', '--file', str(fx.policy_path('policy-a.toml')))
    assert code == 0 and out['valid'] and out['identity'].startswith('xf1:') and out['rules'] == 3
    assert out['caps']['max_items_per_category']['memories'] == 8 and out['caps']['guidance_chars'] == 2000
    code, out, _ = rag('validate', '--file', str(fx.policy_path('policy-invalid.toml')))
    assert code == 1 and out['errors'] == frozen()[1]['cases']['V1']['errors']
    code, out, _ = rag('validate')
    assert code == 0 and out == {'valid': True, 'configured': False, 'policy': 'builtin', 'provider_calls': 0, 'writes': 0}
    assert writes(conn) == before and rag.calls == []


def test_inspect_explains_scope_precedence_digest_and_limits(rag, conn):
    labels = frozen()[1]['effective']
    code, out, _ = rag('inspect', '--file', str(fx.policy_path('policy-a.toml')), '--project', '/synthetic/team-b')
    assert code == 0 and out['source'] == 'file' and out['bundle_digest'].startswith('xb1:')
    assert out['precedence'] == ['builtin', 'global', 'domain', 'project', 'exact']
    for name in ('programming', 'operations'):
        expected = labels[f'{name}@/synthetic/team-b']
        assert out['domains'][name]['scopes'] == expected['scopes']
        assert out['domains'][name]['categories'] == [c for c in expected['categories'] if c in ep.DOMAIN_CHANNELS]
        assert out['domains'][name]['limits']['memories'] == expected['max_items_per_category']
    assert out['domainless']['scopes'] == labels['domainless@/synthetic/team-b']['scopes']
    assert out['domainless']['categories'] == ['pin_suggestions']
    assert out['domains']['operations']['guidance'].startswith('Behalte')
    assert rag.calls == []


def test_inspect_queued_shows_admitted_legacy_and_bound_identities(rag, conn, cfg, tmp_path):
    case = fx.case('R1')
    path = fx.write_transcript(tmp_path / 't.jsonl', case['events'])
    jobs.enqueue_mine(conn, cfg, session_id='legacy-job', transcript_path=path, project=case['project'])
    configured = replace(cfg, mine_policy_file=fx.policy_path('policy-a.toml'))
    jobs.enqueue_mine(conn, configured, session_id='captured-job', transcript_path=path, project=case['project'])
    code, out, _ = rag('inspect', '--queued')
    admitted = [j['admitted'] for j in out['jobs']]
    assert code == 0 and admitted[0] == 'legacy-builtin' and admitted[1].startswith('xb1:')
    assert all(j['bound'] is None for j in out['jobs'])


def sample(tmp_path, case_id='R1', secret=False):
    events = [dict(e) for e in fx.case(case_id)['events']]
    if secret:
        events[0]['text'] += ' api_key=abcdefghijklmnop'
    path = tmp_path / 'sample.json'
    path.write_text(json.dumps({'events': events}))
    return path


def test_default_dry_run_never_calls_a_provider_or_writes(rag, conn, tmp_path):
    before = writes(conn)
    code, out, _ = rag('dry-run', '--file', str(fx.policy_path('policy-a.toml')), '--project', '/synthetic/team-a',
                       '--sample', str(sample(tmp_path, secret=True)))
    assert code == 0 and out['provider_calls'] == 0 and out['writes'] == 0 and out['would_call_provider']
    assert out['sample_redactions'] == 1 and 'abcdefghijklmnop' not in json.dumps(out)
    assert 'OPERATOR EXTRACTION PREFERENCES' in out['preferences']
    code, out, _ = rag('dry-run', '--file', str(fx.policy_path('policy-disabled.toml')), '--project', '/synthetic/team-a',
                       '--sample', str(sample(tmp_path)))
    assert out['all_disabled'] and not out['would_call_provider']
    assert writes(conn) == before and rag.calls == []


def test_explicit_evaluation_calls_the_provider_once_and_still_writes_nothing(rag, conn, tmp_path, monkeypatch):
    case = fx.case('R1')
    mock = fx.MockProvider(case['provider'], case['events'])
    monkeypatch.setattr(mining, 'run_structured', mock)
    before = writes(conn)
    code, out, _ = rag('dry-run', '--file', str(fx.policy_path('policy-a.toml')), '--project', case['project'],
                       '--sample', str(sample(tmp_path)), '--evaluate')
    assert code == 0 and mock.calls == 1 and out['provider_calls'] == 1 and out['writes'] == 0
    assert [i['title'] for i in out['retained']['memories']] == ['HNSW decision']
    assert out['rejected'] == frozen()[1]['cases']['R1']['rejected']
    assert writes(conn) == before


def test_client_mode_refuses_service_policy_operations(rag, conn, tmp_path):
    client = replace(Config(), service_mode='client', service_url='https://service.invalid')
    for argv in (['inspect', '--project', '/p', '--domain', 'x'], ['inspect', '--queued'],
                 ['dry-run', '--project', '/p', '--sample', str(sample(tmp_path))],
                 ['dry-run', '--file', str(fx.policy_path('policy-a.toml')), '--project', '/p', '--domain', 'x',
                  '--sample', str(sample(tmp_path)), '--evaluate']):
        code, out, err = rag(*argv, config=client)
        assert code == 1 and out is None and 'unsupported_in_client_mode' in err, argv
    code, out, _ = rag('validate', '--file', str(fx.policy_path('policy-a.toml')), config=client)
    assert code == 0 and out['valid']
    code, out, _ = rag('inspect', '--file', str(fx.policy_path('policy-a.toml')), '--project', '/synthetic/team-a',
                       '--domain', 'programming', config=client)
    assert code == 0 and list(out['domains']) == ['programming']
    assert rag.calls == []
