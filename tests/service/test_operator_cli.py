"""Operator interfaces are explicit, private and usable through the installed CLI."""
from dataclasses import replace
import json
import os

import pytest
from agentic_rag import cli,db
from agentic_rag.config import Config,load_config
from agentic_rag.service.auth import protected_file,Policy
from .test_worker_fencing import owned


def test_generate_key_and_client_config_never_print_raw_secret(tmp_path,capsys):
    key=tmp_path/'vm.key'
    assert cli.main(['service','key','--id','vm1','--output',str(key)])==0
    output=capsys.readouterr().out;token=protected_file(key).decode().strip()
    assert token.startswith('vm1.') and token not in output
    assert json.loads(output)['verifier'].startswith('sha256$')
    config=tmp_path/'client.toml'
    assert cli.main(['service','client-config','--url','https://rag.example.test','--token-file',str(key),'--output',str(config),'--spool-dir',str(tmp_path/'spool')])==0
    assert token not in config.read_text()
    parsed=load_config(config)
    assert parsed.service_mode=='client' and parsed.service_token_file==key
    assert cli.main(['service','key','--id','vm1','--output',str(key)])==1


def test_static_policy_validation_and_status_do_not_expose_credentials(owned,tmp_path,monkeypatch,capsys):
    cfg,_=owned;monkeypatch.setattr(cli,'load_config',lambda:cfg)
    assert cli.main(['service','check-policy','--file',str(cfg.service_auth_file)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['users']==1 and result['machines']==1
    assert 'sha256$' not in json.dumps(result)
    assert cli.main(['service','status'])==0
    status=json.loads(capsys.readouterr().out)
    assert status['mode']=='standalone' and status['database']['pending']>=0
    assert cli.main(['service','inventory','--source-version','0.6.3','--output',str(tmp_path/'inventory.json')])==0
    inventory=json.loads(protected_file(tmp_path/'inventory.json'))
    assert inventory['supported'] and inventory['tables']['documents']['rows']==0


def test_server_entrypoints_require_explicit_mode(monkeypatch):
    monkeypatch.setattr(cli,'load_config',lambda:Config())
    assert cli.main(['service','serve','--auth-file','/missing'])==1
    assert cli.main(['service','worker'])==1


def test_serve_uses_one_bounded_process_and_loopback_by_default(owned,monkeypatch):
    import uvicorn
    cfg,_=owned;cfg=replace(cfg,service_mode='server');monkeypatch.setattr(cli,'load_config',lambda:cfg)
    seen={}
    monkeypatch.setattr(uvicorn,'run',lambda app,**kw:seen.update(kw))
    assert cli.main(['service','serve','--auth-file',str(cfg.service_auth_file)])==0
    assert seen['host']=='127.0.0.1' and seen['workers']==1
    assert seen['limit_concurrency']==64 and seen['timeout_keep_alive']==30
    assert seen['access_log'] is False


def test_spool_flush_drains_durable_input_when_staging_is_full(owned,tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    from starlette.testclient import TestClient
    from agentic_rag.service import operator
    from agentic_rag.service.client import RemoteClient
    from agentic_rag.service.spool import Spool
    from .test_api import app_fixture
    from .test_client import client_config
    from .test_checkpoint_api import packet
    cfg,_=owned;app,_=app_fixture(tmp_path,cfg);remote=client_config(tmp_path,cfg)
    original_spool=Spool.__init__
    def one_item(self,path,partition,**kwargs):
        return original_spool(self,path,partition,max_items=1)
    monkeypatch.setattr(Spool,'__init__',one_item)
    raw=(json.dumps({'uuid':'tail','message':{'role':'user','content':'A durable synthetic tail'}})+'\n').encode()
    with RemoteClient(remote) as client:
        client.spool.capture_source('pending-tail','/projects/a',raw)
        client.stage_checkpoint(packet())
    with TestClient(app,base_url='https://testserver') as sender:
        original_client=RemoteClient.__init__
        monkeypatch.setattr(RemoteClient,'__init__',lambda self,cfg:original_client(self,cfg,sender=sender))
        args=SimpleNamespace(service_command='spool',retry_blocked=False,flush=True)
        assert operator.run(args,remote)==0
        assert json.loads(capsys.readouterr().out)['pending']==0
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM continuation_checkpoints').fetchone()['n']==1
            assert conn.execute('SELECT count(*) n FROM service_windows').fetchone()['n']==0
        # Staging can proceed on the next invocation after ACK frees capacity.
        assert operator.run(args,remote)==0
        assert json.loads(capsys.readouterr().out)['pending']==0
        with RemoteClient(remote) as client:
            assert client.spool.sources()[0]['raw']==raw
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM service_windows').fetchone()['n']==1


def test_login_persists_distinct_vm_uploader_identity_across_token_renewal(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from agentic_rag.service import operator
    sent=[]
    @contextmanager
    def stream(method,url,**kwargs):
        payload=dict(kwargs['json']);sent.append(payload)
        class Response:
            status_code=200
            def iter_bytes(self):
                yield json.dumps({'access_token':'session.synthetic-'+str(len(sent)),
                                  'uploader_id':payload['uploader_id']}).encode()
        yield Response()
    monkeypatch.setattr(operator.httpx,'stream',stream)
    password=tmp_path/'password';password.write_text('synthetic human login password');password.chmod(0o600)
    def login(token,uploader):
        return operator._login(SimpleNamespace(url='https://rag.example.test',username='alice',password_file=password,
                                               output=tmp_path/token,uploader_file=tmp_path/uploader))
    login('first.key','vm-a.uploader');login('renewed.key','vm-a.uploader');login('other.key','vm-b.uploader')
    assert sent[0]['uploader_id']==sent[1]['uploader_id']!=sent[2]['uploader_id']
    assert (tmp_path/'vm-a.uploader').stat().st_mode&0o777==0o600
    assert 'password' not in (tmp_path/'vm-a.uploader').read_text()
    # A server may not silently substitute a different uploader at login.
    @contextmanager
    def altered(*args,**kwargs):
        class Response:
            status_code=200
            def iter_bytes(self):yield b'{"access_token":"session.synthetic","uploader_id":"wrong"}'
        yield Response()
    monkeypatch.setattr(operator.httpx,'stream',altered)
    with pytest.raises(ValueError,match='invalid_login_uploader'):login('invalid.key','vm-a.uploader')
    assert not (tmp_path/'invalid.key').exists()
