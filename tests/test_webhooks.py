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
    assert event['kind']=='memory.created' and event['resource_version']>=1
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
