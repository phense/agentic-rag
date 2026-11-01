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


@pytest.mark.parametrize('applied_before', [True, False])
def test_quarantined_replacement_never_suppresses_original_on_apply_or_replay(
        conn, cfg, tmp_path, monkeypatch, applied_before):
    # Missing eligibility in the newer-assertion SQL or accepting a removed
    # source on replay must both fail this real mining/gateway regression.
    from agentic_rag import mining, source_origin
    from agentic_rag.mining_window import MiningWindow
    path, sources = recording(tmp_path)
    records = [json.loads(line) for line in path.read_bytes().splitlines()]
    records[1]['message']['content'] = 'Sensor mode is now red.'
    path.write_bytes(b''.join(json.dumps(item).encode() + b'\n' for item in records))
    sources[1]['quote'] = 'Sensor mode is now red.'
    sources[1]['source_id'] = '1:' + hashlib.sha256(path.read_bytes()).hexdigest()
    events = tuple({'source_id': s['source_id'], 'role': 'user',
                    'text': '[user] ' + s['quote'], 'timestamp': s['timestamp'],
                    'offset': 0, 'complete': True} for s in sources)
    window = MiningWindow('\n'.join(e['text'] for e in events), 'end', events=events)
    calls = []
    output = {'assertions': [
        {'entity': 'sensor', 'attribute': 'mode', 'value': value,
         'domain': 'general', 'source_id': source['source_id'],
         'quote': source['quote'], 'event_at': source['timestamp'],
         'expires_at': None, 'relation': relation}
        for source, value, relation in zip(sources, ['blue', 'red'], ['assertion', 'replacement'])]}
    monkeypatch.setattr(mining, 'run_structured', lambda *a, **k: calls.append(1) or output)
    args = dict(session_id='old-native', transcript_path='', last_uuid=None,
                project='/synthetic/origin', provided_window=window)
    def interrupted():
        raise RuntimeError('accepted but not applied')
    if applied_before:
        mining.mine_session(conn, cfg, **args)
        assert conn.execute("SELECT disposition FROM fact_assertions WHERE value='red'").fetchone()['disposition'] == 'accepted'
    else:
        with pytest.raises(RuntimeError, match='accepted but not applied'):
            mining.mine_session(conn, cfg, **args, before_apply=interrupted)
    before = conn.execute('SELECT id,body,provenance FROM documents ORDER BY id').fetchall()
    source_origin.audit(cfg, path, 'session:old-native', apply=True, writers_stopped=True,
                        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if not applied_before:
        mining.mine_session(conn, cfg, **args)
    rows = {r['value']: r for r in conn.execute(
        'SELECT value,disposition,assertion_eligible(document_id) eligible FROM fact_assertions')}
    assert rows['blue']['eligible'] is True
    assert rows['red']['eligible'] is False
    assert len(calls) == 1
    if applied_before:
        assert conn.execute('SELECT id,body,provenance FROM documents ORDER BY id').fetchall() == before
        assert conn.execute("SELECT count(*) n FROM edges WHERE predicate='supersedes'").fetchone()['n'] == 1
    else:
        assert rows['red']['disposition'] == 'review'
        assert conn.execute("SELECT count(*) n FROM edges WHERE predicate='supersedes'").fetchone()['n'] == 0


def test_origin_preview_checks_database_conflicts_and_reports_source_keys(conn, cfg, tmp_path):
    # A file-only preview would miss the conflict until the apply maintenance window.
    from agentic_rag.source_origin import audit
    path, sources = recording(tmp_path)
    bad = {**sources[1], 'timestamp': '2026-11-01T01:00:00Z'}
    doc = save(conn, cfg, bad, 'Conflicting source time')
    preview = audit(cfg, path, 'session:old-native')
    key = evidence.sources(conn, doc.doc_id)[0]['source_key']
    assert preview['ready'] is False
    assert preview['metadata_conflicts'] == [key]
    assert preview['generated_source_keys'] == [key]
    assert preview['affected_claims'][0]['document_id'] == doc.doc_id
    assert evidence.sources(conn, doc.doc_id)[0]['state'] == 'active'


def test_origin_never_revives_replacement_with_independent_refuted_evidence(conn, cfg, tmp_path):
    from agentic_rag import source_origin, validity
    path, sources = recording(tmp_path)
    args = dict(entity='sensor', attribute='mode', domain='general', project='/synthetic/origin')
    original = store.save_assertion(conn, cfg, **args, value='blue', event_at=sources[0]['timestamp'],
        evidence={**sources[0], 'event_at': sources[0]['timestamp']})
    replacement = store.save_assertion(conn, cfg, **args, value='red', relation='replacement',
        event_at=sources[1]['timestamp'], evidence={**sources[1], 'event_at': sources[1]['timestamp']})
    validity.retain_source(conn, replacement.doc_id,
        {'source_id': 'independent', 'namespace': 'session:other', 'role': 'user',
         'quote': 'mode is red', 'complete': True}, 'cli')
    conn.commit()
    source_origin.audit(cfg, path, 'session:old-native', apply=True, writers_stopped=True,
                        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert conn.execute('SELECT assertion_eligible(%s) e', (replacement.doc_id,)).fetchone()['e']
    independent = next(s for s in evidence.sources(conn, replacement.doc_id) if s['source_id'] == 'independent')
    evidence.source_state(conn, independent['source_key'], state='refuted', reason='genuine correction')
    assert not conn.execute('SELECT assertion_eligible(%s) e', (original.doc_id,)).fetchone()['e']
    assert not conn.execute('SELECT assertion_eligible(%s) e', (replacement.doc_id,)).fetchone()['e']


def test_duplicate_assertion_does_not_invert_attachment_source_lock_order(conn, cfg):
    # Taking the source lock before the existing claim lock deadlocks a replay
    # against a concurrent ordinary attachment of that very source.
    import concurrent.futures
    import queue
    import time
    from agentic_rag import db
    args = dict(entity='sensor', attribute='port', value='blue',
                event_at='2026-11-01T00:00:00Z', domain='general', project='/synthetic/origin',
                evidence={'namespace': 'session:lock-order', 'source_id': 'one',
                          'role': 'user', 'quote': 'blue', 'complete': True})
    original = store.save_assertion(conn, cfg, **args)
    ready = queue.Queue()
    def duplicate():
        with db.connect(cfg) as other:
            other.execute("SET LOCAL lock_timeout='3000ms'")
            ready.put(other.info.backend_pid)
            return store.save_assertion(other, cfg, **args).duplicate
    with db.connect(cfg) as attachment:
        attachment.execute("SET LOCAL lock_timeout='500ms'")
        attachment.execute('SELECT document_id FROM claim_records WHERE document_id=%s FOR UPDATE',
                           (original.doc_id,))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(duplicate)
            pid = ready.get(timeout=3)
            blocked = False
            with db.connect(cfg) as observer:
                for _ in range(100):
                    observer.execute('SELECT pg_stat_clear_snapshot()')
                    row = observer.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s', (pid,)).fetchone()
                    observer.commit()
                    if row and row['wait_event_type'] == 'Lock':
                        blocked = True
                        break
                    time.sleep(.01)
            try:
                assert blocked
                evidence.attach(attachment, original.doc_id, [{**args['evidence'], 'timestamp': None}], 'cli')
                attachment.commit()
            finally:
                attachment.rollback()
            assert future.result(timeout=5) is True
