"""Real client outbox recovers a lost HTTP ACK without duplicate accepted input."""
from contextlib import contextmanager
from dataclasses import replace

import httpx
from starlette.testclient import TestClient

from agentic_rag import db
from .test_scope import service_store
from .test_api import app_fixture, KEYS
from .test_ingest import envelope


def client_config(tmp_path,cfg):
    token=tmp_path/'client.key';token.write_text(KEYS[0]);token.chmod(0o600)
    return replace(cfg,service_mode='client',service_url='https://testserver',service_token_file=token,service_spool_dir=tmp_path/'spool')


def test_commit_then_lost_ack_survives_restart_and_replays_once(service_store,tmp_path):
    from agentic_rag.service.client import RemoteClient
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    remote=client_config(tmp_path,cfg)
    class LostAck:
        lost=False
        @contextmanager
        def stream(self,method,url,**kwargs):
            with sender.stream(method,url,**kwargs) as response:
                if url.endswith('/v1/windows') and not self.lost:
                    self.lost=True
                    raise httpx.ReadTimeout('synthetic lost response')
                yield response
    with TestClient(app,base_url='https://testserver') as sender:
        with RemoteClient(remote,sender=LostAck()) as client:
            client.stage_window(envelope(session='lost-ack'))
            client.flush()
            assert len(client.spool.pending())==1
        with RemoteClient(remote,sender=sender) as client:
            client.spool.retry_blocked()
            client.flush()
            assert client.spool.pending()==[]
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM service_windows WHERE payload->>'session_id'='lost-ack'").fetchone()['n']==1


def test_cached_context_is_owned_and_explicitly_stale_offline(service_store,tmp_path):
    from agentic_rag.service.client import RemoteClient
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg);remote=client_config(tmp_path,cfg)
    # Cache ownership is the contract here; queued completion may exceed the
    # one-second hook default on a loaded host. Deadline behavior has clock tests.
    remote=replace(remote,service_hook_wait_seconds=5)
    with TestClient(app,base_url='https://testserver') as sender,RemoteClient(remote,sender=sender) as client:
        assert 'alpha' in client.context('s','/projects/a')
    def down(request):raise httpx.ConnectError('offline')
    with httpx.Client(transport=httpx.MockTransport(down)) as sender,RemoteClient(remote,sender=sender) as client:
        assert 'STALE' in client.context('s','/projects/a')
        assert 'alpha' not in client.context('other-session','/projects/a')
        assert 'alpha' not in client.context('s','/other-project')


def test_native_snapshot_release_requires_real_durable_server_ack(service_store,tmp_path):
    import json
    from agentic_rag.service.client import RemoteClient
    from agentic_rag.service.local import capture_transcript,stage_sources
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg);remote=client_config(tmp_path,cfg)
    source=tmp_path/'large.jsonl'
    raw=(json.dumps({'uuid':'one','message':{'role':'user','content':'A native fact survives a lost response.'}})+'\n').encode()
    raw+=(json.dumps({'type':'tool-result','padding':'x'*(17*1024*1024)})+'\n').encode()
    source.write_bytes(raw)
    capture_transcript(remote,{'session_id':'native-release','cwd':'/projects/a','transcript_path':str(source)})
    source.unlink()
    class LostAck:
        lost=False
        @contextmanager
        def stream(self,method,url,**kwargs):
            with sender.stream(method,url,**kwargs) as response:
                if url.endswith('/v1/windows') and not self.lost:
                    self.lost=True
                    response.read()
                    assert response.status_code==202 and response.json()['durable'] is True
                    raise httpx.ReadTimeout('lost after real server commit')
                yield response
    with TestClient(app,base_url='https://testserver') as sender:
        with RemoteClient(remote,sender=LostAck()) as client:
            assert stage_sources(client)==1
            client.flush(seconds=10)
            assert client.spool.status()['source_bytes']==len(raw)
            assert len(client.spool.pending())==1
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM service_windows WHERE payload->>'session_id'='native-release'").fetchone()['n']==1
        with RemoteClient(remote,sender=sender) as client:
            client.spool.retry_blocked();client.flush(seconds=10)
            assert client.spool.status()['source_bytes']==0 and client.spool.pending()==[]
            assert len(client.spool.extraction_states('native-release'))==1
        with db.connect(cfg) as conn:
            assert conn.execute("SELECT count(*) n FROM service_windows WHERE payload->>'session_id'='native-release'").fetchone()['n']==1
