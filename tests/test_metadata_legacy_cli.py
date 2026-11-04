"""Optional typed arguments must not change unrelated CLI wire contracts."""
from dataclasses import replace
import json

import httpx
import pytest

from agentic_rag import cli
from agentic_rag.config import Config
from agentic_rag.service import client as remote


@pytest.mark.parametrize('argv,tool,arguments', [
    (['feedback','get','--feedback-id','synthetic-feedback'],
     'memory_feedback_get',{'feedback_id':'synthetic-feedback','event_id':None}),
    (['webhooks','status','synthetic-subscription'],
     'webhook_status',{'subscription_id':'synthetic-subscription'}),
])
def test_unfiltered_legacy_cli_keeps_original_http_arguments(
        tmp_path, monkeypatch, capsys, argv, tool, arguments):
    # Mutation: forward parser-wide filter/metadata=None to unrelated tools.
    # Exercise the actual parser, adapter and durable client; only HTTP is stubbed.
    token=tmp_path/'client.key';token.write_text('synthetic-cli-key');token.chmod(0o600)
    cfg=replace(Config(),service_mode='client',service_url='https://legacy.example',
                service_token_file=token,service_spool_dir=tmp_path/'spool')
    monkeypatch.setattr(cli,'load_config',lambda:cfg)
    observed=[]
    def server(request):
        observed.append((request.method,request.url.path))
        if request.method=='GET':
            assert request.url.path=='/v1/capabilities'
            return httpx.Response(200,json={'protocol':1,'extensions':{}})
        assert request.method=='POST' and request.url.path=='/v1/tools/'+tool
        if json.loads(request.content)!=arguments:
            return httpx.Response(400,json={'error':'invalid_arguments'})
        return httpx.Response(200,json={'state':'legacy-result'})
    original=remote.RemoteClient
    with httpx.Client(transport=httpx.MockTransport(server)) as sender:
        class BoundClient(original):
            def __init__(self,config):super().__init__(config,sender=sender)
        monkeypatch.setattr(remote,'RemoteClient',BoundClient)
        assert cli.main(argv)==0
    assert json.loads(capsys.readouterr().out)=={'state':'legacy-result'}
    assert observed==[('GET','/v1/capabilities'),('POST','/v1/tools/'+tool)]
