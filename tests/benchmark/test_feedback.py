"""Private feedback approval/export/evaluation on owned PostgreSQL, no providers."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from agentic_rag import db,feedback,store,query_cache
from agentic_rag.benchmark.database import isolated_database
from agentic_rag.config import Config
from agentic_rag.service.auth import Principal
from agentic_rag.service.context import request_scope


def key():return str(uuid.uuid4())


def actor(user='alice',machine='vm1'):
    return Principal(user,machine,'synthetic',frozenset({'alpha'}),frozenset({'alpha'}),
                     frozenset({'/projects/a'}),frozenset({'/projects/a'}))


@pytest.fixture
def private_store(monkeypatch):
    monkeypatch.setattr(store,'try_embed_texts',lambda *a,**k:None)
    monkeypatch.setattr(query_cache,'model_digest',lambda cfg:None)
    with isolated_database(Config(feedback_enabled=True)) as cfg:
        with db.connect(cfg) as conn:
            conn.execute("INSERT INTO domains(name) VALUES ('alpha')")
            conn.commit()
            targets=[]
            for label in ('a','b','c','d','e','f'):
                body='Grounded synthetic target '+label
                targets.append(store.save_claim(conn,cfg,title=body,body=body,domain='alpha',project='/projects/a',
                    dtype='memory',claim_kind='stated',evidence=[{'namespace':'feedback71-private','source_id':label,
                        'role':'user','quote':body,'complete':True}]).doc_id)
        yield cfg,targets


def signal(private_store,*,query='absent lexical selector',expected=None,user='alice',machine='vm1',kind='missing_evidence'):
    cfg,targets=private_store
    with request_scope(actor(user,machine),cfg):
        with db.connect(cfg,role='writer') as conn:
            event=feedback.capture(conn,cfg,query=query,domain='alpha',project='/projects/a',idempotency_key=key())
            record=feedback.submit(conn,cfg,event_id=event['event']['id'],kind=kind,expected_id=expected or targets[0],
                                   idempotency_key=key(),comment='password=syntheticsecretvalue')
    return event,record


def canonical_rows(cfg):
    with db.connect(cfg) as conn:
        tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                if not r['tablename'].startswith('retrieval_feedback') and r['tablename'] not in ('audit_log','schema_migrations','benchmark_ownership')]
        return {t:conn.execute(f'SELECT to_jsonb(t) row FROM "{t}" t ORDER BY to_jsonb(t)::text').fetchall() for t in tables}


def test_local_operator_approval_cli_is_executable(private_store,tmp_path):
    # Mutation caught: operator route missing, foreign runtime adapter or no version binding.
    cfg,_=private_store
    _,record=signal(private_store)
    config=tmp_path/'config.toml'
    config.write_text(f'[db]\nname="{cfg.db_name}"\nhost="{cfg.db_host}"\n[feedback]\nenabled=true\n')
    result=subprocess.run([sys.executable,'-m','agentic_rag.cli','feedback','approve',record['id'],
        '--expected-revision','1','--query','absent lexical selector'],capture_output=True,text=True,
        env={**os.environ,'AGENTIC_RAG_CONFIG':str(config)},timeout=15)
    assert result.returncode==0,result.stderr
    approved=json.loads(result.stdout)
    assert approved['feedback_id']==record['id'] and approved['revision']==1
    assert approved['expected_version'].startswith('fb1:')


def test_private_export_and_evaluation_preserve_all_canonical_tables(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private,corrections
    cfg,targets=private_store
    before=canonical_rows(cfg)
    records=[]
    for i,target in enumerate(targets):
        _,record=signal(private_store,expected=target,kind='wrong_source' if i%2 else 'missing_evidence')
        private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
        records.append(record)
    export=tmp_path/'labels.json';report=tmp_path/'report.json'
    count=private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=export)
    assert count['exported']==6 and count['selected']==6 and count['withheld']==0
    payload=json.loads(export.read_text())
    assert payload['kind']=='private-retrieval-feedback' and {c['split'] for c in payload['cases']}=={'dev','test'}
    assert 'password=' not in export.read_text() and 'comment' not in export.read_text()
    assert all(not c['baseline_hit'] for c in payload['cases'])
    result=corrections.evaluate_export(cfg,export_path=export,output_path=report)
    assert result['selected']==6 and result['evaluated']==6 and result['current_misses']==6
    assert result['reproduced_failures']==6 and result['stale']==0 and result['withheld']==0
    assert result['provider_calls']==0 and result['application_writes']==0
    assert sum(result['by_split'][s]['evaluated'] for s in ('dev','test'))==6
    print('PRIVATE_FEEDBACK_EXAMPLE',json.dumps(result,sort_keys=True))
    assert canonical_rows(cfg)==before
    assert export.stat().st_mode&0o777==0o600 and report.stat().st_mode&0o777==0o600
    assert not Path(str(report)+'.candidate.json').exists()


def test_actor_independence_and_copied_source_families(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private
    cfg,targets=private_store
    for user,machine in [('alice','vm1'),('alice','vm2'),('bob','vm3')]:
        signal(private_store,user=user,machine=machine)
    summary=private.summary(cfg,domain='alpha',project='/projects/a')
    assert summary['signals']==3 and summary['independent_signals']==2 and summary['source_families']==1
    with db.connect(cfg) as conn:
        pair=[]
        for label in ('copied-a','copied-b'):
            pair.append(store.save_claim(conn,cfg,title=label,body='Shared synthetic span '+label,domain='alpha',
                project='/projects/a',dtype='memory',claim_kind='stated',evidence=[{'namespace':'private-copied',
                'source_id':label,'role':'user','quote':'Shared synthetic span','complete':True}]).doc_id)
    for expected in pair:
        _,record=signal(private_store,expected=expected)
        private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    export=tmp_path/'copied.json'
    private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=export)
    cases=json.loads(export.read_text())['cases']
    assert len(cases)==2 and len({c['split_family'] for c in cases})==1 and len({c['split'] for c in cases})==1


@pytest.mark.parametrize('context',['request','fence','readonly','client'])
def test_operator_context_refusals_happen_before_database(context,monkeypatch):
    from agentic_rag.benchmark import feedback as private
    from agentic_rag.service.context import CURRENT,RequestScope
    from agentic_rag.service.fence import LEASE
    cfg=Config(service_mode='client' if context=='client' else 'standalone')
    token=None
    if context=='request':token=CURRENT.set(RequestScope(actor(),cfg))
    if context=='fence':token=LEASE.set(object())
    if context=='readonly':monkeypatch.setenv('RAG_READONLY','1')
    monkeypatch.setattr(db,'connect',lambda *a,**k:pytest.fail('unauthorized operator context opened database'))
    try:
        with pytest.raises(ValueError,match='operator_local'):
            private.approve(cfg,feedback_id=key(),expected_revision=1,query='safe')
    finally:
        if context=='request':CURRENT.reset(token)
        if context=='fence':LEASE.reset(token)


def test_approval_hash_secrets_retraction_and_source_changes(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private,corrections
    cfg,targets=private_store
    _,record=signal(private_store)
    with pytest.raises(ValueError):private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='different query')
    _,secret=signal(private_store,query='password=syntheticsecretvalue')
    with pytest.raises(ValueError):private.approve(cfg,feedback_id=secret['id'],expected_revision=1,query='password=syntheticsecretvalue')
    private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    export=tmp_path/'before.json'
    private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=export)
    with request_scope(actor(),cfg):
        with db.connect(cfg,role='writer') as conn:feedback.retract(conn,cfg,feedback_id=record['id'],expected_revision=1)
    result=corrections.evaluate_export(cfg,export_path=export,output_path=tmp_path/'after-retract.json')
    assert result['stale']==1 and result['evaluated']==0 and result['reproduced_failures']==0
    with db.connect(cfg) as conn:
        source=conn.execute('SELECT source_key FROM claim_evidence WHERE document_id=%s',(targets[0],)).fetchone()['source_key']
        store.set_source_state(conn,source,state='removed',reason='Synthetic withdrawal')
    with pytest.raises(ValueError):private.approve(cfg,feedback_id=secret['id'],expected_revision=1,query='password=syntheticsecretvalue')
    count=private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=tmp_path/'withdrawn.json')
    assert count['exported']==0 and count['selected']==2


def test_legacy_body_rewrite_invalidates_current_approval(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private,corrections
    cfg,_=private_store
    with db.connect(cfg) as conn:
        plain=store.save_document(conn,cfg,title='Legacy expected',body='Original plain legacy source',domain='alpha',
                                  project='/projects/a',dtype='memory')
    _,record=signal(private_store,expected=plain.doc_id)
    private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    export=tmp_path/'before.json';private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=export)
    with db.connect(cfg) as conn:
        store.save_document(conn,cfg,title='Changed legacy expected',body='Changed plain legacy source',domain='alpha',
                            project='/projects/a',dtype='memory',doc_id=plain.doc_id)
    result=corrections.evaluate_export(cfg,export_path=export,output_path=tmp_path/'stale.json')
    assert result['stale']==1 and result['evaluated']==0 and result['reproduced_failures']==0
    assert private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=tmp_path/'new.json')['exported']==0


def test_tampering_private_paths_and_old_correction_format(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private,corrections
    cfg,_=private_store
    _,record=signal(private_store)
    private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    export=tmp_path/'sealed.json';private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=export)
    data=json.loads(export.read_text());data['cases'][0]['query']='tampered query';export.write_text(json.dumps(data))
    with pytest.raises(ValueError):corrections.evaluate_export(cfg,export_path=export,output_path=tmp_path/'no.json')
    assert not (tmp_path/'no.json').exists()
    with pytest.raises(ValueError):private.export_feedback(cfg,domain='alpha',project='/projects/a',output_path=Path.cwd()/'private-feedback-forbidden.json')
    with pytest.raises(ValueError):corrections._validate_export({'kind':'private-retrieval-feedback','version':1,'synthetic':False})



def test_approval_is_private_audited_and_rollback_atomic(private_store,monkeypatch):
    import psycopg
    from agentic_rag.benchmark import feedback as private
    cfg,_=private_store
    _,record=signal(private_store)
    with db.connect(cfg) as conn:
        before=conn.execute('SELECT * FROM retrieval_feedback_usage').fetchall()
    original=feedback._audit
    def fail(*args):raise RuntimeError('synthetic approval audit fault')
    monkeypatch.setattr(feedback,'_audit',fail)
    with pytest.raises(RuntimeError,match='synthetic approval audit fault'):
        private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT * FROM retrieval_feedback_approvals').fetchall()==[]
        assert conn.execute('SELECT * FROM retrieval_feedback_usage').fetchall()==before
    monkeypatch.setattr(feedback,'_audit',original)
    private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    for role in ('reader','writer','admin'):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.connect(cfg,role=role) as conn:conn.execute('SELECT query FROM retrieval_feedback_approvals')
    with request_scope(actor(),cfg):
        with db.connect(cfg,role='reader') as conn:
            public=json.dumps([feedback.get(conn,cfg,feedback_id=record['id']),feedback.list_feedback(conn,cfg)])
            assert 'absent lexical selector' not in public


@pytest.mark.parametrize('name',[
    'test_original_confirmed_correction_is_exported_and_locally_supported',
    'test_frozen_export_counts_withdrawn_label_as_miss_without_provider',
    'test_complete_family_bound_withholds_instead_of_truncating',
    'test_current_schema_correction_export_remains_read_only',
])
def test_existing_correction_behavior_on_owned_database(private_store,tmp_path,monkeypatch,name):
    # Reuse the original contract tests while keeping their shared cfg/conn
    # fixtures entirely unrequested. No agentic_rag_test database is touched.
    import inspect
    from tests.benchmark import test_corrections as old
    cfg,_=private_store
    with db.connect(cfg) as conn:
        values=dict(conn=conn,cfg=cfg,tmp_path=tmp_path,monkeypatch=monkeypatch)
        fn=getattr(old,name)
        fn(**{key:values[key] for key in inspect.signature(fn).parameters})


def test_existing_synthesis_source_version_gate_on_owned_database(private_store):
    from test_synthesis_policy import test_migration_creates_empty_policy_storage_and_upgrade_accepts_actual_0_6_17
    cfg,_=private_store
    with db.connect(cfg) as conn:
        test_migration_creates_empty_policy_storage_and_upgrade_accepts_actual_0_6_17(conn)


def test_disabled_blocks_approval_but_retains_private_read_workflows(private_store,tmp_path):
    from agentic_rag.benchmark import feedback as private,corrections
    cfg,_=private_store
    _,record=signal(private_store)
    private.approve(cfg,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    disabled=replace(cfg,feedback_enabled=False)
    with pytest.raises(ValueError,match='feedback_disabled'):
        private.approve(disabled,feedback_id=record['id'],expected_revision=1,query='absent lexical selector')
    assert private.summary(disabled,domain='alpha',project='/projects/a')['signals']==1
    path=tmp_path/'retained.json'
    assert private.export_feedback(disabled,domain='alpha',project='/projects/a',output_path=path)['exported']==1
    assert corrections.evaluate_export(disabled,export_path=path,output_path=tmp_path/'retained-result.json')['evaluated']==1
