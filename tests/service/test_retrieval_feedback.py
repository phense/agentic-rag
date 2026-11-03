"""Authenticated feedback contracts on owned PostgreSQL; no provider calls."""
from dataclasses import replace
import uuid

from starlette.testclient import TestClient

from .test_scope import service_store
from .test_api import app_fixture, headers, KEYS


def test_explicit_writer_search_captures_event_without_retaining_query(service_store, tmp_path):
    # Mutation caught: tool absent, ordinary search substituted or raw query retained.
    cfg, docs = service_store
    cfg = replace(cfg, feedback_enabled=True) if hasattr(cfg, 'feedback_enabled') else cfg
    app, _ = app_fixture(tmp_path, cfg)
    query = 'Synthetic protected evidence'
    with TestClient(app, base_url='https://testserver') as client:
        response = client.post('/v1/tools/memory_feedback_search', headers=headers(KEYS[0]), json={
            'query': query, 'domain': 'alpha', 'project': '/projects/a',
            'idempotency_key': str(uuid.uuid4()), 'strategy': 'lexical'})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['event']['query_sha256'] == '026983b732608b0cc42659a06883a92bbbd48d354ac9007d7ba665b701ca819b'
        assert str(docs['allowed']) in {r['document_id'] for r in data['results']}
    from agentic_rag import db
    with db.connect(cfg) as conn:
        retained = conn.execute('SELECT row_to_json(e)::text data FROM retrieval_feedback_events e WHERE id=%s', (data['event']['id'],)).fetchone()['data']
        assert query not in retained and 'Synthetic protected' not in retained


def test_http_signal_workflow_readonly_foreign_and_revocation_rollback(service_store,tmp_path,monkeypatch):
    from agentic_rag import db,feedback
    cfg,docs=service_store
    cfg=replace(cfg,feedback_enabled=True)
    app,policy=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        def post(name,arguments,token=KEYS[0]):
            return client.post('/v1/tools/memory_feedback_'+name,headers=headers(token),json=arguments)
        payload={'query':'Synthetic protected evidence','domain':'alpha','project':'/projects/a','idempotency_key':str(uuid.uuid4())}
        assert client.post('/v1/tools/memory_feedback_search',json=payload).status_code==401
        assert post('search',payload,KEYS[3]).status_code==403
        captured=post('search',payload)
        assert captured.status_code==200,captured.text
        event=captured.json()['event']
        response=post('submit',{'event_id':event['id'],'kind':'useful','idempotency_key':str(uuid.uuid4()),'comment':'token=syntheticsecretvalue'})
        assert response.status_code==200,response.text
        signal=response.json()
        assert signal['comment']=='[REDACTED]' and signal['revision']==1
        errors=[]
        for identifier in (event['id'],str(uuid.uuid4())):
            response=post('submit',{'event_id':identifier,'kind':'useful','idempotency_key':str(uuid.uuid4())},KEYS[2])
            assert response.status_code==404,response.text
            errors.append(response.json())
        assert errors==[{'error':'feedback_unavailable'}]*2
        assert post('update',{'feedback_id':signal['id'],'expected_revision':1,'kind':'not_useful'}).json()['revision']==2
        assert post('retract',{'feedback_id':signal['id'],'expected_revision':1}).status_code==409
        assert post('retract',{'feedback_id':signal['id'],'expected_revision':2}).json()['state']=='retracted'
        assert post('get',{'feedback_id':signal['id']}).json()['revision']==3
        assert any(s['id']==signal['id'] for s in post('list',{}).json()['feedback'])
        original=feedback._audit
        def revoke(conn,owner,operation,identifier):
            original(conn,owner,operation,identifier)
            policy.write_text(policy.read_text().replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
        monkeypatch.setattr(feedback,'_audit',revoke)
        request_key=str(uuid.uuid4())
        response=post('submit',{'event_id':event['id'],'kind':'wrong_source','idempotency_key':request_key})
        assert response.status_code==403 and response.json()=={'error':'authorization_changed'}
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT id FROM retrieval_feedback WHERE idempotency_key=%s',(request_key,)).fetchall()==[]


def test_real_mcp_and_local_remote_cli(service_store,tmp_path,monkeypatch,capsys):
    import asyncio
    import json
    from agentic_rag import cli,mcp_server
    from agentic_rag.service.context import request_scope
    from .test_client import client_config
    from agentic_rag.service.client import RemoteClient
    cfg,_=service_store
    cfg=replace(cfg,feedback_enabled=True)
    app,policy=app_fixture(tmp_path,cfg)
    from .test_scope import principal
    with request_scope(principal(),cfg):
        server=mcp_server.build_server(readonly=False)
        result=asyncio.run(server.call_tool('memory_feedback_search',{'query':'Synthetic protected evidence','domain':'alpha',
                    'project':'/projects/a','idempotency_key':str(uuid.uuid4())}))
        # FastMCP returns text plus structuredContent for typed dictionary tools.
        content=result[0] if isinstance(result,tuple) else result
        captured=json.loads(content[0].text)
        assert captured['event']['id'] and captured['results']
        assert cli.main(['feedback','submit',captured['event']['id'],'--kind','missing_evidence','--idempotency-key',str(uuid.uuid4())])==0
        local=json.loads(capsys.readouterr().out)
        assert local['kind']=='missing_evidence'
    # True standalone OS-derived CLI ownership, with no synthetic RequestScope.
    config_file=tmp_path/'local.toml'
    config_file.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[feedback]\nenabled=true\n')
    monkeypatch.setenv('AGENTIC_RAG_CONFIG',str(config_file))
    assert cli.main(['feedback','search','Synthetic protected evidence','--domain','alpha','--project','/projects/a',
                     '--idempotency-key',str(uuid.uuid4())])==0
    local=json.loads(capsys.readouterr().out)
    assert local['event']['id']
    assert cli.main(['feedback','submit',local['event']['id'],'--kind','useful','--idempotency-key',str(uuid.uuid4())])==0
    signal=json.loads(capsys.readouterr().out)
    assert cli.main(['feedback','retract',signal['id'],'--expected-revision','1'])==0
    assert json.loads(capsys.readouterr().out)['state']=='retracted'
    remote=client_config(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as sender:
        # Supply a real authenticated HTTP transport at the socket boundary.
        monkeypatch.setattr('agentic_rag.config.load_config',lambda *a,**k:remote)
        monkeypatch.setattr(cli,'load_config',lambda *a,**k:remote)
        class Attached(RemoteClient):
            def __init__(self,config):super().__init__(config,sender=sender)
            def negotiate(self,**kwargs):
                result=super().negotiate(**kwargs)
                self.queued_tools=False  # Exercise existing synchronous REST tool path.
                return result
        monkeypatch.setattr('agentic_rag.service.client.RemoteClient',Attached)
        assert cli.main(['feedback','search','Synthetic protected evidence','--domain','alpha','--project','/projects/a',
                         '--idempotency-key',str(uuid.uuid4())])==0
        data=json.loads(capsys.readouterr().out)
        assert data['event']['id'] and data['results']


def test_queued_remote_feedback_preserves_atomic_results_and_origin(service_store,tmp_path):
    from agentic_rag import db
    from agentic_rag.service.client import RemoteClient
    from .test_client import client_config
    cfg,_=service_store
    cfg=replace(cfg,feedback_enabled=True)
    app,_=app_fixture(tmp_path,cfg)
    remote=client_config(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as sender,RemoteClient(remote,sender=sender) as client:
        data=client.invoke('memory_feedback_search',{'query':'Synthetic protected evidence','domain':'alpha',
                           'project':'/projects/a','idempotency_key':str(uuid.uuid4())},seconds=10)
        assert data.get('event'),data
        assert client.queued_tools is True
        signal=client.invoke('memory_feedback_submit',{'event_id':data['event']['id'],'kind':'wrong_source',
                             'idempotency_key':str(uuid.uuid4())},seconds=10)
        assert signal.get('revision')==1,signal
        retracted=client.invoke('memory_feedback_retract',{'feedback_id':signal['id'],'expected_revision':1},seconds=10)
        assert retracted.get('state')=='retracted',retracted
        assert client.spool.pending_requests()==[]
    with db.connect(cfg) as conn:
        event=conn.execute('SELECT * FROM retrieval_feedback_events WHERE id=%s',(data['event']['id'],)).fetchone()
        request=conn.execute("SELECT * FROM service_requests WHERE tool='memory_feedback_search' AND result->'event'->>'id'=%s",(data['event']['id'],)).fetchone()
        assert request['state']=='completed' and request['arguments'] is None
        assert event['origin_request_id'] is not None and event['origin_request_id']==request['origin_request_id']
