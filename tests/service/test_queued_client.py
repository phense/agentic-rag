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


def _cfg(tmp_path):
    token=tmp_path/'token';token.write_text('synthetic.client-key');token.chmod(0o600)
    return replace(Config(),service_mode='client',service_url='https://rag.test',service_token_file=token,service_spool_dir=tmp_path/'spool')


def test_background_flush_drops_acknowledged_handle_whose_server_result_expired(tmp_path):
    """Regression: the uploader flushed with consume=False and kept every 404 handle forever.

    Expired handles filled the 64-slot request spool and blocked every later tool call
    with 'request spool full' until manual cleanup."""
    from agentic_rag.service.spool import Spool
    cfg=_cfg(tmp_path)
    server_id='22222222-2222-4222-8222-222222222222'
    def gone(request):
        if request.url.path=='/v1/capabilities':return httpx.Response(200,json={'protocol':1,'extensions':{'queued_tools':1}})
        return httpx.Response(404,json={'error':{'code':'not_found'}})
    with httpx.Client(transport=httpx.MockTransport(gone)) as sender,RemoteClient(cfg,sender=sender) as client:
        handle=client.spool.stage_request('memory_context',{'session_id':'s'})
        client.spool.request_ack(handle,server_id)
        summary=client.flush_requests()
        assert summary['pending']==0
        assert client.spool.pending_requests()==[]


def test_full_request_spool_reclaims_expired_handles_before_refusing(tmp_path):
    """Slots held by handles the server already reported as gone are reclaimed on demand."""
    import pytest
    from agentic_rag.service.spool import Spool,SpoolFull
    with Spool(tmp_path/'private'/'spool.sqlite','one') as spool:
        for i in range(64):
            handle=spool.stage_request('memory_context',{'session_id':str(i)})
            if i<10:
                spool.request_ack(handle,f'00000000-0000-4000-8000-{i:012d}')
                spool.request_error(handle,'not_found')
        fresh=spool.stage_request('memory_context',{'session_id':'after-reclaim'})
        assert fresh.startswith('local.')
        assert len(spool.pending_requests())==55
        # Unacknowledged or still-live handles are never reclaimed.
        for i in range(9):spool.stage_request('memory_context',{'session_id':f'more-{i}'})
        with pytest.raises(SpoolFull):spool.stage_request('memory_context',{'session_id':'overflow'})
        assert len(spool.pending_requests())==64
