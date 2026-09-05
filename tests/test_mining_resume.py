import json
from dataclasses import replace

import pytest

from agentic_rag import mining
from agentic_rag.config import Config


def event(identity, text):
    return {"uuid": identity, "message": {"role": "user", "content": text}}


def write_events(path, *events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return str(path)


def response(*bodies):
    return {"memories": [{"title": f"Fact {i}", "body": body,
                           "domain": "general", "edges": []}
                          for i, body in enumerate(bodies)],
            "lessons": [], "signals": [], "contradictions": [],
            "pin_suggestions": [], "contradictions_with_pins": [],
            "domain_proposals": []}


def setup(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('general')")
    conn.commit()
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


def test_mining_event_tail_is_eventually_consumed_once(conn, tmp_path, monkeypatch):
    # Mutation caught: advancing the cursor to EOF after truncating the digest.
    cfg = replace(setup(conn), mine_max_digest_chars=128, mine_per_block_chars=800)
    path = write_events(tmp_path / "session.jsonl", event("first", "A" * 200),
                        event("last", "TAIL_FACT_ONLY"))
    prompts = []

    def extract(prompt, *args, **kwargs):
        prompts.append(prompt)
        return response()

    monkeypatch.setattr(mining, "run_structured", extract)
    cursor = None
    for _ in range(10):
        result = mining.mine_session(conn, cfg, session_id="tail", transcript_path=path,
                                     last_uuid=cursor, project=None)
        if result.new_last_uuid == cursor:
            break
        cursor = result.new_last_uuid
    assert sum("TAIL_FACT_ONLY" in p for p in prompts) == 1


def test_accepted_extraction_survives_interrupted_application(conn, tmp_path, monkeypatch):
    # Mutation caught: document 1 commits independently, then a retry regenerates
    # different output and either duplicates or changes the accepted batch.
    cfg = setup(conn)
    path = write_events(tmp_path / "session.jsonl", event("one", "Two durable facts"))
    calls = []

    def extract(*args, **kwargs):
        calls.append(True)
        return response("accepted first", "accepted second") if len(calls) == 1 else response("changed retry")

    monkeypatch.setattr(mining, "run_structured", extract)
    real_save = mining.save_document
    saves = []

    def interrupted(*args, **kwargs):
        saved = real_save(*args, **kwargs)
        saves.append(saved)
        if len(saves) == 1:
            raise RuntimeError("simulated worker death after first write")
        return saved

    monkeypatch.setattr(mining, "save_document", interrupted)
    with pytest.raises(RuntimeError, match="simulated worker death"):
        mining.mine_session(conn, cfg, session_id="crash", transcript_path=path,
                            last_uuid=None, project=None)
    conn.rollback()
    assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0
    monkeypatch.setattr(mining, "save_document", real_save)
    mining.mine_session(conn, cfg, session_id="crash", transcript_path=path,
                        last_uuid=None, project=None)
    bodies = [r["body"] for r in conn.execute("SELECT body FROM documents ORDER BY body")]
    assert bodies == ["accepted first", "accepted second"]
    assert len(calls) == 1
    mining.mine_session(conn, cfg, session_id="crash", transcript_path=path,
                        last_uuid=None, project=None)
    assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 2
    assert len(calls) == 1


def test_worker_finishes_all_windows_without_spending_failure_budget(conn, tmp_path, monkeypatch):
    from agentic_rag import jobs, worker
    cfg = replace(setup(conn), mine_max_digest_chars=128,
                  mine_per_block_chars=70, mine_debounce_seconds=0)
    path = write_events(tmp_path / 'long.jsonl', event('first', 'A' * 350),
                        event('last', 'FINAL_FACT'))
    seen = []
    def extract(prompt, *args, **kwargs):
        seen.append(prompt)
        return response('final fact') if 'FINAL_FACT' in prompt else response()
    monkeypatch.setattr(mining, 'run_structured', extract)
    jobs.enqueue_mine(conn, cfg, session_id='worker-tail', transcript_path=path, project=None)
    worker.drain(conn, cfg, max_jobs=2)
    row = conn.execute("SELECT status, attempts FROM mining_queue WHERE kind='mine'").fetchone()
    assert row['status'] == 'pending'
    assert row['attempts'] == 0
    worker.drain(conn, cfg, max_jobs=20)
    row = conn.execute("SELECT status FROM mining_queue WHERE kind='mine'").fetchone()
    assert row['status'] == 'done'
    assert sum('FINAL_FACT' in p for p in seen) == 1
    assert conn.execute('SELECT body FROM documents').fetchone()['body'] == 'final fact'


def test_append_during_provider_call_is_not_lost(conn, tmp_path, monkeypatch):
    from agentic_rag import db, jobs, worker
    cfg = replace(setup(conn), mine_debounce_seconds=0)
    path = write_events(tmp_path / 'append.jsonl', event('first', 'initial'))
    seen = []
    def extract(prompt, *args, **kwargs):
        seen.append(prompt)
        if len(seen) == 1:
            with open(path, 'a') as stream:
                stream.write(json.dumps(event('last', 'ARRIVED_DURING_CALL')) + '\n')
            other = db.connect(cfg)
            try:
                assert not jobs.enqueue_mine(other, cfg, session_id='append', transcript_path=path, project=None)
            finally:
                other.close()
        return response()
    monkeypatch.setattr(mining, 'run_structured', extract)
    jobs.enqueue_mine(conn, cfg, session_id='append', transcript_path=path, project=None)
    worker.drain(conn, cfg, max_jobs=10)
    assert sum('ARRIVED_DURING_CALL' in p for p in seen) == 1
    assert conn.execute("SELECT status FROM mining_queue WHERE kind='mine'").fetchone()['status'] == 'done'


@pytest.mark.parametrize('death_after', [1, 2])
def test_actual_process_death_rolls_back_all_batch_effects(conn, tmp_path, death_after):
    import os
    import subprocess
    import sys
    cfg = setup(conn)
    path = write_events(tmp_path / 'kill.jsonl', event('first', 'two source facts'))
    # The model boundary is synthetic. PostgreSQL transactions and process death are real.
    program = '''
import json, os, sys
from agentic_rag import db, mining
from agentic_rag.config import Config
cfg=Config(db_name="agentic_rag_test",ollama_url="http://localhost:1")
c=db.connect(cfg,role="writer")
mining.run_structured=lambda *a,**k: json.loads(sys.argv[2])
real=mining.save_document
count=0
def save(*a,**k):
    global count
    result=real(*a,**k)
    count += 1
    if count == int(sys.argv[3]): os._exit(23)
    return result
mining.save_document=save
mining.mine_session(c,cfg,session_id="killed",transcript_path=sys.argv[1],last_uuid=None,project=None)
'''
    process = subprocess.run([sys.executable, '-c', program, path,
                              json.dumps(response('first accepted', 'second accepted')),
                              str(death_after)], cwd=os.getcwd(), capture_output=True, text=True)
    assert process.returncode == 23, process.stderr
    assert conn.execute('SELECT count(*) AS n FROM documents').fetchone()['n'] == 0
    assert conn.execute('SELECT count(*) AS n FROM mining_batches WHERE applied_at IS NULL').fetchone()['n'] == 1
    def forbidden(*a, **k):
        pytest.fail('retry must use durable accepted extraction')
    result = mining.mine_session(conn, cfg, session_id='killed', transcript_path=path,
                                 last_uuid=None, project=None, runner=forbidden)
    assert result.saved == 2
    assert [r['body'] for r in conn.execute('SELECT body FROM documents ORDER BY body')] == ['first accepted', 'second accepted']


def test_status_exposes_unapplied_batch_and_source_bounds(conn, tmp_path, monkeypatch):
    from agentic_rag.status import gather_status
    cfg = setup(conn)
    path = write_events(tmp_path / 'status.jsonl', event('one', 'fact'))
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: response('fact'))
    def fail(*a, **k):
        raise RuntimeError('unapplied')
    monkeypatch.setattr(mining, 'save_document', fail)
    with pytest.raises(RuntimeError, match='unapplied'):
        mining.mine_session(conn, cfg, session_id='status', transcript_path=path, last_uuid=None, project=None)
    status = gather_status(conn, cfg)
    assert getattr(status, 'pending_mining_batches', None) == 1
    assert status.mining_windows[0]['input_cursor'] == ''
    assert status.mining_windows[0]['output_cursor']
    assert 'extraction' not in status.mining_windows[0]


def test_every_accepted_effect_has_distinct_batch_item_provenance(conn, tmp_path, monkeypatch):
    cfg = setup(conn)
    path = write_events(tmp_path / 'effects.jsonl', event('one', 'evidence'))
    contradiction = {'slug':'missing', 'statement':'correction', 'quote':'evidence', 'domain':'general'}
    data = response()
    data.update(contradictions=[contradiction, contradiction],
                pin_suggestions=[{'body':'rule','scope':'global','reason':'requested'}],
                contradictions_with_pins=[{'pin':'rule','statement':'changed','quote':'evidence'}],
                domain_proposals=[{'name':'new','description':'new domain','reason':'requested'}])
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: data)
    result = mining.mine_session(conn,cfg,session_id='effects',transcript_path=path,last_uuid=None,project=None)
    identities = [r['provenance']['mining_item'] for r in conn.execute('SELECT provenance FROM documents')]
    assert sorted(identities) == ['contradiction:0','contradiction:1']
    rows = conn.execute("SELECT op,summary FROM audit_log WHERE op IN ('pin_suggestion','pin_contradiction','domain_proposal')").fetchall()
    assert len(rows) == 3
    for row in rows:
        assert result.batch_id in row['summary']
        assert row['op'] + ':0' in row['summary']
