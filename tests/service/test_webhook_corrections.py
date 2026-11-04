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
