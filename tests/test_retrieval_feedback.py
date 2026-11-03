"""Real PostgreSQL feedback isolation, concurrency and atomicity contracts."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import uuid

import psycopg
import pytest

from agentic_rag import db
from agentic_rag.config import Config
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope


def key():
    return str(uuid.uuid4())


@pytest.fixture(scope='module')
def owned():
    from agentic_rag import store
    cfg = Config(ollama_url='http://127.0.0.1:1', rerank_url='http://127.0.0.1:1')
    with isolated_database(cfg) as cfg:
        with db.connect(cfg) as conn:
            conn.execute("INSERT INTO domains(name) VALUES ('alpha'),('beta')")
            conn.commit()
            ids = [store.save_claim(conn, cfg, title='Synthetic feedback '+n, body='Synthetic protected evidence '+n,
                                      claim_kind='stated', evidence=[{'namespace':'synthetic-feedback','source_id':n,'role':'user',
                                      'quote':'Synthetic protected evidence '+n,'complete':True}],
                                      domain='alpha' if n != 'foreign' else 'beta', dtype='memory', project='/projects/a').doc_id
                   for n in ('first','second','foreign')]
        yield cfg, ids


def principal(user='alice', machine='vm1', readonly=False):
    return Principal(user, machine, 'one', frozenset({'alpha'}), frozenset() if readonly else frozenset({'alpha'}),
                     frozenset({'/projects/a'}), frozenset() if readonly else frozenset({'/projects/a'}))


def call(owned, name, **kwargs):
    from agentic_rag import feedback
    cfg, _ = owned
    cfg = replace(cfg, feedback_enabled=True)
    with request_scope(principal(), cfg):
        with db.connect(cfg, role='writer') as conn:
            return getattr(feedback, name)(conn, cfg, **kwargs)


def capture(owned, **kwargs):
    return call(owned, 'capture', query='Synthetic protected evidence', domain='alpha', project='/projects/a',
                idempotency_key=kwargs.pop('idempotency_key', key()), **kwargs)


def knowledge_hash(cfg):
    with db.connect(cfg) as conn:
        tables = ['documents','chunks','claim_records','claim_evidence','knowledge_sources','source_revisions','claim_revisions','pins','edges']
        return {table: hashlib.sha256(json.dumps(conn.execute(f'SELECT to_jsonb(t) row FROM {table} t ORDER BY to_jsonb(t)::text').fetchall(), sort_keys=True, default=str).encode()).hexdigest() for table in tables}


def test_replay_revision_retraction_privacy_and_knowledge_immutability(owned):
    # Missing digest checks, optimistic locking, secret stripping or knowledge writes fail here.
    from agentic_rag import feedback
    cfg, ids = owned
    before = knowledge_hash(cfg)
    request_key = key()
    first = capture(owned, idempotency_key=request_key)
    assert capture(owned, idempotency_key=request_key)['event']['id'] == first['event']['id']
    with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
        call(owned, 'capture', query='Different query', domain='alpha', project='/projects/a', idempotency_key=request_key)
    event = first['event']
    assert event['query_sha256'] == hashlib.sha256(b'Synthetic protected evidence').hexdigest()
    submit_key = key()
    values = dict(event_id=event['id'], kind='wrong_source', idempotency_key=submit_key,
                  result_id=ids[0], expected_id=ids[1], comment='password=syntheticsecretvalue')
    signal = call(owned, 'submit', **values)
    assert signal['revision'] == 1 and signal['comment'] == '[REDACTED]'
    assert call(owned, 'submit', **values)['id'] == signal['id']
    with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
        call(owned, 'submit', **{**values, 'kind':'useful'})
    updated = call(owned, 'update', feedback_id=signal['id'], expected_revision=1, kind='missing_evidence', expected_id=ids[1])
    assert updated['revision'] == 2 and len(updated['history']) == 2
    with pytest.raises(feedback.FeedbackError, match='feedback_conflict'):
        call(owned, 'retract', feedback_id=signal['id'], expected_revision=1)
    retracted = call(owned, 'retract', feedback_id=signal['id'], expected_revision=2)
    assert retracted['state'] == 'retracted' and retracted['revision'] == 3
    assert knowledge_hash(cfg) == before
    with db.connect(cfg) as conn:
        rows = conn.execute('SELECT to_jsonb(e)::text data FROM retrieval_feedback_events e').fetchall()
        assert all('Synthetic protected evidence' not in r['data'] for r in rows)


def test_foreign_clients_readonly_visibility_and_immutable_identity(owned):
    # Mutation caught: namespace/actor or existing document RLS bypass.
    from agentic_rag import feedback
    cfg, ids = owned
    cfg = replace(cfg, feedback_enabled=True)
    event = capture(owned)['event']
    signal = call(owned, 'submit', event_id=event['id'], kind='useful', idempotency_key=key())
    for p in (principal('bob'), principal(machine='vm2')):
        with request_scope(p, cfg):
            with db.connect(cfg, role='writer') as conn:
                assert conn.execute('SELECT id FROM retrieval_feedback WHERE id=%s',(signal['id'],)).fetchall() == []
                with pytest.raises(feedback.FeedbackError, match='feedback_unavailable'):
                    feedback.get(conn,cfg,feedback_id=signal['id'])
    for expected in (ids[2], key()):
        with pytest.raises(feedback.FeedbackError, match='feedback_unavailable'):
            call(owned,'submit',event_id=event['id'],kind='missing_evidence',expected_id=expected,idempotency_key=key())
    with request_scope(principal(readonly=True), cfg):
        with db.connect(cfg,role='writer') as conn:
            with pytest.raises(feedback.FeedbackError, match='feedback_unavailable'):
                feedback.submit(conn,cfg,event_id=event['id'],kind='useful',idempotency_key=key())
    with request_scope(principal(),cfg):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg,role='writer') as conn:
                conn.execute("UPDATE retrieval_feedback SET namespace='spoof' WHERE id=%s",(signal['id'],))


def test_capture_and_signal_races_and_audit_failure_rollback(owned):
    # Mutation caught: absent namespace serialization, revision check or audit transaction.
    from agentic_rag import feedback
    cfg,_=owned
    request_key=key()
    with ThreadPoolExecutor(max_workers=4) as pool:
        events=list(pool.map(lambda _:capture(owned,idempotency_key=request_key),range(4)))
    assert len({e['event']['id'] for e in events})==1
    event=events[0]['event']
    submit_key=key()
    def submit(_):
        return call(owned,'submit',event_id=event['id'],kind='not_useful',idempotency_key=submit_key)
    with ThreadPoolExecutor(max_workers=4) as pool:
        signals=list(pool.map(submit,range(4)))
    assert len({s['id'] for s in signals})==1
    def update(_):
        try:
            return call(owned,'update',feedback_id=signals[0]['id'],expected_revision=1,kind='useful')['revision']
        except feedback.FeedbackError as e:
            return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str,pool.map(update,range(2))))==['2','feedback_conflict']
    def retract(_):
        try:
            return call(owned,'retract',feedback_id=signals[0]['id'],expected_revision=2)['state']
        except feedback.FeedbackError as e:
            return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(retract,range(2)))==['feedback_conflict','retracted']
    with db.connect(cfg) as conn:
        usage_before=conn.execute('SELECT * FROM retrieval_feedback_usage WHERE namespace=%s',(principal().namespace,)).fetchone()
    with db.connect(cfg) as conn:
        conn.execute("CREATE FUNCTION reject_feedback_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.op LIKE 'feedback_%' THEN RAISE EXCEPTION 'synthetic audit fault'; END IF; RETURN NEW; END $$")
        conn.execute('CREATE TRIGGER reject_feedback_audit BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION reject_feedback_audit()')
    fail_key=key()
    try:
        with pytest.raises(psycopg.Error):
            call(owned,'submit',event_id=event['id'],kind='useful',idempotency_key=fail_key)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT id FROM retrieval_feedback WHERE idempotency_key=%s',(fail_key,)).fetchall()==[]
            assert conn.execute('SELECT * FROM retrieval_feedback_usage WHERE namespace=%s',(principal().namespace,)).fetchone()==usage_before
    finally:
        with db.connect(cfg) as conn:conn.execute('DROP TRIGGER reject_feedback_audit ON audit_log')
    assert call(owned,'submit',event_id=event['id'],kind='useful',idempotency_key=fail_key)['revision']==1


def test_disabled_inspection_caps_and_changed_evidence(owned,monkeypatch):
    from agentic_rag import feedback
    cfg,ids=owned
    event=capture(owned)['event']
    signal=call(owned,'submit',event_id=event['id'],kind='missing_evidence',expected_id=ids[1],idempotency_key=key())
    with request_scope(principal(),cfg):
        with db.connect(cfg,role='writer') as conn:
            assert feedback.get(conn,cfg,feedback_id=signal['id'])['id']==signal['id']
            with pytest.raises(feedback.FeedbackError,match='feedback_disabled'):
                feedback.retract(conn,cfg,feedback_id=signal['id'],expected_revision=1)
    with pytest.raises(ValueError):capture(owned,k=21)
    monkeypatch.setattr(feedback,'MAX_EVENTS',1)
    with pytest.raises(feedback.FeedbackError,match='feedback_quota'):
        capture(owned)
    monkeypatch.setattr(feedback,'MAX_EVENTS',1024)
    monkeypatch.setattr(feedback,'MAX_HOURLY',1)
    with pytest.raises(feedback.FeedbackError,match='feedback_rate_limit'):
        capture(owned)
    monkeypatch.setattr(feedback,'MAX_HOURLY',120)
    with db.connect(cfg) as conn:conn.execute('UPDATE documents SET status=\'archived\' WHERE id=%s',(ids[1],))
    assert call(owned,'get',feedback_id=signal['id'])['stale'] is True


def test_idempotent_retry_survives_changed_expected_version(owned):
    from agentic_rag import store
    cfg,ids=owned
    event=capture(owned)['event']
    args=dict(event_id=event['id'],kind='missing_evidence',expected_id=ids[0],idempotency_key=key())
    signal=call(owned,'submit',**args)
    with db.connect(cfg) as conn:
        source=conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',(ids[0],)).fetchone()['source_key']
        store.set_source_state(conn,source,state='removed',reason='Synthetic source withdrawn')
    replay=call(owned,'submit',**args)
    assert replay['id']==signal['id'] and replay['stale'] is True


def test_retained_quota_survives_scope_revocation(owned,monkeypatch):
    # Mutation caught: quota derived only from currently RLS-visible rows.
    from agentic_rag import feedback
    cfg,_=owned
    cfg=replace(cfg,feedback_enabled=True)
    capture(owned)
    monkeypatch.setattr(feedback,'MAX_EVENTS',1)
    changed=replace(principal(),read_domains=frozenset({'beta'}),write_domains=frozenset({'beta'}))
    with request_scope(changed,cfg):
        with db.connect(cfg,role='writer') as conn:
            assert conn.execute('SELECT id FROM retrieval_feedback_events').fetchall()==[]
            with pytest.raises(feedback.FeedbackError,match='feedback_quota'):
                feedback.capture(conn,cfg,query='Synthetic evidence',domain='beta',project='/projects/a',idempotency_key=key())


def test_storage_signal_history_and_comment_caps(owned,monkeypatch):
    from agentic_rag import feedback
    event=capture(owned)['event']
    with pytest.raises(ValueError):
        call(owned,'submit',event_id=event['id'],kind='useful',comment='a'*1001,idempotency_key=key())
    monkeypatch.setattr(feedback,'MAX_BYTES',1)
    with pytest.raises(feedback.FeedbackError,match='feedback_quota'):
        call(owned,'submit',event_id=event['id'],kind='useful',idempotency_key=key())
    monkeypatch.setattr(feedback,'MAX_BYTES',16*1024**2)
    monkeypatch.setattr(feedback,'MAX_SIGNALS',1)
    with pytest.raises(feedback.FeedbackError,match='feedback_quota'):
        call(owned,'submit',event_id=event['id'],kind='useful',idempotency_key=key())
    monkeypatch.setattr(feedback,'MAX_SIGNALS',2048)
    signal=call(owned,'submit',event_id=event['id'],kind='useful',idempotency_key=key())
    monkeypatch.setattr(feedback,'MAX_REVISIONS',1)
    with pytest.raises(feedback.FeedbackError,match='feedback_revision_limit'):
        call(owned,'retract',feedback_id=signal['id'],expected_revision=1)


def test_feedback_version_detects_legacy_title_and_body_changes(owned):
    from agentic_rag import feedback,store
    cfg,_=owned
    with db.connect(cfg) as conn:
        saved=store.save_document(conn,cfg,title='Legacy plain feedback memory',body='Original legacy body',
                                  domain='alpha',project='/projects/a',dtype='memory')
    event=capture(owned)['event']
    args=dict(event_id=event['id'],kind='missing_evidence',expected_id=saved.doc_id,idempotency_key=key())
    signal=call(owned,'submit',**args)
    with db.connect(cfg) as conn:
        first=feedback.document_snapshot(conn,saved.doc_id)
        store.save_document(conn,cfg,title='Changed legacy title',body='Rewritten legacy body',domain='alpha',
                            project='/projects/a',dtype='memory',doc_id=saved.doc_id)
        second=feedback.document_snapshot(conn,saved.doc_id)
    assert first['evidence_version']==second['evidence_version']
    assert first['version'].startswith('fb1:') and first['version']!=second['version']
    assert call(owned,'submit',**args)['id']==signal['id']
    assert call(owned,'get',feedback_id=signal['id'])['stale'] is True


def test_source_snapshot_bound_has_no_partial_capture(owned):
    from agentic_rag import feedback,store
    cfg,_=owned
    with db.connect(cfg) as conn:
        for start in (0,8,16):
            store.save_claim(conn,cfg,title='Many synthetic sources',body='Many synthetic sources bounded evidence',
                             domain='alpha',project='/projects/a',dtype='memory',claim_kind='stated',
                             evidence=[{'namespace':'synthetic-feedback-bound','source_id':str(i),'role':'user',
                                        'quote':'Many synthetic sources bounded evidence','complete':True}
                                       for i in range(start,min(start+8,17))])
        before=conn.execute('SELECT count(*) n FROM retrieval_feedback_events').fetchone()['n']
    with pytest.raises(feedback.FeedbackError,match='feedback_snapshot_limit'):
        call(owned,'capture',query='Many synthetic sources',domain='alpha',project='/projects/a',idempotency_key=key())
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM retrieval_feedback_events').fetchone()['n']==before


@pytest.mark.parametrize('when,expiry',[('2019-01-01T00:00:00+00:00','2020-01-01T00:00:00+00:00'),
                                      ('2099-01-01T00:00:00+00:00',None)])
def test_expected_assertion_must_be_currently_eligible(owned,when,expiry):
    from agentic_rag import feedback,store
    cfg,_=owned
    with db.connect(cfg) as conn:
        saved=store.save_assertion(conn,cfg,entity='Synthetic machine '+when,attribute='state',value='ready',
            event_at=when,expires_at=expiry,evidence={'source_id':'synthetic-time-'+when,'role':'user','quote':'ready'},
            domain='alpha',project='/projects/a')
        snapshot=feedback.document_snapshot(conn,saved.doc_id)
        assert snapshot['eligible'] is False
    event=capture(owned)['event']
    signal=call(owned,'submit',event_id=event['id'],kind='missing_evidence',expected_id=saved.doc_id,idempotency_key=key())
    assert signal['stale'] is True


@pytest.mark.parametrize('grant',[
    'GRANT UPDATE(query_sha256) ON retrieval_feedback_events TO rag_writer',
    'GRANT UPDATE(comment) ON retrieval_feedback TO rag_reader',
    'GRANT UPDATE(bytes) ON retrieval_feedback_usage TO rag_reader',
])
def test_schema_refuses_mutating_column_grant_drift(owned,grant):
    from agentic_rag.service.schema import ServiceSchemaError,validate_schema
    cfg,_=owned
    with db.connect(cfg) as conn:
        conn.execute(grant)
        with pytest.raises(ServiceSchemaError):validate_schema(conn)
        conn.rollback()
