"""A populated upgrade must withdraw old misattribution without deleting data."""
import hashlib
import json

import pytest

from agentic_rag import cli, evidence, store
from agentic_rag.domains import seed_defaults


def recording(tmp_path):
    records = [
        {'uuid': 'human', 'type': 'user', 'timestamp': '2026-11-01T00:00:00Z',
         'message': {'role': 'user', 'content': 'Sensor mode is blue.'}},
        {'uuid': 'summary', 'type': 'user', 'isCompactSummary': True,
         'timestamp': '2026-11-01T00:01:00Z',
         'message': {'role': 'user', 'content': 'Sensor mode is red.'}},
    ]
    raw = [json.dumps(item).encode() + b'\n' for item in records]
    path = tmp_path / 'old-native.jsonl'
    path.write_bytes(b''.join(raw))
    return path, [
        {'namespace': 'session:old-native',
         'source_id': str(i) + ':' + hashlib.sha256(b''.join(raw[:i + 1])).hexdigest(),
         'role': 'user', 'timestamp': item['timestamp'],
         'quote': item['message']['content'], 'complete': True}
        for i, item in enumerate(records)
    ]


def command(path, output, *, apply=False, sha=None, stopped=True):
    args = ['service', 'source-origin', '--transcript', str(path),
            '--namespace', 'session:old-native', '--output', str(output)]
    if apply:
        args += ['--apply', '--expected-sha256', sha]
        if stopped:
            args += ['--writers-stopped']
    try:
        return cli.main(args)
    except SystemExit as exc:
        return exc.code


@pytest.fixture(autouse=True)
def setup(conn, monkeypatch):
    seed_defaults(conn)
    monkeypatch.setattr(store, 'try_embed_texts', lambda *a, **k: None)


def save(conn, cfg, source, title):
    return store.save_claim(conn, cfg, title=title, body=source['quote'],
                            domain='general', dtype='memory', project='/synthetic/origin',
                            claim_kind='stated', evidence=[source])


def test_upgrade_quarantines_existing_and_future_generated_evidence_only(
        conn, cfg, hook_env, tmp_path, capsys):
    path, sources = recording(tmp_path)
    original = save(conn, cfg, sources[0], 'Original blue')
    generated = save(conn, cfg, sources[1], 'Misattributed red')
    before = conn.execute('SELECT id,body,provenance FROM documents ORDER BY id').fetchall()
    assert conn.execute('SELECT claim_eligible(%s)', (generated.doc_id,)).fetchone()['claim_eligible']

    preview = tmp_path / 'preview.json'
    assert command(path, preview) == 0
    report = json.loads(preview.read_text())
    assert report['applied'] is False
    assert report['generated_sources'] == 1
    assert evidence.sources(conn, generated.doc_id)[0]['state'] == 'active'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert command(path, tmp_path / 'applied.json', apply=True, sha=digest) == 0

    assert evidence.sources(conn, original.doc_id)[0]['state'] == 'active'
    assert evidence.sources(conn, generated.doc_id)[0]['state'] == 'removed'
    assert not conn.execute('SELECT claim_eligible(%s)', (generated.doc_id,)).fetchone()['claim_eligible']
    assert conn.execute('SELECT id,body,provenance FROM documents ORDER BY id').fetchall() == before
    audits = conn.execute("SELECT count(*) n FROM audit_log WHERE op='source_state'").fetchone()['n']
    assert audits == 1
    assert command(path, tmp_path / 'retry.json', apply=True, sha=digest) == 0
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE op='source_state'").fetchone()['n'] == audits
    capsys.readouterr()


def test_upgrade_tombstone_prevents_pending_legacy_batch_from_reactivating_source(
        conn, cfg, hook_env, tmp_path):
    path, sources = recording(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert command(path, tmp_path / 'apply.json', apply=True, sha=digest) == 0
    # This is what an already accepted 0.6.20 extraction batch later does.
    # The gateway must preserve the quarantined source's trust on attachment.
    later = save(conn, cfg, sources[1], 'Retried old extraction')
    assert evidence.sources(conn, later.doc_id)[0]['state'] == 'removed'
    assert not conn.execute('SELECT claim_eligible(%s)', (later.doc_id,)).fetchone()['claim_eligible']


def test_origin_apply_requires_exact_recording_and_stopped_writers(
        conn, hook_env, tmp_path):
    path, _ = recording(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for sha, stopped in [('0' * 64, True), (digest, False)]:
        assert command(path, tmp_path / (sha + str(stopped) + '.json'),
                       apply=True, sha=sha, stopped=stopped) != 0
    assert conn.execute('SELECT count(*) n FROM knowledge_sources').fetchone()['n'] == 0


@pytest.mark.parametrize('has_original', [True, False])
def test_old_staged_window_never_sends_quarantined_prose_to_provider(
        conn, cfg, hook_env, tmp_path, monkeypatch, has_original):
    from agentic_rag import mining
    from agentic_rag.mining_window import MiningWindow
    path, sources = recording(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert command(path, tmp_path / 'quarantine.json', apply=True, sha=digest) == 0
    selected = sources if has_original else sources[1:]
    events = tuple({'source_id': s['source_id'], 'role': 'user',
                    'text': '[user] ' + s['quote'], 'timestamp': s['timestamp'],
                    'offset': 0, 'complete': True} for s in selected)
    window = MiningWindow('\n'.join(e['text'] for e in events), 'old-window-end', events=events)
    prompts = []
    monkeypatch.setattr(mining, 'run_structured', lambda prompt, *a, **k: prompts.append(prompt) or {})
    result = mining.mine_session(conn, cfg, session_id='old-native', transcript_path='',
                                 last_uuid=None, project='/synthetic/origin', provided_window=window)
    assert result.new_last_uuid == 'old-window-end'
    if has_original:
        assert len(prompts) == 1
        assert 'Sensor mode is blue.' in prompts[0]
        assert 'Sensor mode is red.' not in prompts[0]
    else:
        assert prompts == []


def test_failed_quarantine_audit_rolls_back_even_new_source_tombstones(
        conn, cfg, tmp_path, monkeypatch):
    from agentic_rag.source_origin import audit
    path, _ = recording(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(evidence, '_audit', fail)
    with pytest.raises(RuntimeError, match='synthetic audit failure'):
        audit(cfg, path, 'session:old-native', apply=True, writers_stopped=True,
              expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert conn.execute('SELECT count(*) n FROM knowledge_sources').fetchone()['n'] == 0
    assert conn.execute('SELECT count(*) n FROM source_history').fetchone()['n'] == 0


def test_scoped_old_writer_cannot_reactivate_removed_service_source(
        conn, cfg, tmp_path):
    from agentic_rag import db
    from agentic_rag.service.auth import Principal
    from agentic_rag.service.context import request_scope
    from agentic_rag.source_origin import audit
    principal = Principal('alice', 'vm1', 'one', frozenset({'general'}), frozenset({'general'}),
                          frozenset({'/synthetic/origin'}), frozenset({'/synthetic/origin'}),
                          credential_revision='synthetic-known-revision')
    path, sources = recording(tmp_path)
    namespace = principal.session_id('old-native')
    sources[1]['namespace'] = namespace
    audit(cfg, path, namespace, apply=True, writers_stopped=True,
          expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    with request_scope(principal, cfg), db.connect(cfg, role='writer') as scoped:
        later = save(scoped, cfg, sources[1], 'Scoped legacy retry')
    assert evidence.sources(conn, later.doc_id)[0]['state'] == 'removed'
    assert not conn.execute('SELECT claim_eligible(%s)', (later.doc_id,)).fetchone()['claim_eligible']


def test_origin_reader_refuses_nonregular_and_incomplete_recordings(tmp_path):
    import os
    from agentic_rag.source_origin import scan
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match='regular_recording'):
        scan(fifo)
    incomplete = tmp_path / 'incomplete'
    incomplete.write_bytes(b'{"type":"user"}')
    with pytest.raises(ValueError, match='incomplete_recording'):
        scan(incomplete)
