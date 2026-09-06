import io
import json
from dataclasses import replace
import pytest
from agentic_rag import context, context_gate, db, evidence, pins, profiles, store
from agentic_rag.domains import seed_defaults
from agentic_rag.hooks import prompt_recall, session_start

PROJECT='/synthetic/context-a'

@pytest.fixture(autouse=True)
def setup(conn,monkeypatch):
    seed_defaults(conn)
    conn.execute('DELETE FROM project_profiles');conn.commit()
    monkeypatch.setattr(store,'try_embed_texts',lambda *a:None)
    monkeypatch.setattr(session_start.common,'spawn_worker',lambda:None)


def put(conn,cfg,body='We always run python -m pytest for tests.',project=PROJECT):
    return store.save_claim(conn,cfg,title='Testing convention',body=body,domain='general',dtype='memory',project=project,claim_kind='stated',
        evidence=[{'namespace':'synthetic','source_id':body,'role':'user','quote':body,'complete':True}])


def test_query_context_without_error_and_negative_gate(conn,cfg):
    doc=put(conn,cfg);put(conn,cfg,'We always use foreign-marker for tests.','/synthetic/context-b')
    result=context.build(conn,cfg,project=PROJECT,mode='prompt',prompt='How do we run tests in this project?')
    assert 'python -m pytest' in result['text'] and 'foreign-marker' not in result['text']
    assert doc.doc_id in result['document_ids']
    assert context.build(conn,cfg,project=PROJECT,mode='prompt',prompt='What is the weather?')['text']==''
    assert context.build(conn,cfg,project=PROJECT,mode='prompt',prompt='How is the weather in this project?')['text']==''


def test_startup_exact_pin_checkpoint_and_advisory_sources(conn,cfg):
    from agentic_rag.continuity import store as continuity
    from agentic_rag.continuity.model import CheckpointSnapshot
    doc=put(conn,cfg);store.refresh_profile(conn,cfg,PROJECT)
    body='Keep exact pin lines.\nNever remove this condition.'
    pins.add_pin(conn,body=body)
    snapshot=continuity.upsert_snapshot(conn,CheckpointSnapshot(session_id='s',turn_id='t',cursor='c',source='PreCompact',trigger='auto',cwd=PROJECT,project_root=PROJECT))
    continuity.apply_enrichment(conn,snapshot.id,{'goal':'Finish the context feature','next_action':'Verify its tests'})
    result=context.build(conn,cfg,project=PROJECT,session_id='s',source='compact')
    assert body in result['text'] and 'Finish the context feature' in result['text']
    assert 'advisory' in result['text'].lower() and 'python -m pytest' in result['text']
    assert evidence.sources(conn,doc.doc_id)[0]['source_key'] in result['text']
    assert len(result['text'])<=cfg.context_max_chars


def test_profile_not_injected_cannot_deduplicate_query(conn,cfg):
    doc=put(conn,cfg)
    store.refresh_profile(conn,cfg,PROJECT)
    result=context.build(conn,replace(cfg,context_max_chars=1000),project=PROJECT,mode='prompt',prompt='How do we run tests in this project?')
    assert 'python -m pytest' in result['text']
    assert result['text'].count('python -m pytest')==1
    assert doc.doc_id in result['document_ids'] and len(result['text'])<=1000


def test_profile_failure_and_tight_budget_preserve_whole_multiline_pins(conn,cfg,monkeypatch):
    first='Mandatory exact instruction.'
    second='A'*700+'\n'+'B'*700
    pins.add_pin(conn,body=first);pins.add_pin(conn,body=second)
    monkeypatch.setattr(profiles,'read',lambda *a:(_ for _ in ()).throw(RuntimeError('refresh path failed')))
    result=context.build(conn,replace(cfg,context_max_chars=1000),project=PROJECT)
    assert first in result['text']
    assert 'A'*100 not in result['text'] and 'B'*100 not in result['text']
    assert 'cut' in result['text'] and 'profile' in result['text'].lower()
    assert len(result['text'])<=1000
    assert [p.body for p in pins.matching_pins(conn,PROJECT)]==[first,second]


def test_real_turn_replay_later_identical_text_and_correction(conn,cfg,hook_env,monkeypatch):
    monkeypatch.setattr(prompt_recall,'load_config',lambda:cfg)
    doc=put(conn,cfg)
    payload={'session_id':'s','turn_id':'t1','cwd':PROJECT,'prompt':'How do we run tests in this project?'}
    def run(p):
        out=io.StringIO();prompt_recall.run(p,out);return out.getvalue()
    assert 'pytest' in run(payload)
    assert run(payload)==''
    assert 'pytest' in run({**payload,'turn_id':'t2'})
    store.set_source_state(conn,evidence.sources(conn,doc.doc_id)[0]['source_key'],state='removed',reason='corrected')
    put(conn,cfg,'We always run uv run pytest for tests.')
    assert 'uv run pytest' in run(payload)
    assert run({k:v for k,v in payload.items() if k!='turn_id'})
    assert run({k:v for k,v in payload.items() if k!='turn_id'})


def test_failed_emit_does_not_record_receipt(conn,cfg,hook_env,monkeypatch):
    put(conn,cfg);monkeypatch.setattr(prompt_recall,'load_config',lambda:cfg)
    payload={'session_id':'s','turn_id':'t','cwd':PROJECT,'prompt':'How do we run tests in this project?'}
    original=prompt_recall.common.emit_context
    monkeypatch.setattr(prompt_recall.common,'emit_context',lambda *a:(_ for _ in ()).throw(OSError('closed pipe')))
    prompt_recall.run(payload,io.StringIO())
    assert not list(context_gate.RECEIPT_DIR.glob('*.receipt'))
    monkeypatch.setattr(prompt_recall.common,'emit_context',original)
    out=io.StringIO();prompt_recall.run(payload,out);assert out.getvalue()


def test_local_cli_mcp_context_are_reader_interfaces(conn,cfg,hook_env,capsys,monkeypatch):
    from agentic_rag import cli,mcp_server
    put(conn,cfg)
    monkeypatch.setattr(cli,'load_config',lambda:cfg);monkeypatch.setattr(mcp_server,'load_config',lambda:cfg)
    assert cli.main(['context','--project',PROJECT,'--prompt','How do we run tests in this project?','--json'])==0
    assert 'pytest' in json.loads(capsys.readouterr().out)['text']
    monkeypatch.setenv('RAG_READONLY','1')
    assert 'memory_context' in mcp_server.tool_names(True)
    assert 'pytest' in mcp_server.memory_context(project=PROJECT,prompt='How do we run tests in this project?')['text']


def test_architecture_startup_queue_worker_reader_and_turn_delivery(conn,cfg,hook_env,monkeypatch):
    from agentic_rag import jobs,mcp_server,worker
    put(conn,cfg)
    pin='Keep the exact rule.\nInclude its condition.'
    pins.add_pin(conn,body=pin)
    monkeypatch.setattr(session_start,'load_config',lambda:cfg)
    monkeypatch.setattr(prompt_recall,'load_config',lambda:cfg)
    monkeypatch.setattr(mcp_server,'load_config',lambda:cfg)
    out=io.StringIO();session_start.run({'cwd':PROJECT,'session_id':'startup','source':'startup'},out)
    initial=json.loads(out.getvalue())['hookSpecificOutput']['additionalContext']
    assert pin in initial and 'profile' in initial.lower()
    jobs=conn.execute("SELECT * FROM mining_queue WHERE kind='profile_refresh' AND status='pending'").fetchall()
    assert len(jobs)==1
    worker.process_job(conn,cfg,dict(jobs[0]))
    result=mcp_server.memory_context(project=PROJECT)
    assert result['profile_status']=='fresh' and 'python -m pytest' in result['text'] and pin in result['text']
    payload={'cwd':PROJECT,'session_id':'startup','turn_id':'one','prompt':'How do we run tests in this project?'}
    def emit(p):
        out=io.StringIO();prompt_recall.run(p,out);return out.getvalue()
    assert emit(payload) and not emit(payload)
    assert emit({**payload,'turn_id':'two'})


def test_architecture_failed_worker_refresh_keeps_dated_revalidated_view(conn,cfg,hook_env,monkeypatch):
    from agentic_rag import worker
    old=put(conn,cfg,'We always use old-command for tests.')
    valid=put(conn,cfg,'We always prefer separate backups.')
    pin='Preserve exact recovery rule.\nIts condition stays attached.'
    pins.add_pin(conn,body=pin)
    store.refresh_profile(conn,cfg,PROJECT)
    before=dict(conn.execute('SELECT * FROM project_profiles').fetchone())
    store.set_source_state(conn,evidence.sources(conn,old.doc_id)[0]['source_key'],state='refuted',reason='replaced')
    new=put(conn,cfg,'We always use new-command for tests.')
    monkeypatch.setattr(session_start,'load_config',lambda:cfg)
    out=io.StringIO();session_start.run({'cwd':PROJECT,'session_id':'recovery','source':'startup'},out)
    job=conn.execute("SELECT * FROM mining_queue WHERE kind='profile_refresh' AND status='pending'").fetchone()
    assert job
    original=profiles._audit
    monkeypatch.setattr(profiles,'_audit',lambda *a:(_ for _ in ()).throw(RuntimeError('synthetic failure after cache write')))
    with pytest.raises(RuntimeError):worker.process_job(conn,cfg,dict(job))
    assert dict(conn.execute('SELECT * FROM project_profiles').fetchone())==before
    with db.connect(cfg,role='reader') as reader:
        result=context.build(reader,cfg,project=PROJECT)
    assert 'old-command' not in result['text'] and 'separate backups' in result['text']
    assert pin in result['text'] and 'stale' in result['text'] and str(before['generated_at'].date()) in result['text']
    monkeypatch.setattr(profiles,'_audit',original)
    worker.process_job(conn,cfg,dict(job))
    with db.connect(cfg,role='reader') as reader:
        result=context.build(reader,cfg,project=PROJECT)
    assert result['profile_status']=='fresh' and 'new-command' in result['text']


def test_render_failure_still_schedules_missing_profile(conn,cfg,hook_env,monkeypatch):
    put(conn,cfg)
    monkeypatch.setattr(session_start,'load_config',lambda:cfg)
    monkeypatch.setattr(context,'build',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('synthetic renderer failure')))
    out=io.StringIO();session_start.run({'cwd':PROJECT,'session_id':'broken-render','source':'startup'},out)
    assert 'unavailable' in out.getvalue() and 'synthetic renderer failure' in out.getvalue()
    assert conn.execute("SELECT count(*) n FROM mining_queue WHERE kind='profile_refresh' AND status='pending'").fetchone()['n']==1
