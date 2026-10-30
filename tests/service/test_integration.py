"""Reviewer-derived whole-success and accepted-output recovery scenarios.

Only owned databases and synthetic transcripts; HTTP, spool, migrations,
worker fences, canonical gateways and dump/restore remain real.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
import threading
import time
import uuid

import httpx
import pytest
from psycopg import sql
from starlette.testclient import TestClient

from agentic_rag import db, mining, query_cache, store, worker
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service import upgrade
from agentic_rag.service.client import RemoteClient
from agentic_rag.service.local import capture_transcript, pre_compact, post_compact, stage_sources
from agentic_rag.service.runner import run
from .test_api import app_fixture, headers, KEYS
from test_maintenance_restore import owned_source


@contextmanager
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr(query_cache, 'model_digest', lambda cfg: 'a'*64)
    monkeypatch.setattr(store, 'try_embed_texts', lambda texts, cfg: [[1.0]+[0.0]*1023 for _ in texts])
    monkeypatch.setattr(mining, 'try_embed_texts', lambda *a, **k: None)
    monkeypatch.setattr(worker, 'LOG_PATH', tmp_path/'worker.log')
    with owned_source(tmp_path, 19) as cfg:
        original = upgrade.inventory(cfg, '0.6.3')
        with db.connect(cfg) as conn:
            old_rows = {name: conn.execute(sql.SQL('SELECT row_to_json(t)::text row FROM public.{} t').format(sql.Identifier(name))).fetchall()
                        for name in ('documents', 'pins', 'audit_log', 'knowledge_sources', 'claim_evidence', 'fact_assertions', 'assertion_sources')}
        result = upgrade.local_upgrade(cfg, '0.6.3', tmp_path/'before.dump', apply=True, writers_stopped=True)
        assert result['restore_verified'] and result['original_rows_unchanged']
        assert upgrade.verify_preserved(cfg, result['manifest'])['unchanged']
        app, policy = app_fixture(tmp_path, cfg)
        policy.write_text(policy.read_text().replace('alpha', 'programming').replace('/projects/a', '/synthetic/backup'))
        cfg = replace(cfg, service_mode='server', service_auth_file=policy)
        yield cfg, app, result, original, old_rows


def remote_config(cfg, tmp_path, token):
    key = tmp_path/'client.key'
    key.write_text(token); key.chmod(0o600)
    return replace(cfg, service_mode='client', service_url='https://testserver',
                   service_token_file=key, service_spool_dir=tmp_path/'spool')


def capture(cfg, tmp_path):
    source = tmp_path/'transcript.jsonl'
    source.write_text(json.dumps({'uuid': 'event-1', 'message': {'role': 'user', 'content': 'server port is now 9000'}})+'\n')
    payload = dict(session_id='whole-flow', cwd='/synthetic/backup', transcript_path=str(source), trigger='manual', turn_id='turn-1')
    capture_transcript(cfg, payload)
    pre_compact(cfg, payload)
    post_compact(cfg, {**payload, 'compact_summary': '<summary>Continue the synthetic port verification.</summary>'})


def extraction(prompt):
    events = json.loads(prompt.split('SOURCE EVENTS (consumed fragments only):\n', 1)[1])
    assert len(events) == 1 and events[0]['text'] == '[user] server port is now 9000'
    return {'memories': [dict(title='Whole-flow port declaration', body='server port is now 9000', domain='programming',
                             edges=[], claim_kind='stated', evidence=[dict(source_id=events[0]['source_id'], quote='server port is now 9000')])]}


def counts(cfg):
    with db.connect(cfg) as conn:
        return {name: conn.execute(sql.SQL('SELECT count(*) n FROM public.{}').format(sql.Identifier(name))).fetchone()['n']
                for name in ('service_windows', 'service_streams', 'mining_queue', 'mining_batches', 'knowledge_sources')}


def receipt(cfg):
    with db.connect(cfg) as conn:
        return str(conn.execute('SELECT id FROM service_windows').fetchone()['id'])


def drive(cfg, receipt_id, terminal):
    """Run the real singleton/fenced loop, stopping after the observed receipt."""
    stop = threading.Event(); result = []
    thread = threading.Thread(target=lambda: result.append(run(cfg, stop=stop, interval=.01)))
    thread.start()
    try:
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            with db.connect(cfg) as conn:
                state = conn.execute('SELECT state FROM service_windows WHERE id=%s', (receipt_id,)).fetchone()['state']
                status = conn.execute('SELECT q.status FROM mining_queue q JOIN service_windows w ON q.id=w.queue_id WHERE w.id=%s', (receipt_id,)).fetchone()['status']
            if state == terminal and status != 'processing':
                return
            assert thread.is_alive(), result
            time.sleep(.02)
        pytest.fail('real service runner did not reach '+terminal)
    finally:
        stop.set(); thread.join(5)
        assert not thread.is_alive()
        assert result == [0]


def test_it058_s01_populated_upgrade_capture_upload_fenced_apply_and_scoped_read(tmp_path, monkeypatch):
    with installed(tmp_path, monkeypatch) as (cfg, app, upgrade_result, original, old_rows):
        remote = remote_config(cfg, tmp_path, KEYS[0]); capture(remote, tmp_path)
        calls = []
        monkeypatch.setattr(mining, 'run_structured', lambda prompt, *a, **k: calls.append(1) or extraction(prompt))
        observed = []
        with TestClient(app, base_url='https://testserver') as sender:
            class ObserveAck:
                @contextmanager
                def stream(self, method, url, **kwargs):
                    with sender.stream(method, url, **kwargs) as response:
                        if url.endswith('/v1/windows') and response.status_code == 202:
                            # Separate connection before yielding the ACK to the
                            # connector: all receipt/head/job writes are durable.
                            with db.connect(cfg) as conn:
                                row = conn.execute('SELECT w.output_cursor,s.last_cursor,q.status FROM service_windows w JOIN service_streams s USING(session_id) JOIN mining_queue q ON q.id=w.queue_id').fetchone()
                                assert row['output_cursor'] == row['last_cursor'] and row['status'] == 'pending'
                                observed.append(True)
                        yield response
            with RemoteClient(remote, sender=ObserveAck()) as client:
                assert stage_sources(client) == 1
                staged = json.loads([r for r in client.spool.pending() if r['kind'] == 'window'][0]['payload'])
                assert client.flush(seconds=10)['pending'] == 0
                assert client.spool.pending() == []
            assert observed == [True]
            receipt_id = receipt(cfg); before = counts(cfg)
            replay = sender.post('/v1/windows', headers=headers(KEYS[0]), json=staged)
            assert replay.status_code == 202 and replay.json()['receipt'] == receipt_id
            assert counts(cfg) == before
            drive(cfg, receipt_id, 'applied')
            assert calls == [1]
            result = sender.post('/v1/tools/memory_get', headers=headers(KEYS[0]), json={'id_or_slug': 'whole-flow-port-declaration'})
            assert result.status_code == 200, result.text
            document = result.json()['document']; assert document['body'] == 'server port is now 9000'
            rpc = sender.post('/mcp/ro/', headers={**headers(KEYS[0]), 'accept': 'application/json, text/event-stream'}, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'memory_get', 'arguments': {'id_or_slug': document['id']}}})
            assert json.loads(rpc.json()['result']['content'][0]['text'])['document']['id'] == document['id']
            assert sender.get('/v1/jobs/'+receipt_id, headers=headers(KEYS[2])).status_code == 404
            assert sender.get('/v1/checkpoints/whole-flow', headers=headers(KEYS[2])).status_code == 404
            assert sender.post('/v1/tools/memory_get', headers=headers(KEYS[2]), json={'id_or_slug': document['id']}).json().get('document') is None
            assert sender.post('/v1/tools/memory_save', headers=headers(KEYS[3]), json={'title': 'Denied', 'body': 'No write', 'domain': 'programming', 'project': '/synthetic/backup'}).status_code == 403
            assert 'Continue the synthetic port verification' in sender.get('/v1/checkpoints/whole-flow', headers=headers(KEYS[0])).json()['rendered']
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM mining_batches WHERE applied_at IS NOT NULL').fetchone()['n'] == 1
            assert conn.execute('SELECT actor FROM audit_log WHERE document_id=%s AND op=\'save_document\'', (document['id'],)).fetchone()['actor'] == 'service:machine:alice:vm1'
            from agentic_rag.service.auth import Policy
            expected_namespace = Policy.load(cfg.service_auth_file).authenticate_key(KEYS[0]).session_id('whole-flow')
            assert len(document['claim_sources']) == 1
            assert document['claim_sources'][0]['namespace'] == expected_namespace
            assert document['claim_sources'][0]['quote'] == 'server port is now 9000'
            for name, rows in old_rows.items():
                actual = conn.execute(sql.SQL('SELECT row_to_json(t)::text row FROM public.{} t').format(sql.Identifier(name))).fetchall()
                assert {r['row'] for r in rows} <= {r['row'] for r in actual}
        after = upgrade.inventory(cfg, '0.6.10')
        assert all(g in after['grants'] for g in original['grants'])
        assert all(after['sequences'][name]['last_value'] >= value['last_value'] for name, value in original['sequences'].items())


def test_it058_r01_lost_ack_accepted_output_revocation_explicit_retry_and_current_backup(tmp_path, monkeypatch):
    with installed(tmp_path, monkeypatch) as (cfg, app, upgraded, _, _):
        calls = []; accepted = threading.Event(); resume = threading.Event()
        monkeypatch.setattr(mining, 'run_structured', lambda prompt, *a, **k: calls.append(1) or extraction(prompt))
        real_mine = mining.mine_session
        def pause_before_apply(*args, **kwargs):
            real_check = kwargs['before_apply']
            def check():
                accepted.set()
                assert resume.wait(10)
                real_check()
            return real_mine(*args, **{**kwargs, 'before_apply': check})
        monkeypatch.setattr(mining, 'mine_session', pause_before_apply)
        with TestClient(app, base_url='https://testserver') as sender:
            uploader=str(uuid.uuid4())
            def login():
                result = sender.post('/v1/login', headers={'x-rag-protocol': '1'}, json={'username': 'alice', 'password': 'correct horse synthetic password','uploader_id':uploader})
                assert result.status_code == 200
                return result.json()['access_token']
            old = login(); remote = remote_config(cfg, tmp_path, old); capture(remote, tmp_path)
            class LostAck:
                lost = False
                @contextmanager
                def stream(self, method, url, **kwargs):
                    with sender.stream(method, url, **kwargs) as response:
                        if url.endswith('/v1/windows') and not self.lost:
                            self.lost = True
                            assert response.status_code == 202
                            raise httpx.ReadTimeout('synthetic lost ACK after commit')
                        yield response
            with RemoteClient(remote, sender=LostAck()) as client:
                assert stage_sources(client) == 1
                client.flush(seconds=10)
                assert len(client.spool.pending()) == 1
            assert counts(cfg)['service_windows'] == 1
            with RemoteClient(remote, sender=sender) as client:
                client.spool.retry_blocked(); assert client.flush(seconds=10)['pending'] == 0
            receipt_id = receipt(cfg)
            result = []; thread = threading.Thread(target=lambda: result.append(drive(cfg, receipt_id, 'blocked')))
            thread.start()
            try:
                assert accepted.wait(10)
                with db.connect(cfg) as conn:
                    batch = conn.execute('SELECT * FROM mining_batches').fetchone()
                    assert batch['applied_at'] is None and batch['extraction']['memories'][0]['title'] == 'Whole-flow port declaration'
                    original_authority = conn.execute('SELECT payload FROM service_windows').fetchone()['payload']['_principal']
                assert sender.post('/v1/logout', headers=headers(old)).status_code == 200
            finally:
                resume.set(); thread.join(15)
                assert not thread.is_alive()
            assert result == [None]
            assert counts(cfg)['mining_batches'] == 1 and counts(cfg)['service_windows'] == 1
            assert calls == [1]
            with db.connect(cfg) as conn:
                assert conn.execute("SELECT count(*) n FROM documents WHERE title='Whole-flow port declaration'").fetchone()['n'] == 0
            # Old authority cannot perform another inference or apply output.
            drive(cfg, receipt_id, 'blocked'); assert calls == [1]
            new = login()
            retry = sender.post('/v1/jobs/'+receipt_id+'/retry', headers=headers(new), json={})
            assert retry.status_code == 200, retry.text
            monkeypatch.setattr(mining, 'mine_session', real_mine)
            drive(cfg, receipt_id, 'applied'); assert calls == [1]
            with db.connect(cfg) as conn:
                payload = conn.execute('SELECT payload FROM service_windows').fetchone()['payload']
                assert payload['_original_principal'] == original_authority
                assert payload['_principal']['session'] != original_authority['session']
                assert conn.execute("SELECT count(*) n FROM documents WHERE title='Whole-flow port declaration'").fetchone()['n'] == 1
            with pytest.raises(ValueError, match='target_drift'):
                upgrade.restore_target(cfg, tmp_path/'before.dump', upgraded['manifest'], apply=True, resume=True)
            proof = upgrade.verified_backup(cfg, '0.6.10', tmp_path/'current.dump')
            assert proof['restore_verified']
            with isolated_database(cfg, initialize=False) as restored:
                assert upgrade.restore_target(restored, tmp_path/'current.dump', proof['manifest'], apply=True)['restore_verified']
                actual = upgrade.inventory(restored, '0.6.10')
                for name in ('service_windows', 'service_streams', 'mining_batches', 'continuation_checkpoints', 'documents', 'claim_evidence', 'knowledge_sources', 'pins', 'audit_log'):
                    assert actual['tables'][name] == proof['manifest']['tables'][name]
                assert actual['grants'] == proof['manifest']['grants']
                assert actual['sequences'] == proof['manifest']['sequences']
