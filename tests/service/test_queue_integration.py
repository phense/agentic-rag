"""The shipped connector talks to real ASGI/SQL and waits without re-enqueue."""
from dataclasses import replace
import uuid
from starlette.testclient import TestClient
from agentic_rag.service.client import RemoteClient
from .test_scope import service_store
from .test_api import app_fixture,KEYS


def test_negotiated_connector_completes_read_write_and_reuses_real_http(tmp_path,service_store):
    cfg,_=service_store
    app,_=app_fixture(tmp_path,cfg)
    token=tmp_path/'token';token.write_text(KEYS[0]);token.chmod(0o600)
    client_cfg=replace(cfg,service_mode='client',service_url='https://testserver',service_token_file=token,service_spool_dir=tmp_path/'spool')
    with TestClient(app,base_url='https://testserver') as sender,RemoteClient(client_cfg,sender=sender) as client:
        domains=client.invoke('memory_domains',{},seconds=10)
        assert domains['domains'][0]['name']=='alpha',domains
        saved=client.invoke('memory_save',{'title':'Connector '+str(uuid.uuid4()),'body':'Synthetic durable request','domain':'alpha','project':'/projects/a'},seconds=10)
        assert saved['created']
        fetched=client.invoke('memory_get',{'id_or_slug':saved['doc_id']},seconds=10)
        assert fetched['document']['body']=='Synthetic durable request'
        assert client.spool.pending_requests()==[]
