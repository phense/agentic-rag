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
    with TestClient(app,base_url='https://testserver') as sender,RemoteClient(remote,sender=sender) as client:
        assert 'alpha' in client.context('s','/projects/a')
    def down(request):raise httpx.ConnectError('offline')
    with httpx.Client(transport=httpx.MockTransport(down)) as sender,RemoteClient(remote,sender=sender) as client:
        assert 'STALE' in client.context('s','/projects/a')
        assert 'alpha' not in client.context('other-session','/projects/a')
        assert 'alpha' not in client.context('s','/other-project')
