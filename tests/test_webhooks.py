"""Consumer contracts: minimal atomic capture and hostile destinations."""
import json
import uuid

import pytest


def test_capture_defaults_off_and_rolls_back(conn):
    # An accidental migration/startup opt-in must fail this test.
    present=conn.execute("SELECT to_regclass('public.webhook_control') IS NOT NULL ok").fetchone()['ok']
    assert present, 'additive webhook capture/control contract missing'
    assert conn.execute('SELECT enabled FROM webhook_control').fetchone()['enabled'] is False
    from agentic_rag import webhooks
    subscription=webhooks.subscribe(conn,None,endpoint='https://example.com/hook',domain='general',project='global',
                                    kinds=['memory.created'],idempotency_key=str(uuid.uuid4()))
    conn.execute("INSERT INTO domains(name) VALUES ('general') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO documents(slug,domain,dtype,title,body,project_scope) VALUES ('off','general','memory','PRIVATE TITLE','PRIVATE BODY','global')")
    assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0
    conn.execute('UPDATE webhook_control SET enabled=true')
    conn.execute("INSERT INTO documents(slug,domain,dtype,title,body,project_scope) VALUES ('on','general','memory','PRIVATE TITLE','PRIVATE BODY','global')")
    event=conn.execute('SELECT payload FROM webhook_events').fetchone()['payload']
    assert event['kind']=='memory.created' and event['resource_version']==0  # private until deferred commit admission
    assert 'PRIVATE' not in json.dumps(event)
    assert conn.execute('SELECT count(*) n FROM webhook_deliveries').fetchone()['n']==1
    conn.rollback()
    assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0


def test_subscription_idempotency_revision_and_foreign_scope(conn):
    from agentic_rag import webhooks
    key=str(uuid.uuid4())
    args=dict(endpoint='https://example.com/hook',domain='general',project='global',kinds=['memory.created'],idempotency_key=key)
    one=webhooks.subscribe(conn,None,**args)
    assert webhooks.subscribe(conn,None,**args)==one
    with pytest.raises(webhooks.WebhookError,match='webhook_conflict'):
        webhooks.subscribe(conn,None,**{**args,'endpoint':'https://example.com/other'})
    with pytest.raises(webhooks.WebhookError,match='webhook_conflict'):
        webhooks.disable(conn,None,subscription_id=one['id'],expected_revision=2)
    assert webhooks.disable(conn,None,subscription_id=one['id'],expected_revision=1)['revision']==2
    assert webhooks.status(conn,None,subscription_id=one['id'])['subscription']['enabled'] is False
    with pytest.raises(webhooks.WebhookError,match='webhook_unavailable'):
        webhooks.status(conn,None,subscription_id=str(uuid.uuid4()))


@pytest.mark.parametrize('endpoint',['http://example.com/','https://user:pass@example.com/',
    'https://example.com/?secret=abc','https://example.com/#fragment','https://example.com/\r\nX: y'])
def test_invalid_destinations(endpoint):
    from agentic_rag.webhook_delivery import normalize_endpoint
    with pytest.raises(ValueError):normalize_endpoint(endpoint)


@pytest.mark.parametrize('address',['127.0.0.1','169.254.169.254','::ffff:169.254.169.254','224.0.0.1','0.0.0.0','fe80::1','::'])
def test_forbidden_addresses(address):
    from agentic_rag.webhook_delivery import validate_addresses
    with pytest.raises(ValueError):validate_addresses('https://example.com', [address], {})


def test_operator_contexts_and_private_files(tmp_path):
    from agentic_rag import webhook_delivery as delivery
    from agentic_rag.config import Config
    from agentic_rag.service.queued_transaction import GROUP,EXECUTION
    from agentic_rag.service.fence import LEASE
    from agentic_rag.service.context import CURRENT
    cfg=Config()
    for context in (CURRENT,GROUP,EXECUTION,LEASE):
        token=context.set(object())
        try:
            with pytest.raises(ValueError,match='operator_local'):delivery.key_init(cfg,tmp_path/'forbidden')
        finally:context.reset(token)
    delivery.key_init(cfg,tmp_path/'root')
    with pytest.raises(FileExistsError):delivery.key_init(cfg,tmp_path/'root')
    (tmp_path/'root').chmod(0o644)
    with pytest.raises(ValueError):delivery.signing_key(tmp_path/'root',str(uuid.uuid4()),1)
    (tmp_path/'root').chmod(0o600)
    (tmp_path/'link').symlink_to(tmp_path/'root')
    with pytest.raises(OSError):delivery.signing_key(tmp_path/'link',str(uuid.uuid4()),1)
    git=tmp_path/'checkout';git.mkdir();(git/'.git').mkdir()
    with pytest.raises(ValueError,match='outside_git'):delivery.key_init(cfg,git/'root')


@pytest.mark.parametrize('raw',[b'HTTP/1.1 204 OK\r\n',b'HTTP/1.1 204 OK\r\nBad header\r\n\r\n',b'HTTP/1.1 204 OK\r\nX: '+b'a'*9000+b'\r\n\r\n'])
def test_partial_or_malformed_response_never_acknowledged(monkeypatch,raw):
    from agentic_rag import webhook_delivery as delivery
    class FakeSocket:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def settimeout(self,*a):pass
        def connect(self,address):assert address==('127.0.0.1',99)
        def sendall(self,*a):pass
        def recv(self,size):
            nonlocal raw
            piece,raw=raw[:size],raw[size:]
            return piece
    monkeypatch.setattr(delivery,'resolve',lambda *a:['127.0.0.1'])
    monkeypatch.setattr(delivery.socket,'socket',lambda *a:FakeSocket())
    with pytest.raises(ValueError):
        delivery.transmit('http://localhost:99/',b'{}',{},test_http=True,policy={'http://localhost:99':['127.0.0.1/32']})


def test_tls_uses_pinned_numeric_address_original_sni_host_and_no_redirect(monkeypatch):
    from agentic_rag import webhook_delivery as delivery
    connections=[];names=[];requests=[]
    class FakeSocket:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def close(self):pass
        def settimeout(self,*a):pass
        def connect(self,address):connections.append(address)
        def sendall(self,request):requests.append(request)
        def recv(self,*a):return b'HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/latest\r\n\r\n'
    class Context:
        def wrap_socket(self,raw,*,server_hostname):names.append(server_hostname);return raw
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:1')
    monkeypatch.setattr(delivery,'resolve',lambda *a:['93.184.216.34'])
    monkeypatch.setattr(delivery.socket,'socket',lambda *a:FakeSocket())
    monkeypatch.setattr(delivery.ssl,'create_default_context',lambda:Context())
    assert delivery.transmit('https://example.com:8443/hook',b'{}',{})==302
    assert connections==[('93.184.216.34',8443)] and names==['example.com']
    assert b'Host: example.com:8443\r\n' in requests[0] and len(requests)==1
