"""T06827: A2 success/recovery through real collaborating components.

Real: isolated PostgreSQL store, authenticated source acceptance, mining queue,
fenced singleton worker, accepted-batch replay, audited gateway, RLS-scoped
writer, request queue, API lifespan consumers and the actual RemoteClient.
Simulated only: the extraction provider (scripted output) and the two Ollama
HTTP daemons (deterministic vectors, injectable digest swap/outage). These
tests are no physical model, vector-parity or 40-client acceptance.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import threading
import uuid

import httpx
import pytest
from starlette.testclient import TestClient

from agentic_rag import db, mining, worker
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config, load_config
from agentic_rag.service.auth import Policy
from agentic_rag.service.fence import worker_scope
from agentic_rag.service.ingest import accept
from .test_auth import policy_file
from .test_ingest import envelope
from .test_model_lane import LANE, LANE_VECTOR, OTHER, PRIMARY, PRIMARY_VECTOR, ollama  # noqa: F401

KEY = 'one.synthetic-long-random-machine-secret'
TITLE = 'Port declaration'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'LOG_PATH', tmp_path / 'worker.log')
    policy = policy_file(tmp_path)
    with isolated_database(Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')) as base:
        with db.connect(base) as conn:
            conn.execute("INSERT INTO domains(name) VALUES ('alpha')")
        def configured(**settings):
            lines = ['[db]', f'name = "{base.db_name}"', f'host = "{base.db_host}"', '[service]',
                     'mode = "server"', f'auth_file = "{policy}"']
            lines += [f'{k} = {json.dumps(v)}' for k, v in settings.pop('service', {}).items()]
            lines += ['[rerank]', 'url = "http://127.0.0.1:1"', '[ollama]', f'url = "{PRIMARY}"']
            lines += [f'{k} = {json.dumps(v)}' for k, v in settings.items()]
            path = tmp_path / f'config-{uuid.uuid4().hex}.toml'
            path.write_text('\n'.join(lines) + '\n')
            return load_config(path)
        yield configured, policy


@pytest.fixture
def provider(monkeypatch):
    calls = []
    output = {'memories': [{'title': TITLE, 'body': 'server port is now 9000', 'domain': 'alpha', 'edges': [],
                            'claim_kind': 'stated', 'evidence': [{'source_id': 'event-1', 'quote': 'server port is now 9000'}]}]}
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: calls.append(1) or output)
    return calls


def submit(cfg, policy, session):
    loaded = Policy.load(policy)
    return accept(cfg, loaded.authenticate_key(KEY), loaded, envelope(session=session))['receipt']


def drain(cfg):
    with worker.acquire_database_lock(cfg) as keeper:
        assert keeper is not None
        with worker_scope(keeper), db.connect(cfg, role='writer') as conn:
            return worker.drain(conn, cfg, max_jobs=1)


def state(cfg, receipt):
    with db.connect(cfg) as conn:
        window = conn.execute("SELECT state,result->>'code' AS code,queue_id FROM service_windows WHERE id=%s", (receipt,)).fetchone()
        job = conn.execute('SELECT status,attempts,last_error FROM mining_queue WHERE id=%s', (window['queue_id'],)).fetchone()
        documents = conn.execute('SELECT id FROM documents WHERE title=%s', (TITLE,)).fetchall()
        vectors = [json.loads(r['v']) for r in conn.execute(
            'SELECT c.embedding::text v FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.title=%s', (TITLE,))]
        accepted = conn.execute('SELECT count(*) n FROM mining_batches WHERE applied_at IS NULL').fetchone()['n']
        audits = conn.execute("SELECT count(*) n FROM audit_log WHERE op='save_document'").fetchone()['n']
    return {'window': window['state'], 'code': window['code'], 'job': job['status'], 'attempts': job['attempts'],
            'error': job['last_error'], 'documents': len(documents), 'vectors': vectors, 'accepted': accepted, 'audits': audits}


def release(cfg, receipt):
    # Test scheduling only: the worker's 60 s pressure backoff is not waited for.
    with db.connect(cfg) as conn:
        conn.execute('UPDATE mining_queue SET next_attempt_at=now() WHERE id=(SELECT queue_id FROM service_windows WHERE id=%s)', (receipt,))


def test_success_lane_drains_original_through_gateway(runtime, ollama, provider):
    configured, policy = runtime
    cfg = configured(background_url=LANE, num_thread=2, background_num_thread=1, background_timeout_seconds=60)
    receipt = submit(cfg, policy, 'lane-success')
    assert drain(cfg)['done'] == 1
    after = state(cfg, receipt)
    assert after['window'] == 'applied' and after['documents'] == 1 and after['accepted'] == 0
    assert after['vectors'] and all(v == LANE_VECTOR for v in after['vectors'])
    assert provider == [1]
    assert ollama.embeds('lane.test') and not ollama.embeds('primary.test')
    assert {b.get('options', {}).get('num_thread') for _, _, b, _ in ollama.embeds('lane.test')} == {1}


@pytest.mark.parametrize('fault,code', [('swap_lane', 'background_model_identity'),
                                        ('swap_primary', 'background_model_identity'),
                                        ('down', 'background_model_unavailable')])
def test_lane_failure_retains_attempt_and_accepted_output_then_recovers(runtime, ollama, provider, fault, code):
    configured, policy = runtime
    cfg = configured(background_url=LANE)
    receipt = submit(cfg, policy, 'lane-' + fault)
    if fault == 'down':
        ollama.down.add('lane.test')
    else:
        host = 'lane.test' if fault == 'swap_lane' else 'primary.test'
        def swap_once(fake):
            fake.after_embed = None
            fake.digests[host] = OTHER
        ollama.after_embed = swap_once
    result = drain(cfg)
    assert result['done'] == 0 and result['failed'] == 1
    blocked = state(cfg, receipt)
    assert blocked['window'] == 'blocked' and blocked['code'] == code
    assert blocked['job'] == 'pending' and blocked['attempts'] == 0 and blocked['error'] == code
    assert blocked['documents'] == 0 and blocked['audits'] == 0 and blocked['accepted'] == 1
    assert provider == [1]
    # Daemon restored (same digest on both endpoints): the worker resumes from
    # the accepted batch without a second provider call.
    ollama.down.clear()
    ollama.digests.update({'lane.test': 'a' * 64, 'primary.test': 'a' * 64})
    release(cfg, receipt)
    assert drain(cfg)['done'] == 1
    applied = state(cfg, receipt)
    assert applied['window'] == 'applied' and applied['documents'] == 1 and applied['accepted'] == 0
    assert all(v == LANE_VECTOR for v in applied['vectors']) and provider == [1]


def test_config_rollback_restores_default_lane_without_deleting_work(runtime, ollama, provider):
    configured, policy = runtime
    lane = configured(background_url=LANE, service={'request_consumers': 4})
    receipt = submit(lane, policy, 'lane-rollback')
    ollama.down.add('lane.test')
    assert drain(lane)['failed'] == 1
    assert state(lane, receipt)['job'] == 'pending'
    # Key removal + restart: a fresh process loads the file without lane keys.
    default = configured()
    assert default.ollama_background_url is None and default.service_request_consumers == 2
    release(default, receipt)
    assert drain(default)['done'] == 1
    applied = state(default, receipt)
    assert applied['window'] == 'applied' and all(v == PRIMARY_VECTOR for v in applied['vectors'])
    assert provider == [1]
    timeouts = {t for h, _, _, t in ollama.embeds('primary.test')}
    assert timeouts == {10.0}  # unchanged default background deadline


def test_lane_and_default_workers_share_singleton_owner_lock(runtime):
    configured, _ = runtime
    lane, default = configured(background_url=LANE), configured()
    with worker.acquire_database_lock(lane) as first:
        assert first is not None
        with worker.acquire_database_lock(default) as second:
            assert second is None
    with worker.acquire_database_lock(default) as recovered:
        assert recovered is not None


def test_revoked_key_blocks_before_lane_inference(runtime, ollama, provider):
    configured, policy = runtime
    cfg = configured(background_url=LANE)
    receipt = submit(cfg, policy, 'lane-revoked')
    original = policy.read_text()
    policy.write_text(original.replace('[machines.vm1]', '[machines.vm1]\nenabled=false'))
    drain(cfg)
    revoked = state(cfg, receipt)
    assert revoked['window'] == 'blocked' and revoked['documents'] == 0
    assert provider == [] and ollama.embeds() == []
    policy.write_text(original)
    release(cfg, receipt)
    assert drain(cfg)['done'] == 1 and state(cfg, receipt)['documents'] == 1


# API consumers and the actual client.

def app(cfg, policy):
    from agentic_rag.service.api import create_app
    return create_app(cfg, policy, allowed_hosts=['testserver'])


def remote_config(tmp_path, cfg):
    token = tmp_path / 'client.key'
    token.write_text(KEY)
    token.chmod(0o600)
    return replace(Config(), service_mode='client', service_url='https://testserver', service_token_file=token,
                   service_spool_dir=tmp_path / 'spool')


def request_rows(cfg):
    with db.connect(cfg) as conn:
        return conn.execute("SELECT count(*) n FROM service_requests WHERE tool='memory_domains'").fetchone()['n']


def test_actual_client_completes_through_four_consumers_after_rate_limit(runtime, ollama, tmp_path):
    from agentic_rag.service.client import RemoteClient
    configured, policy = runtime
    cfg = configured(background_url=LANE, service={'request_consumers': 4})
    remote = remote_config(tmp_path, cfg)
    with TestClient(app(cfg, policy), base_url='https://testserver') as sender:
        headers = {'authorization': 'Bearer ' + KEY, 'x-rag-protocol': '1'}
        # Exhaust the unchanged 12/s namespace window with real control calls.
        codes = [sender.get('/v1/requests/' + str(uuid.uuid4()), headers=headers).status_code for _ in range(12)]
        assert codes == [404] * 12
        assert sender.get('/v1/requests/' + str(uuid.uuid4()), headers=headers).status_code == 429
        with RemoteClient(remote, sender=sender) as client:
            result = client.invoke('memory_domains', {}, seconds=10)
            assert client.spool.pending_requests() == []
    assert result == {'domains': [{'name': 'alpha', 'description': '', 'docs': 0}]}
    assert request_rows(cfg) == 1


def test_actual_client_lost_ack_replays_one_queued_request(runtime, ollama, tmp_path):
    from agentic_rag.service.client import RemoteClient
    configured, policy = runtime
    cfg = configured(service={'request_consumers': 2})
    remote = remote_config(tmp_path, cfg)
    with TestClient(app(cfg, policy), base_url='https://testserver') as real:
        class LostAck:
            lost = False
            @contextmanager
            def stream(self, method, url, **kwargs):
                with real.stream(method, url, **kwargs) as response:
                    if url.endswith('/v1/requests') and method == 'POST' and not self.lost:
                        self.lost = True
                        response.read()
                        raise httpx.ReadTimeout('synthetic lost ACK after commit')
                    yield response
        with RemoteClient(remote, sender=LostAck()) as client:
            assert client.invoke('memory_domains', {}, seconds=10)['domains'][0]['name'] == 'alpha'
    assert request_rows(cfg) == 1


def test_api_startup_rejects_consumers_beyond_pool_reserve(runtime, monkeypatch):
    import os
    configured, policy = runtime
    cfg = configured(service={'request_consumers': 3})
    monkeypatch.setattr(os, 'process_cpu_count', lambda: 1, raising=False)
    with pytest.raises(BaseException) as raised:
        with TestClient(app(cfg, policy), base_url='https://testserver'):
            pass
    error = raised.value
    while isinstance(error, BaseExceptionGroup):  # lifespan task-group wrapper
        error = error.exceptions[0]
    assert isinstance(error, ValueError) and 'request_consumers=3' in str(error)
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM service_requests').fetchone()['n'] == 0
