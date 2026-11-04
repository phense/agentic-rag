"""Real PostgreSQL/RLS/queued transactions and an isolated HTTP receiver."""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import http.server
import json
import os
from pathlib import Path
import threading
import time
import uuid

import psycopg
from psycopg import sql
import pytest
from starlette.testclient import TestClient

from agentic_rag import db,store,webhooks
from agentic_rag import webhook_delivery as delivery
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service.context import request_scope
from agentic_rag.service.auth import Policy
from .test_api import app_fixture,KEYS,headers
from .test_scope import service_store
from .test_queue_atomicity import paused,queued


@pytest.fixture
def wh(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    with isolated_database(Config(webhook_key_file=tmp_path/'root')) as cfg:
        delivery.key_init(cfg,cfg.webhook_key_file)
        yield cfg


def subscribe(cfg,*,domain='general',project='/p',kinds=None,endpoint='https://example.com/hook'):
    with db.connect(cfg,role='writer') as conn:
        return webhooks.subscribe(conn,cfg,endpoint=endpoint,domain=domain,project=project,
            kinds=kinds or ['memory.created'],idempotency_key=str(uuid.uuid4()))


def save(cfg,**kwargs):
    with db.connect(cfg) as conn:
        return store.save_document(conn,cfg,title='PRIVATE TITLE '+str(uuid.uuid4()),body='PRIVATE BODY '+str(uuid.uuid4()),
            domain='general',dtype='memory',project='/p',**kwargs).doc_id


@contextmanager
def receiver(code=204):
    captured=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.rfile.read(int(self.headers['Content-Length'])),dict(self.headers)))
            self.send_response(code);self.end_headers()
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)+'/hook',captured
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


def local_policy(cfg,endpoint):
    return replace(cfg,webhook_test_http=True,webhook_private_origins={delivery.origin(endpoint):['127.0.0.1/32']})


def test_committed_exact_bytes_signature_crash_recovery_rotation(wh,tmp_path):
    # Catches implicit network, unstable event serialization, unfenced completion.
    with receiver() as (endpoint,received):
        cfg=local_policy(wh,endpoint)
        sub=subscribe(cfg,endpoint=endpoint,kinds=['memory.created','memory.changed'])
        delivery.key_export(cfg,subscription_id=sub['id'],output=tmp_path/'receiver-key')
        exported=json.loads((tmp_path/'receiver-key').read_text())
        assert (tmp_path/'receiver-key').stat().st_mode&0o777==0o600
        delivery.capture(cfg,True)
        document=save(cfg)
        assert received==[]
        first=delivery.claim(cfg)
        assert first['attempts']==1
        body=first['wire'].encode()
        header=delivery.signature_headers(cfg.webhook_key_file,first['id'],first['generation'],body)
        assert delivery.transmit(endpoint,body,header,policy=cfg.webhook_private_origins,test_http=True)==204
        # Receiver acknowledged, worker died before completion. Recover same ID/bytes.
        with db.connect(cfg) as conn:conn.execute("UPDATE webhook_deliveries SET lease_until=now()-interval '1 second'")
        recovered=delivery.claim(cfg)
        assert recovered['attempts']==2 and recovered['event_id']==first['event_id'] and recovered['wire']==first['wire']
        assert delivery.complete(cfg,first,'acknowledged') is False
        assert delivery.complete(cfg,first,'network') is False
        header2=delivery.signature_headers(cfg.webhook_key_file,recovered['id'],recovered['generation'],body)
        delivery.transmit(endpoint,body,header2,policy=cfg.webhook_private_origins,test_http=True)
        assert delivery.complete(cfg,recovered,'acknowledged')
        assert len(received)==2 and received[0][0]==received[1][0]
        for raw,headers_ in received:
            assert delivery.verify_signature(bytes.fromhex(exported['key_hex']),raw,headers_)
            assert not delivery.verify_signature(bytes.fromhex(exported['key_hex']),raw+b' ',headers_)
            assert not delivery.verify_signature(bytes.fromhex(exported['key_hex']),raw,headers_,now=int(headers_['X-RAG-Timestamp'])+301)
            assert headers_['X-RAG-Key-Id']==exported['key_id'] and b'PRIVATE' not in raw
        with db.connect(cfg,role='writer') as conn:
            rotated=webhooks.rotate(conn,cfg,subscription_id=sub['id'],expected_revision=1)
            assert rotated['generation']==2
            webhooks.replay(conn,cfg,subscription_id=sub['id'],expected_revision=2,delivery_id=str(first['delivery_id']))
        delivery.key_export(cfg,subscription_id=sub['id'],output=tmp_path/'receiver-key-2')
        exported2=json.loads((tmp_path/'receiver-key-2').read_text())
        assert exported2['key_id']!=exported['key_id'] and exported2['key_hex']!=exported['key_hex']
        assert delivery.send_one(cfg)['outcome']=='acknowledged'
        assert received[-1][0]==body and delivery.verify_signature(bytes.fromhex(exported2['key_hex']),body,received[-1][1])
        with db.connect(cfg) as conn:
            store.save_document(conn,cfg,title='Only title changed',body='Changed body',domain='general',dtype='memory',project='/p',doc_id=document)
            versions=[r['resource_version'] for r in conn.execute('SELECT resource_version FROM webhook_events ORDER BY resource_version')]
            assert versions[0]<versions[1]
        # Changed root has a distinct receiver-visible key identity.
        delivery.key_init(cfg,tmp_path/'another-root')
        assert delivery.signing_key(tmp_path/'another-root',sub['id'],2)[0]!=exported2['key_id']


def test_crash_attempt_budget_is_durable_and_replay_bounded(wh):
    sub=subscribe(wh);delivery.capture(wh,True);save(wh)
    for attempt in range(1,7):
        row=delivery.claim(wh);assert row['attempts']==attempt
        with db.connect(wh) as conn:conn.execute("UPDATE webhook_deliveries SET lease_until=now()-interval '1 second'")
    assert delivery.claim(wh) is None
    with db.connect(wh) as conn:
        record=conn.execute('SELECT * FROM webhook_deliveries').fetchone()
        assert record['state']=='dead' and record['outcome']=='exhausted'
        for _ in range(8):
            webhooks.replay(conn,wh,subscription_id=sub['id'],expected_revision=1,delivery_id=str(record['id']))
            conn.execute("UPDATE webhook_deliveries SET state='dead'")
        with pytest.raises(webhooks.WebhookError,match='webhook_unavailable'):
            webhooks.replay(conn,wh,subscription_id=sub['id'],expected_revision=1,delivery_id=str(record['id']))


def test_outage_backoff_dead_letter_replay_and_off(wh):
    with receiver(503) as (endpoint,received):
        cfg=local_policy(wh,endpoint);sub=subscribe(cfg,endpoint=endpoint);delivery.capture(cfg,True);save(cfg)
        for i in range(6):
            assert delivery.send_one(cfg)['outcome']=='response'
            with db.connect(cfg) as conn:
                row=conn.execute('SELECT * FROM webhook_deliveries').fetchone()
                assert row['attempts']==i+1
                if i<5:
                    assert row['state']=='retry' and row['due_at']>row['updated_at']
                    conn.execute('UPDATE webhook_deliveries SET due_at=now()')
        assert row['state']=='dead' and len(received)==6
        delivery.capture(cfg,False)
        assert delivery.send_one(cfg)=={'state':'idle'} and len(received)==6
        with db.connect(cfg) as conn:
            before=conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']
        save(cfg)
        with db.connect(cfg) as conn:assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==before


def test_quota_failure_rolls_back_knowledge_and_audit(wh):
    subscribe(wh);delivery.capture(wh,True)
    with db.connect(wh) as conn:conn.execute('UPDATE webhook_control SET max_records=1')
    save(wh)
    with db.connect(wh) as conn:
        before=conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']
    with pytest.raises(psycopg.Error,match='webhook_capacity'):save(wh)
    with db.connect(wh) as conn:
        assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==1
        assert conn.execute('SELECT count(*) n FROM audit_log').fetchone()['n']==before
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==1
    # No subscribers means no orphan event consumes the finite quota.
    with db.connect(wh) as conn:conn.execute('UPDATE webhook_subscriptions SET enabled=false')
    save(wh)


def test_direct_roles_cannot_read_or_forge_private_state_and_acl_drift(wh):
    for role in ('reader','writer'):
        for table in webhooks.TABLES:
            with db.connect(wh,role=role) as conn:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute('SELECT * FROM '+table)
        with db.connect(wh,role=role) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute("SELECT rag_webhook_emit('memory.created','x','general','/p',NULL,'{}')")
    sub=subscribe(wh)
    with db.connect(wh,role='reader') as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute("SELECT rag_webhook_manage('disable','{}')")
    with db.connect(wh) as conn:
        conn.execute('GRANT SELECT ON webhook_subscriptions TO rag_reader')
        assert webhooks.schema_valid(conn) is False
    with pytest.raises(webhooks.WebhookError,match='incompatible_service_schema'):delivery.capture(wh,True)


def test_canonical_catalog_review_source_lifecycle_and_rollback(wh):
    from agentic_rag import lifecycle
    sub=subscribe(wh,kinds=list(webhooks.KNOWLEDGE_KINDS));delivery.capture(wh,True)
    with db.connect(wh) as conn:
        def claim(name):
            return store.save_claim(conn,wh,title=name,body='Same private source content',domain='general',dtype='memory',project='/p',
                claim_kind='stated',evidence=[{'namespace':'synthetic-webhook','source_id':name,'role':'user','quote':'Same private source content','complete':True}]).doc_id
        managed=claim('managed')
        member=store.save_document(conn,wh,title='Same title',body='Same private body',domain='general',dtype='memory',project='/p').doc_id
        target=store.save_document(conn,wh,title='Same title',body='Same private body',domain='general',dtype='memory',project='/p').doc_id
        store.review_claim(conn,managed,state='confirmed',reason='PRIVATE REVIEW PROSE')
        source=conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',(managed,)).fetchone()['source_key']
        store.set_source_state(conn,source,state='removed',reason='PRIVATE WITHDRAWAL')
        store.set_source_state(conn,source,state='active',reason='PRIVATE REACTIVATION')
        from agentic_rag.lifecycle import preview,apply,correct
        member,target=target,member  # duplicate member is the newer copy
        view=preview(conn,member=member,target=target,operation='exact_duplicate')
        made=apply(conn,wh,member=member,target=target,operation='exact_duplicate',reason='PRIVATE DECISION',
            expected_member_version=view['member']['version'],expected_target_version=view['target']['version'])
        correct(conn,wh,decision_id=made['decision']['id'],expected_revision=1,reason='PRIVATE CORRECTION')
        captured=conn.execute('SELECT kind,payload FROM webhook_events').fetchall()
        kinds=[row['kind'] for row in captured]
        assert kinds.count('memory.created')==3 and kinds.count('claim.reviewed')>=1 and kinds.count('source.changed')==2
        assert 'lifecycle.applied' in kinds and 'lifecycle.corrected' in kinds
        assert 'PRIVATE' not in json.dumps(captured,default=str) and 'Same private' not in json.dumps(captured,default=str)
        before=conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']
        store.save_document(conn,wh,title='Rolled back title',body='Rolled back body',domain='general',dtype='memory',project='/p',commit=False)
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==before+1
        conn.rollback()
    with db.connect(wh) as conn:assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==before


def test_owned_job_null_domain_does_not_broadcast_to_knowledge_or_foreign(wh):
    subscribe(wh,domain=None,kinds=['job.applied','job.error','job.cancelled'])
    subscribe(wh,kinds=['memory.created'])
    with db.connect(wh) as conn:
        conn.execute("UPDATE webhook_subscriptions SET namespace='owner-A' WHERE domain IS NULL")
        delivery.capture(wh,True)
        for owner in ('owner-A','owner-B'):
            stream='stream-'+owner
            conn.execute('INSERT INTO service_streams(session_id,owner_namespace,project) VALUES(%s,%s,%s)',(stream,owner,'/p'))
            receipt=conn.execute("""INSERT INTO service_windows(owner_namespace,session_id,input_cursor,output_cursor,content_hash,payload,project)
                VALUES(%s,%s,'a','b','hash','{}','/p') RETURNING id""",(owner,stream)).fetchone()['id']
            conn.execute("UPDATE service_windows SET state='blocked' WHERE id=%s",(receipt,))
            conn.execute("UPDATE service_windows SET state='queued' WHERE id=%s",(receipt,))
            conn.execute("UPDATE service_windows SET state='applied',result='{" + '"private":"NEVER COPY"' + "}' WHERE id=%s",(receipt,))
        rows=conn.execute('SELECT e.*,d.subscription_id FROM webhook_events e JOIN webhook_deliveries d ON e.id=d.event_id').fetchall()
        assert len(rows)==1 and rows[0]['domain'] is None and rows[0]['owner_namespace']=='owner-A'
        assert rows[0]['kind']=='job.applied' and 'NEVER' not in rows[0]['wire']


def test_scoped_remote_management_revocation_and_readonly(service_store,tmp_path,paused):
    cfg,_=service_store
    app,policy_path=app_fixture(tmp_path,cfg)
    cfg=replace(cfg,service_auth_file=policy_path,webhook_key_file=tmp_path/'root')
    delivery.key_init(cfg,cfg.webhook_key_file)
    with receiver() as (endpoint,received),TestClient(app,base_url='https://testserver') as client:
        cfg=local_policy(cfg,endpoint)
        args=dict(endpoint=endpoint,project='/projects/a',domain='alpha',kinds=['memory.created'],idempotency_key=str(uuid.uuid4()))
        response=client.post('/v1/tools/webhook_subscribe',headers=headers(KEYS[0]),json=args)
        assert response.status_code==200,response.text
        sub=response.json()
        assert client.post('/v1/tools/webhook_subscribe',headers=headers(KEYS[1]),json=args).status_code==403
        for identity in (sub['id'],str(uuid.uuid4())):
            response=client.post('/v1/tools/webhook_status',headers=headers(KEYS[2]),json={'subscription_id':identity})
            assert response.status_code==404 and response.json()=={'error':'webhook_unavailable'}
        status=client.post('/v1/tools/webhook_status',headers=headers(KEYS[0]),json={'subscription_id':sub['id']})
        assert status.status_code==200 and 'credential_reference' not in status.text and endpoint not in status.text
        delivery.capture(cfg,True)
        with db.connect(cfg) as conn:
            store.save_document(conn,cfg,title='Private owned memory',body='never leave',domain='alpha',dtype='memory',project='/projects/a')
        # Revocation between durable capture and socket: exact saved credential is rejected.
        policy_path.write_text(policy_path.read_text().replace('[machines.vm1]','[machines.vm1]\nenabled=false'))
        assert delivery.send_one(cfg)['outcome']=='revoked' and received==[]


def test_queued_subscription_and_result_are_atomic(service_store,tmp_path,paused,monkeypatch):
    from agentic_rag.service import requests as queue,engine
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    args=dict(endpoint='https://example.com/hook',project='/projects/a',domain='alpha',kinds=['memory.created'],idempotency_key=str(uuid.uuid4()))
    original_validator=engine.validator
    original_queue_validator=queue.validator
    original=engine.validator('webhook_subscribe')[0]
    with db.connect(cfg) as conn:before=conn.execute('SELECT count(*) n FROM webhook_subscriptions').fetchone()['n']
    def oversized(**arguments):
        original(**arguments)
        return {'bad':'x'*131073}
    with TestClient(app,base_url='https://testserver') as client:
        identity=queued(client,'webhook_subscribe',args)
        monkeypatch.setattr(engine,'validator',lambda name:(oversized,True))
        monkeypatch.setattr(queue,'validator',engine.validator)
        assert queue.run_one(cfg)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['code']=='result_too_large'
        with db.connect(cfg) as conn:assert conn.execute('SELECT count(*) n FROM webhook_subscriptions').fetchone()['n']==before
        # Normal retry is one committed subscription and one durable result.
        monkeypatch.setattr(engine,'validator',original_validator)
        monkeypatch.setattr(queue,'validator',original_queue_validator)
        identity=queued(client,'webhook_subscribe',args)
        assert queue.run_one(cfg)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed',result
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM webhook_subscriptions').fetchone()['n']==before+1
            assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='webhook.subscribe' AND summary=%s",(result['result']['id'],)).fetchone()['n']==1


def test_malicious_dns_proxy_redirect_and_hard_timeout(monkeypatch):
    # Resolver/socket seams; these tests never probe a private service.
    attempts=[]
    actual_resolve=delivery.resolve
    monkeypatch.setattr(delivery,'resolve',lambda *args:['93.184.216.34','127.0.0.1'])
    monkeypatch.setattr(delivery.socket,'socket',lambda *args:attempts.append(args))
    with pytest.raises(ValueError):delivery.transmit('https://example.com/',b'{}',{})
    assert attempts==[]
    with pytest.raises(ValueError):delivery.validate_addresses('https://example.com/', ['::ffff:169.254.169.254'],{'https://example.com':['169.254.0.0/16']})
    def blocked(*a,**kw):raise __import__('subprocess').TimeoutExpired(a[0],kw['timeout'])
    monkeypatch.setattr(delivery.subprocess,'run',blocked)
    with pytest.raises(TimeoutError):actual_resolve('example.com',443,time.monotonic()+.01)


def test_same_resource_serialization_and_reverse_delivery(wh):
    from concurrent.futures import ThreadPoolExecutor
    subscribe(wh,kinds=['memory.created','memory.changed']);delivery.capture(wh,True)
    document=save(wh)
    with db.connect(wh) as first,ThreadPoolExecutor(max_workers=1) as pool:
        store.save_document(first,wh,title='First title',body='First body',domain='general',dtype='memory',project='/p',doc_id=document,commit=False)
        def second():
            with db.connect(wh) as conn:
                return store.save_document(conn,wh,title='Second title',body='Second body',domain='general',dtype='memory',project='/p',doc_id=document).doc_id
        future=pool.submit(second)
        first.commit()
        assert future.result(timeout=10)==document
    with db.connect(wh) as conn:
        events=[r['payload'] for r in conn.execute("SELECT payload FROM webhook_events WHERE kind='memory.changed' ORDER BY resource_version")]
        assert len(events)==2 and events[0]['resource_version']<events[1]['resource_version']
        assert conn.execute('SELECT title,body FROM documents WHERE id=%s',(document,)).fetchone()=={'title':'Second title','body':'Second body'}
    latest=-1;accepted=[]
    for event in reversed(events):
        if event['resource_version']>latest:
            accepted.append(event['event_id']);latest=event['resource_version']
    assert accepted==[events[1]['event_id']]


def test_038_scrubs_arbitrary_default_acl_grants(tmp_path):
    from .test_feedback_review import acl_roles
    # Fully disposable grantee. Existing source-table ACLs must remain unchanged.
    role='wh_acl_'+uuid.uuid4().hex[:12]
    with psycopg.connect(db.dsn(Config(),dbname='postgres'),autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} NOSUPERUSER').format(sql.Identifier(role)))
        try:
            with isolated_database(Config(),initialize=False) as cfg:
                prefix=tmp_path/'037';prefix.mkdir()
                for file in sorted(db.SQL_DIR.glob('*.sql'))[:37]:(prefix/file.name).write_bytes(file.read_bytes())
                with db.connect(cfg) as conn:
                    db.apply_migrations(conn,prefix)
                    original=conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl']
                    for category,rights in [('TABLES','ALL'),('SEQUENCES','ALL'),('FUNCTIONS','EXECUTE')]:
                        conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT '+rights+' ON '+category+' TO {}').format(sql.Identifier(role)))
                    conn.commit()
                    assert db.apply_migrations(conn,db.SQL_DIR)==['038_webhooks.sql']
                    assert webhooks.schema_valid(conn)
                    assert conn.execute("SELECT relacl::text acl FROM pg_class WHERE oid='documents'::regclass").fetchone()['acl']==original
                    for table in webhooks.TABLES:
                        assert not conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') bad",(role,table)).fetchone()['bad']
                    for sequence in ['webhook_resource_order','webhook_events_capture_order_seq']:
                        assert not conn.execute("SELECT has_sequence_privilege(%s,%s,'USAGE,SELECT,UPDATE') bad",(role,sequence)).fetchone()['bad']
                    for function in ['rag_webhook_manage(text,jsonb,jsonb)','rag_webhook_finalize()']:
                        assert not conn.execute("SELECT has_function_privilege(%s,%s,'EXECUTE') bad",(role,function)).fetchone()['bad']
        finally:admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_queued_process_death_before_publication_and_replay(service_store,tmp_path,paused):
    import subprocess,sys
    from .test_request_queue import packet
    from agentic_rag.service import requests as queue
    cfg,_=service_store
    app,p=app_fixture(tmp_path,cfg);cfg=replace(cfg,service_auth_file=p)
    args=dict(endpoint='https://example.com/hook',domain='alpha',project='/projects/a',kinds=['memory.changed'],idempotency_key=str(uuid.uuid4()))
    value=packet('webhook_subscribe',args)
    code='''
import os
from pathlib import Path
from agentic_rag.config import Config
from agentic_rag.service import engine,requests
cfg=Config(db_name=os.environ['WH_TEST_DB'],db_host='127.0.0.1',service_auth_file=Path(os.environ['WH_TEST_POLICY']),ollama_url='http://127.0.0.1:1')
original=engine.validator
def crash(name):
 fn,write=original(name)
 def execute(**arguments):
  result=fn(**arguments)
  os._exit(9)
 return execute,write
engine.validator=crash
requests.validator=crash
requests.run_one(cfg)
'''
    with TestClient(app,base_url='https://testserver') as client:
        response=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert response.status_code==202
        identity=response.json()['request_id']
        process=subprocess.run([sys.executable,'-c',code],env={**os.environ,'WH_TEST_DB':cfg.db_name,'WH_TEST_POLICY':str(p)},capture_output=True,timeout=30)
        assert process.returncode==9,process.stderr[-1000:]
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM webhook_subscriptions WHERE idempotency_key=%s',(args['idempotency_key'],)).fetchone()['n']==0
        assert queue.run_one(cfg)
        result=client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()
        assert result['state']=='completed'
        replay=client.post('/v1/requests',headers=headers(KEYS[0]),json=value)
        assert replay.json()['request_id']==identity
        assert client.get('/v1/requests/'+identity,headers=headers(KEYS[0])).json()==result
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM webhook_subscriptions WHERE idempotency_key=%s',(args['idempotency_key'],)).fetchone()['n']==1


def test_capture_and_subscription_mutation_use_consistent_lock_order(wh):
    # Mutation caught: FOR UPDATE prevents an emitter's FK KEY SHARE while
    # a manager may still finish its transaction. NO KEY UPDATE must coexist.
    from concurrent.futures import ThreadPoolExecutor
    sub=subscribe(wh);delivery.capture(wh,True)
    with db.connect(wh,role='writer') as manager,ThreadPoolExecutor(max_workers=1) as pool:
        changed=webhooks.update(manager,wh,subscription_id=sub['id'],expected_revision=1,endpoint='https://example.com/new')
        assert changed['revision']==2
        future=pool.submit(save,wh)
        try:assert future.result(timeout=5)
        finally:manager.rollback()
    with db.connect(wh) as conn:
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==1
        assert conn.execute("SELECT state FROM webhook_deliveries").fetchone()['state']=='pending'


def test_management_rpc_requires_optimistic_revision_even_for_direct_writer(wh):
    sub=subscribe(wh)
    with db.connect(wh,role='writer') as conn:
        from psycopg.types.json import Jsonb
        with pytest.raises(psycopg.Error,match='webhook_conflict'):
            conn.execute("SELECT rag_webhook_manage('disable',%s)",(Jsonb({'subscription_id':sub['id']}),))
    with db.connect(wh,role='writer') as conn:
        assert webhooks.status(conn,wh,subscription_id=sub['id'])['subscription']['enabled'] is True
