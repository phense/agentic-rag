"""Review2 regressions for immutable credentials and recoverable pressure."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentic_rag import db, mining, store, worker
from agentic_rag.service.auth import Policy, hash_key, AuthenticationError
from agentic_rag.service.context import request_scope
from agentic_rag.service.engine import ServiceError
from agentic_rag.service.ingest import accept
from agentic_rag.service.resources import admission
from agentic_rag.service.worker import process_embed, JobBlocked
from .test_worker_fencing import owned, window

TOKEN='review.synthetic-key-for-isolated-probe'


def queued_embedding(cfg,principal):
    with request_scope(principal,cfg),db.connect(cfg,role='writer') as conn:
        saved=store.save_document(conn,cfg,title='Deferred port',body='Port is 9000',domain='alpha',dtype='memory',project='/projects/a')
    with db.connect(cfg) as conn:
        return dict(conn.execute("SELECT * FROM mining_queue WHERE kind='embed' AND payload->>'document_id'=%s",(saved.doc_id,)).fetchone())


@pytest.mark.parametrize('when',['during_save','after_save'])
def test_rotated_key_does_not_adopt_new_credential_for_deferred_embedding(owned,monkeypatch,when):
    cfg,policy=owned;principal=policy.authenticate_key(TOKEN)
    def rotate(*a,**k):
        cfg.service_auth_file.write_text(cfg.service_auth_file.read_text().replace(hash_key(TOKEN),hash_key('review.replacement-unrelated-secret')))
        return None
    if when=='during_save':
        monkeypatch.setattr(store,'try_embed_texts',rotate)
        with pytest.raises(JobBlocked,match='authorization_changed'):
            queued_embedding(cfg,principal)
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==0
            assert conn.execute('SELECT count(*) n FROM mining_queue').fetchone()['n']==0
    else:
        # A previously committed job must retain the original credential revision
        # and be blocked after rotation, independently of synchronous rollback.
        job=queued_embedding(cfg,principal)
        rotate()
        assert job['payload']['_principal']['revision']==hash_key(TOKEN)
        monkeypatch.setattr(store,'embed_texts',lambda *a,**k:pytest.fail('revoked origin reached inference'))
        with pytest.raises(JobBlocked):process_embed(cfg,job['payload'])
        with db.connect(cfg) as conn:
            assert conn.execute('SELECT count(*) n FROM chunks WHERE embedding IS NOT NULL').fetchone()['n']==0
            assert conn.execute('SELECT count(*) n FROM documents').fetchone()['n']==1
    with pytest.raises(AuthenticationError):Policy.load(cfg.service_auth_file).authenticate_key(TOKEN)


@pytest.mark.parametrize('pressure,when',[('database','before_inference'),('disk','before_inference'),('disk','before_commit')])
def test_deferred_embedding_obeys_storage_limits_and_rolls_back(owned,monkeypatch,when,pressure):
    from agentic_rag.service import resources
    cfg,policy=owned;job=queued_embedding(cfg,policy.authenticate_key(TOKEN));active={'pressure':when=='before_inference'}
    original=resources.shutil.disk_usage
    if pressure=='database' and when=='before_inference':cfg=replace(cfg,service_max_database_bytes=1)
    else:
        monkeypatch.setattr(resources.shutil,'disk_usage',lambda path:SimpleNamespace(free=0) if active['pressure'] else original(path))
    def vectors(texts,*a,**k):
        assert when=='before_commit','pressure must stop inference'
        active['pressure']=True
        return [[.01]*1024 for _ in texts]
    monkeypatch.setattr(store,'embed_texts',vectors)
    with pytest.raises(ServiceError) as exc:process_embed(cfg,job['payload'])
    assert exc.value.status==507
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM chunks WHERE embedding IS NOT NULL').fetchone()['n']==0
        assert conn.execute("SELECT status FROM mining_queue WHERE id=%s",(job['id'],)).fetchone()['status']=='pending'


def test_repeated_write_contention_keeps_accepted_batch_retryable(owned,monkeypatch):
    cfg,policy=owned;cfg=replace(cfg,worker_backoff_seconds=0)
    p=policy.authenticate_key(TOKEN);receipt=accept(cfg,p,policy,window())['receipt'];calls=[]
    monkeypatch.setattr(mining,'run_structured',lambda *a,**k:calls.append(1) or {})
    with admission(cfg):
        with db.connect(cfg) as conn:
            for _ in range(4):
                worker.drain(conn,cfg,max_jobs=1)
                row=conn.execute('SELECT q.id,q.status,q.attempts FROM mining_queue q JOIN service_windows w ON w.queue_id=q.id WHERE w.id=%s',(receipt,)).fetchone()
                assert row['status']=='pending' and row['attempts']==0,row
                conn.execute('UPDATE mining_queue SET next_attempt_at=now() WHERE id=%s',(row['id'],));conn.commit()
    with db.connect(cfg) as conn:
        assert worker.drain(conn,cfg,max_jobs=1)['done']==1
        assert conn.execute('SELECT state FROM service_windows WHERE id=%s',(receipt,)).fetchone()['state']=='applied'
    assert calls==[1]
