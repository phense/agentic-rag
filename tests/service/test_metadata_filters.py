"""Actual authenticated typed-metadata boundaries; doubles only at external HTTP/model."""
import json
from dataclasses import replace
import httpx
import pytest
from starlette.testclient import TestClient
from agentic_rag import db,store
from agentic_rag.config import Config
from .test_api import app_fixture,headers,KEYS
from .test_scope import service_store,principal
from .test_client import client_config

FILTER={'version':1,'where':{'field':'dtype','op':'eq','value':'memory'}}

@pytest.mark.parametrize('path,body',[
    ('/v1/tools/memory_search','{"query":"Synthetic","filter":{"version":0,"version":1,"where":{"field":"dtype","op":"eq","value":"memory"}}}'),
    ('/v1/requests','{"idempotency_key":"00000000-0000-4000-8000-000000000001","created_at":"2026-11-04T00:00:00Z","tool":"memory_search","arguments":{"query":"Synthetic","filter":{"version":1,"where":{"field":"dtype","field":"slug","op":"eq","value":"memory"}}}}'),
    ('/mcp/ro/','{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"query":"Synthetic","filter":{"version":1,"version":1,"where":{"field":"dtype","op":"eq","value":"memory"}}}}}'),
])
def test_authenticated_raw_duplicate_filter_keys_are_rejected(service_store,tmp_path,path,body):
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post(path,content=body,headers={**headers(KEYS[0]),'content-type':'application/json','accept':'application/json, text/event-stream'})
        assert response.status_code==400 and response.json()=={'error':'invalid_filter'}


def test_old_server_refuses_typed_arguments_before_submit(tmp_path):
    from agentic_rag.service.client import RemoteClient,RemoteError
    cfg=client_config(tmp_path,Config())
    calls=[]
    def server(request):
        calls.append(request.method+' '+request.url.path)
        assert request.method=='GET'
        return httpx.Response(200,json={'protocol':1,'extensions':{'queued_tools':1}})
    with httpx.Client(transport=httpx.MockTransport(server)) as sender,RemoteClient(cfg,sender=sender) as client:
        with pytest.raises(RemoteError,match='unsupported_filter'):
            client.invoke('memory_search',{'query':'Synthetic','filter':FILTER})
        assert client.spool.pending_requests()==[]
    assert calls==['GET /v1/capabilities']


def test_authenticated_filter_and_schema_preserve_foreign_denial(service_store,tmp_path,monkeypatch):
    cfg,docs=service_store;cfg=replace(cfg,metadata_fields={'team':'string'})
    app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        capabilities=client.get('/v1/capabilities',headers=headers(KEYS[0])).json()
        assert capabilities['extensions']['typed_metadata']==1
        info=client.post('/v1/tools/memory_filter_schema',headers=headers(KEYS[0]),json={}).json()
        assert info['application_fields']=={'team':'string'}
        result=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={'query':'Synthetic','strategy':'lexical','rerank':'off','filter':FILTER})
        assert result.status_code==200,result.text
        assert {r['document_id'] for r in result.json()['results']}=={docs['allowed']}
        denied=client.post('/v1/tools/memory_search',headers=headers(KEYS[0]),json={'query':'Synthetic','filter':{'version':1,'where':{'field':'domain','op':'eq','value':'beta'}}})
        assert denied.status_code==400 and denied.json()=={'error':'invalid_filter'}
        assert client.post('/v1/tools/memory_save',headers=headers(KEYS[3]),json={'title':'x','body':'x','domain':'alpha','project':'/projects/a','metadata':{'team':'x'}}).status_code==403
