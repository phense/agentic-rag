"""A wait timeout preserves the identical envelope across process restart/lost ACK."""
from dataclasses import replace
import httpx
from agentic_rag.config import Config
from agentic_rag.service.client import RemoteClient


def test_lost_ack_keeps_local_handle_and_replays_same_envelope(tmp_path):
    token=tmp_path/'token';token.write_text('synthetic.client-key');token.chmod(0o600)
    cfg=replace(Config(),service_mode='client',service_url='https://rag.test',service_token_file=token,service_spool_dir=tmp_path/'spool')
    envelopes=[]
    def first(request):
        import json
        if request.url.path=='/v1/capabilities':return httpx.Response(200,json={'protocol':1,'extensions':{'queued_tools':1}})
        envelopes.append(json.loads(request.content))
        raise httpx.ReadTimeout('lost ack')
    with httpx.Client(transport=httpx.MockTransport(first)) as sender,RemoteClient(cfg,sender=sender) as client:
        result=client.invoke('memory_domains',{},seconds=.01)
        assert result['waiting'] and not result['durable'] and result['request_id'].startswith('local.')
        handle=result['request_id']
    def second(request):
        import json
        if request.url.path=='/v1/capabilities':return httpx.Response(200,json={'protocol':1,'extensions':{'queued_tools':1}})
        if request.method=='POST':
            envelopes.append(json.loads(request.content))
            return httpx.Response(202,json={'request_id':'11111111-1111-4111-8111-111111111111','state':'pending','durable':True})
        return httpx.Response(200,json={'request_id':'11111111-1111-4111-8111-111111111111','state':'completed','durable':True,'result':{'domains':[]}})
    with httpx.Client(transport=httpx.MockTransport(second)) as sender,RemoteClient(cfg,sender=sender) as client:
        result=client.request_status(handle)
        assert result['state']=='completed' and result['result']=={'domains':[]}
    assert len(envelopes)==2 and envelopes[0]==envelopes[1]


def test_request_outbox_is_globally_bounded_and_keeps_pending(tmp_path):
    import pytest
    from agentic_rag.service.spool import Spool,SpoolFull
    with Spool(tmp_path/'private'/'spool.sqlite','one') as spool:
        for i in range(64):spool.stage_request('memory_context',{'session_id':str(i)})
        with pytest.raises(SpoolFull):spool.stage_request('memory_context',{'session_id':'overflow'})
        assert len(spool.pending_requests())==64
    with Spool(tmp_path/'private'/'spool.sqlite','two') as spool:
        with pytest.raises(SpoolFull):spool.stage_request('memory_domains',{})
