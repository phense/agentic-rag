import json
import pytest
from agentic_rag.integrations.opencode import hooks
from agentic_rag.hooks import common
from agentic_rag.continuity import store
from agentic_rag.transcript import build_digest

def payload():
    return {'session_id':'ses_fixture','cwd':'/private/tmp/opencode-fixture','messages':[
        {'id':'msg_1','role':'user','text':'Remember the harmless fixture objective.'},
        {'id':'msg_2','role':'assistant','text':'Fixture complete.','tools':['bash']}]}

@pytest.fixture
def env(hook_env,tmp_path,monkeypatch):
    monkeypatch.setattr(hooks,'TRANSCRIPT_DIR',tmp_path.resolve()/'projection')
    monkeypatch.setattr(common,'spawn_worker',lambda:None)

def test_projection_private_sanitized_idempotent(env):
    p=payload();p['messages'][0]['text']='fixture sk-'+'a'*48
    first=hooks.project_transcript(p);hooks.project_transcript(p)
    rows=[json.loads(x) for x in first.read_text().splitlines()]
    assert len(rows)==2
    assert 'sk-'+'a'*48 not in first.read_text()
    assert first.stat().st_mode & 0o777 == 0o600
    assert build_digest(first).last_uuid=='opencode:msg_2'
    assert '[assistant tool: bash]' in build_digest(first).text

def test_projection_rejects_symlink(env,tmp_path):
    target=tmp_path/'foreign';target.mkdir()
    hooks.TRANSCRIPT_DIR.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError):hooks.project_transcript(payload())
    assert list(target.iterdir())==[]

def test_context_failure_visible_and_disable_nonwriting(env,monkeypatch):
    def fail(p):raise RuntimeError('test unavailable')
    monkeypatch.setattr(hooks,'startup_context',fail)
    out=hooks.dispatch('context',payload())
    assert not out['ok'] and 'unavailable' in out['context']
    monkeypatch.setenv('AGENTIC_RAG_HOOKS_DISABLE','1')
    assert hooks.dispatch('idle',payload())=={'ok':True}
    assert not hooks.TRANSCRIPT_DIR.exists()

def test_compaction_and_idle_shared_store(env,cfg):
    from agentic_rag import db
    p=payload()|{'boundary_id':'msg_compact','trigger':'manual'}
    before=hooks.dispatch('pre-compact',p)
    assert before['ok'],before
    assert hooks.dispatch('pre-compact',p)['checkpoint_id']==before['checkpoint_id']
    after=hooks.dispatch('post-compact',p|{'summary':'Fixture handoff: next action verify.'})
    assert after['ok'],after
    assert hooks.dispatch('idle',p)['ok']
    assert hooks.dispatch('idle',p)['ok']
    with db.connect(cfg,role='reader') as conn:
        checkpoint=store.matching_compaction(conn,'opencode:ses_fixture','msg_compact','manual')
        assert checkpoint.compacted_at is not None
        assert 'Fixture handoff' in checkpoint.handoff
        assert conn.execute("SELECT count(*) AS n FROM mining_queue WHERE kind='mine' AND session_id='opencode:ses_fixture'").fetchone()['n']==1

def test_foreign_compaction_does_not_attach_to_latest(env):
    p=payload()|{'boundary_id':'msg_first','trigger':'manual'}
    hooks.dispatch('pre-compact',p)
    assert not hooks.dispatch('post-compact',p|{'boundary_id':'msg_unrelated','summary':'Wrong summary'})['ok']

def test_two_compactions_keep_resolvable_delta_cursor(env,cfg):
    from agentic_rag import db
    first=payload()|{'session_id':'ses_delta','boundary_id':'msg_c1','trigger':'manual'}
    hooks.dispatch('pre-compact',first)
    second=first|{'boundary_id':'msg_c2','messages':[{'id':'msg_3','role':'user','text':'New delta only.'}]}
    result=hooks.dispatch('pre-compact',second)
    with db.connect(cfg,role='reader') as conn:
        cp=store.matching_compaction(conn,'opencode:ses_delta','msg_c2','manual')
        job=conn.execute("SELECT transcript_path,last_uuid FROM mining_queue WHERE kind='checkpoint_enrich' AND payload->>'checkpoint_id'=%s",(result['checkpoint_id'],)).fetchone()
        assert cp.predecessor_cursor==job['last_uuid']
        digest=build_digest(job['transcript_path'],after_uuid=job['last_uuid'])
        assert 'New delta only' in digest.text
        assert 'harmless fixture objective' not in digest.text
