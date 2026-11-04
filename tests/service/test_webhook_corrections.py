"""Independent-review regressions: deferred admission and terminal retirement."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time
import uuid

import psycopg
import pytest

from agentic_rag import db,store,webhooks
from agentic_rag import webhook_delivery as delivery
from .test_webhooks import wh,subscribe,save


def change(conn,cfg,document,title):
    return store.save_document(conn,cfg,title=title,body='Private canonical '+title,domain='general',dtype='memory',
                               project='/p',doc_id=document,commit=False)


def test_exact_multi_document_producer_does_not_block_its_peer_at_quota(wh):
    # A holds DocA; B only writes DocB. A then needs DocB. B must be able to
    # complete without waiting on admission held by A's unfinished transaction.
    first,second=save(wh),save(wh)
    subscribe(wh,kinds=['memory.changed']);delivery.capture(wh,True)
    ready=threading.Event();written=threading.Event();commit_gate=threading.Event();pids=[]
    def peer():
        with db.connect(wh,role='writer') as conn:
            pids.append(conn.info.backend_pid);ready.set()
            change(conn,wh,second,'B-only DocB');written.set()
            assert commit_gate.wait(timeout=5)
            conn.commit()
    with db.connect(wh,role='writer') as first_writer,ThreadPoolExecutor(max_workers=1) as pool:
        change(first_writer,wh,first,'A DocA')
        future=pool.submit(peer);assert ready.wait(timeout=3)
        deadline=time.monotonic()+4
        waiting=False
        while time.monotonic()<deadline:
            waiting=first_writer.execute('SELECT %s=ANY(pg_blocking_pids(%s)) waiting',
                (first_writer.info.backend_pid,pids[0])).fetchone()['waiting']
            if waiting or written.is_set():break
            time.sleep(.01)
        assert waiting or written.is_set()
        commit_gate.set()
        try:
            change(first_writer,wh,second,'A DocB after B')
            first_writer.commit()
        except BaseException:
            first_writer.rollback()
            raise
        future.result(timeout=6)
    with db.connect(wh) as conn:
        assert conn.execute('SELECT title FROM documents WHERE id=%s',(second,)).fetchone()['title']=='A DocB after B'
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==3
        assert conn.execute('SELECT count(*) n FROM webhook_events WHERE resource_version<=0').fetchone()['n']==0


def test_terminal_cancel_is_audited_idempotent_and_recovers_capacity(wh):
    sub=subscribe(wh);delivery.capture(wh,True);save(wh)
    with db.connect(wh) as conn:
        conn.execute('UPDATE webhook_control SET max_records=1')
        row=conn.execute("UPDATE webhook_deliveries SET state='revoked',outcome='revoked',replay_count=8,updated_at=now()-interval '8 days' RETURNING id").fetchone()
    operation=getattr(delivery,'cancel',None)
    assert callable(operation), 'audited terminal delivery cancellation is missing'
    cancelled=operation(wh,delivery_id=str(row['id']),expected_state='revoked')
    assert cancelled['state']=='cancelled' and cancelled['changed'] is True
    repeated=operation(wh,delivery_id=str(row['id']),expected_state='revoked')
    assert repeated['changed'] is False and repeated['cancelled_at']==cancelled['cancelled_at']
    with db.connect(wh) as conn:
        record=conn.execute('SELECT lease,lease_until,updated_at FROM webhook_deliveries').fetchone()
        assert record['lease'] is None and record['lease_until'] is None
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='webhook.cancel'").fetchone()['n']==1
    assert delivery.prune(wh)=={'deliveries':0,'events':0}  # seven days start now, not before cancellation
    with pytest.raises(psycopg.Error,match='webhook_capacity'):save(wh)
    with db.connect(wh) as conn:conn.execute("UPDATE webhook_deliveries SET updated_at=now()-interval '8 days'; UPDATE webhook_events SET created_at=now()-interval '8 days'")
    assert delivery.prune(wh)=={'deliveries':1,'events':1}
    save(wh)
    with db.connect(wh) as conn:assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==1


@pytest.mark.parametrize('isolation',['READ COMMITTED','REPEATABLE READ'])
@pytest.mark.parametrize('boundary',['records','bytes'])
def test_concurrent_commits_enforce_hard_event_quota_and_snapshot_fence(wh,isolation,boundary):
    project='/p' if boundary=='records' else '/'+('/'.join(['p'*100]*12))
    with db.connect(wh) as conn:
        docs=[store.save_document(conn,wh,title='Quota '+str(n),body='Synthetic original '+str(n),domain='general',dtype='memory',project=project).doc_id for n in range(2)]
    subscribe(wh,project=project,kinds=['memory.changed']);delivery.capture(wh,True)
    with db.connect(wh) as conn:
        conn.execute('UPDATE webhook_control SET max_records=%s,max_bytes=%s',(1 if boundary=='records' else 10000,4096 if boundary=='bytes' else 33554432))
    barrier=threading.Barrier(2)
    def writer(index):
        with db.connect(wh,role='writer') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
            store.save_document(conn,wh,title='Committed quota '+str(index),body='Concurrent '+str(index),domain='general',dtype='memory',project=project,doc_id=docs[index],commit=False)
            barrier.wait(timeout=5)
            try:conn.commit();return 'committed'
            except psycopg.Error as error:
                code=error.sqlstate;conn.rollback();return code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(writer,range(2)))
    assert sorted(results)==sorted(['committed','40001' if isolation=='REPEATABLE READ' else '54000'])
    with db.connect(wh) as conn:
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==1
        assert conn.execute('SELECT count(*) n FROM webhook_deliveries').fetchone()['n']==1
        assert conn.execute("SELECT count(*) n FROM documents WHERE title LIKE 'Committed quota%'").fetchone()['n']==1
        assert conn.execute('SELECT sum(octet_length(wire)+octet_length(payload::text)) n FROM webhook_events').fetchone()['n']<= (4096 if boundary=='bytes' else 33554432)


@pytest.mark.parametrize('isolation',['READ COMMITTED','REPEATABLE READ'])
def test_concurrent_subscription_admission_is_hard_bounded(wh,isolation):
    for _ in range(31):subscribe(wh)
    barrier=threading.Barrier(2)
    def create(_):
        with db.connect(wh,role='writer') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
            webhooks.subscribe(conn,wh,endpoint='https://example.com/hook',domain='general',project='/p',kinds=['memory.created'],idempotency_key=str(uuid.uuid4()))
            barrier.wait(timeout=5)
            try:conn.commit();return 'committed'
            except psycopg.Error as error:
                code=error.sqlstate;conn.rollback();return code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
    assert sorted(results)==sorted(['committed','40001' if isolation=='REPEATABLE READ' else '54000'])
    with db.connect(wh) as conn:assert conn.execute('SELECT count(*) n FROM webhook_subscriptions').fetchone()['n']==32


def test_final_wire_order_follows_commit_for_edge_and_memory_same_resource(wh):
    import json
    source,target=save(wh),save(wh)
    subscribe(wh,kinds=['memory.changed','edge.supersedes']);delivery.capture(wh,True)
    with db.connect(wh,role='writer') as edge_writer:
        slug=edge_writer.execute('SELECT slug FROM documents WHERE id=%s',(target,)).fetchone()['slug']
        # Direct limited-role edge fixture exercises the retained trigger branch
        # whose only document lock is its FK KEY SHARE, not a title/body UPDATE.
        edge_writer.execute("INSERT INTO edges(src_id,dst_id,dst_slug,predicate,created_by) VALUES(%s,%s,%s,'supersedes','manual')",(source,target,slug))
        edge_writer.execute("INSERT INTO audit_log(actor,op,summary) VALUES('cli','synthetic_edge','scoped synthetic edge fixture')")
        assert edge_writer.execute('SELECT 1').fetchone()
        with db.connect(wh) as observer:
            assert observer.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0
        with ThreadPoolExecutor(max_workers=1) as pool:
            def change_memory():
                with db.connect(wh,role='writer') as conn:
                    change(conn,wh,source,'Earlier committed memory');conn.commit()
            future=pool.submit(change_memory)
            try:future.result(timeout=5)
            except BaseException:edge_writer.rollback();raise
        edge_writer.commit()
    with db.connect(wh) as conn:
        rows=conn.execute('SELECT kind,resource,resource_version,payload,wire FROM webhook_events ORDER BY resource_version').fetchall()
        assert [row['kind'] for row in rows]==['memory.changed','edge.supersedes']
        assert all(row['resource']==source and row['resource_version']>0 and json.loads(row['wire'])==row['payload'] and row['payload']['resource_version']==row['resource_version'] for row in rows)
        assert rows[0]['resource_version']<rows[1]['resource_version']


def test_private_stage_is_invisible_and_set_constraints_marks_end_of_write_phase(wh):
    import json
    doc=save(wh);subscribe(wh,kinds=['memory.changed']);delivery.capture(wh,True)
    with db.connect(wh) as conn:
        change(conn,wh,doc,'One captured state')
        staged=conn.execute('SELECT resource_version,payload,wire FROM webhook_events').fetchone()
        assert staged['resource_version']==0 and staged['payload']['resource_version']==0
        assert delivery.claim(wh) is None
        # Explicit IMMEDIATE is supported here as an end-of-canonical-write
        # boundary. Arbitrary further custom SQL resource locking is not claimed.
        conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
        finalized=conn.execute('SELECT resource_version,payload,wire FROM webhook_events').fetchone()
        assert finalized['resource_version']>0 and json.loads(finalized['wire'])==finalized['payload']
        assert {k:v for k,v in staged['payload'].items() if k!='resource_version'}=={k:v for k,v in finalized['payload'].items() if k!='resource_version'}
        conn.rollback()
    with db.connect(wh) as conn:assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0


def test_same_transaction_management_capture_and_prune_skip_locked_rows(wh):
    sub=subscribe(wh);delivery.capture(wh,True);save(wh)
    with db.connect(wh) as conn:
        row=conn.execute("UPDATE webhook_deliveries SET state='disabled',outcome='disabled' RETURNING id").fetchone()
    delivery.cancel(wh,delivery_id=str(row['id']),expected_state='disabled')
    with db.connect(wh) as conn:
        conn.execute("UPDATE webhook_deliveries SET updated_at=now()-interval '8 days'; UPDATE webhook_events SET created_at=now()-interval '8 days'")
    with db.connect(wh,role='writer') as manager:
        webhooks.replay(manager,wh,subscription_id=sub['id'],expected_revision=1,delivery_id=str(row['id']))
        store.save_document(manager,wh,title='Management plus capture',body='Synthetic same transaction canonical write',domain='general',dtype='memory',project='/p',commit=False)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(delivery.prune,wh)
            try:assert future.result(timeout=5)=={'deliveries':0,'events':0}
            except BaseException:manager.rollback();raise
        manager.commit()
    with db.connect(wh) as conn:
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==2
        assert conn.execute('SELECT state,cancelled_from FROM webhook_deliveries WHERE id=%s',(row['id'],)).fetchone()=={'state':'pending','cancelled_from':None}


@pytest.mark.parametrize('terminal',['dead','revoked','disabled'])
def test_cancel_expected_state_authority_replay_and_fence(wh,terminal):
    sub=subscribe(wh);delivery.capture(wh,True);save(wh)
    lease=uuid.uuid4()
    with db.connect(wh) as conn:
        row=conn.execute('UPDATE webhook_deliveries SET state=%s,lease=%s,lease_until=now()+interval \'1 minute\' RETURNING id',(terminal,lease)).fetchone()
        original=conn.execute('SELECT credential_reference FROM webhook_subscriptions').fetchone()['credential_reference']
    with pytest.raises(webhooks.WebhookError,match='webhook_conflict'):
        delivery.cancel(wh,delivery_id=str(row['id']),expected_state='dead' if terminal!='dead' else 'revoked')
    one=delivery.cancel(wh,delivery_id=str(row['id']),expected_state=terminal)
    assert delivery.cancel(wh,delivery_id=str(row['id']),expected_state=terminal)['cancelled_at']==one['cancelled_at']
    with db.connect(wh) as conn:
        assert conn.execute('SELECT lease,lease_until FROM webhook_deliveries').fetchone()=={'lease':None,'lease_until':None}
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='webhook.cancel'").fetchone()['n']==1
        webhooks.replay(conn,wh,subscription_id=sub['id'],expected_revision=1,delivery_id=str(row['id']))
        assert conn.execute('SELECT credential_reference FROM webhook_subscriptions').fetchone()['credential_reference']==original
        assert conn.execute('SELECT state,cancelled_from FROM webhook_deliveries').fetchone()=={'state':'pending','cancelled_from':None}
    from agentic_rag.service.queued_transaction import GROUP,EXECUTION
    from agentic_rag.service.context import CURRENT
    from agentic_rag.service.fence import LEASE
    for context in (CURRENT,GROUP,EXECUTION,LEASE):
        token=context.set(object())
        try:
            with pytest.raises(webhooks.WebhookError,match='operator_local'):delivery.cancel(wh,delivery_id=str(row['id']),expected_state=terminal)
        finally:context.reset(token)
    with pytest.raises(webhooks.WebhookError,match='operator_local'):
        delivery.cancel(replace(wh,service_mode='client'),delivery_id=str(row['id']),expected_state=terminal)


@pytest.mark.parametrize('state',['pending','retry','leased','acknowledged'])
def test_cancel_refuses_live_or_acknowledged_state(wh,state):
    subscribe(wh);delivery.capture(wh,True);save(wh)
    with db.connect(wh) as conn:row=conn.execute('UPDATE webhook_deliveries SET state=%s RETURNING id',(state,)).fetchone()
    with pytest.raises(webhooks.WebhookError,match='webhook_conflict'):delivery.cancel(wh,delivery_id=str(row['id']),expected_state='dead')
    with db.connect(wh) as conn:
        assert conn.execute('SELECT state FROM webhook_deliveries').fetchone()['state']==state
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='webhook.cancel'").fetchone()['n']==0


def test_cancel_audit_failure_rolls_back_retirement(wh):
    subscribe(wh);delivery.capture(wh,True);save(wh)
    with db.connect(wh) as conn:
        row=conn.execute("UPDATE webhook_deliveries SET state='revoked',outcome='revoked' RETURNING id").fetchone()
        conn.execute("""CREATE FUNCTION synthetic_cancel_reject() RETURNS trigger LANGUAGE plpgsql AS $$
         BEGIN IF NEW.op='webhook.cancel' THEN RAISE EXCEPTION 'synthetic_audit_failure'; END IF; RETURN NEW; END $$;
         CREATE TRIGGER synthetic_cancel_reject BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION synthetic_cancel_reject()""")
    with pytest.raises(psycopg.Error,match='synthetic_audit_failure'):
        delivery.cancel(wh,delivery_id=str(row['id']),expected_state='revoked')
    with db.connect(wh) as conn:
        assert conn.execute('SELECT state,cancelled_from FROM webhook_deliveries').fetchone()=={'state':'revoked','cancelled_from':None}
        assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='webhook.cancel'").fetchone()['n']==0


def test_actual_multi_document_mining_and_lifecycle_producers(wh,tmp_path,monkeypatch):
    import json
    from agentic_rag import mining,lifecycle,query_cache
    from tests.test_mining import _raw,_runner_returning
    monkeypatch.setattr(mining,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda *a,**k:None)
    subscribe(wh,kinds=list(webhooks.KNOWLEDGE_KINDS));delivery.capture(wh,True)
    transcript=tmp_path/'synthetic.jsonl'
    transcript.write_text(json.dumps({'uuid':'synthetic-1','type':'user','message':{'role':'user','content':'Synthetic private mining evidence'}})+'\n')
    payload=_raw(memories=[{'title':'First mined memory','body':'First synthetic mining body','domain':'general','edges':[]},
                           {'title':'Second mined memory','body':'Second synthetic mining body','domain':'general','edges':[]}])
    with db.connect(wh) as conn:
        result=mining.mine_session(conn,wh,session_id='synthetic-webhooks-review',transcript_path=str(transcript),last_uuid=None,project='/p',runner=_runner_returning(payload))
        assert result.saved==2
        older=store.save_document(conn,wh,title='Duplicate same title',body='Duplicate same body',domain='general',dtype='memory',project='/p').doc_id
        newer=store.save_document(conn,wh,title='Duplicate same title',body='Duplicate same body',domain='general',dtype='memory',project='/p').doc_id
        view=lifecycle.preview(conn,newer,older,operation='exact_duplicate')
        applied=lifecycle.apply(conn,wh,member=newer,target=older,operation='exact_duplicate',expected_member_version=view['member']['version'],expected_target_version=view['target']['version'],reason='Synthetic lifecycle operation')
        lifecycle.correct(conn,wh,decision_id=applied['decision']['id'],expected_revision=1,reason='Synthetic correction')
        rows=conn.execute('SELECT kind,resource_version,payload,wire FROM webhook_events ORDER BY resource_version').fetchall()
        assert [r['kind'] for r in rows].count('memory.created')==4
        assert 'lifecycle.applied' in [r['kind'] for r in rows] and 'lifecycle.corrected' in [r['kind'] for r in rows]
        assert all(r['resource_version']>0 and json.loads(r['wire'])==r['payload'] for r in rows)


@pytest.mark.parametrize('drift',[
    "GRANT USAGE ON SEQUENCE webhook_events_capture_order_seq TO rag_reader",
    "ALTER TABLE webhook_events DISABLE TRIGGER webhook_event_admission",
    "ALTER TABLE webhook_subscriptions DISABLE TRIGGER webhook_subscription_admission",
    "ALTER TABLE webhook_deliveries DROP CONSTRAINT webhook_cancel_marker",
    "ALTER TABLE webhook_deliveries DROP CONSTRAINT webhook_cancel_origin",
    "ALTER TABLE webhook_events DROP CONSTRAINT webhook_event_staging_version",
])
def test_new_commit_and_retirement_invariants_fail_closed_on_schema_drift(wh,drift):
    with db.connect(wh) as conn:
        assert webhooks.schema_valid(conn)
        conn.execute(drift)
        assert webhooks.schema_valid(conn) is False
        conn.rollback()


def test_immediate_constraints_cannot_commit_delivery_fanout_above_quota(wh):
    subscribe(wh);subscribe(wh);delivery.capture(wh,True)
    with db.connect(wh) as conn:conn.execute('UPDATE webhook_control SET max_records=3')
    with pytest.raises(psycopg.Error,match='webhook_capacity'):
        with db.connect(wh,role='writer') as conn:
            conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
            for n in range(2):
                store.save_document(conn,wh,title='Immediate fanout '+str(n),body='Synthetic fanout '+str(n),domain='general',dtype='memory',project='/p',commit=False)
            conn.commit()
    with db.connect(wh) as conn:
        assert conn.execute('SELECT count(*) n FROM webhook_events').fetchone()['n']==0
        assert conn.execute('SELECT count(*) n FROM webhook_deliveries').fetchone()['n']==0
        assert conn.execute("SELECT count(*) n FROM documents WHERE title LIKE 'Immediate fanout%'").fetchone()['n']==0
