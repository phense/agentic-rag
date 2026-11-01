"""Remote activation must cover every retained window in the exact stored stream."""
import hashlib
import json
from pathlib import Path

import pytest

from agentic_rag import db
from agentic_rag.mining_window import read_window
from agentic_rag.service.auth import Policy
from agentic_rag.service.ingest import accept
from agentic_rag.source_origin import audit
from .test_auth import policy_file
from .test_scope import service_store


def test_origin_preview_covers_real_remote_stream_and_blocks_missing_window(service_store, tmp_path):
    cfg, _ = service_store
    policy = Policy.load(policy_file(tmp_path))
    principal = policy.authenticate_key('one.synthetic-long-random-machine-secret')
    path = tmp_path / 'original.jsonl'
    path.write_text(json.dumps({'type': 'user', 'uuid': 'one',
        'message': {'role': 'user', 'content': 'Synthetic blue sensor'}}) + '\n')
    window = read_window(path)
    data = {'version': 1, 'session_id': 'native-one', 'input_cursor': '',
            'output_cursor': window.last_uuid, 'project': '/projects/a',
            'window': {'text': window.text, 'events': list(window.events),
                       'warnings': [], 'synthetic': False, 'has_more': False}}
    accept(cfg, principal, policy, data)
    namespace = principal.session_id('native-one')
    preview = audit(cfg, path, namespace)
    assert preview['ready'] is True
    assert preview['window_coverage']['total'] == 1
    assert preview['window_coverage']['uncovered'] == []
    # A durable window from a longer recording cannot be covered by the old prefix.
    first_end = window.last_uuid
    path.write_text(path.read_text() + json.dumps({'type': 'user', 'uuid': 'two',
        'message': {'role': 'user', 'content': 'Synthetic later original'}}) + '\n')
    later = read_window(path, after_uuid=first_end)
    data['input_cursor'] = first_end
    data['output_cursor'] = later.last_uuid
    data['window']['text'] = later.text
    data['window']['events'] = list(later.events)
    accept(cfg, principal, policy, data)
    prefix = tmp_path / 'incomplete-prefix.jsonl'
    prefix.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    preview = audit(cfg, prefix, namespace)
    assert preview['ready'] is False
    assert preview['window_coverage']['total'] == 2
    assert len(preview['window_coverage']['uncovered']) == 1
    with pytest.raises(ValueError, match='coverage'):
        audit(cfg, prefix, namespace, apply=True, writers_stopped=True,
              expected_sha256=hashlib.sha256(prefix.read_bytes()).hexdigest())
    with db.connect(cfg) as conn:
        assert conn.execute('SELECT count(*) n FROM knowledge_sources').fetchone()['n'] == 0
    assert audit(cfg, path, namespace)['ready'] is True


def test_export_retains_raw_bytes_and_rejects_uncovered_local_pending_window(tmp_path):
    # Exporting sources.raw alone would omit a later unacknowledged window.
    from agentic_rag import source_origin
    from agentic_rag.service.spool import Spool
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    path = root / 'record.jsonl'
    raw = (json.dumps({'type': 'user', 'uuid': 'one',
         'message': {'role': 'user', 'content': 'Synthetic blue sensor'}}) + '\n').encode()
    path.write_bytes(raw)
    window = read_window(path)
    payload = {'version': 1, 'session_id': 'native-one', 'input_cursor': '',
               'output_cursor': window.last_uuid, 'project': '/projects/a',
               'window': {'text': window.text, 'events': list(window.events),
                          'warnings': [], 'synthetic': False, 'has_more': False}}
    spool_path = root / 'spool.sqlite'
    with Spool(spool_path, 'frozen-partition') as spool:
        spool.capture_source('native-one', '/projects/a', raw)
        spool.enqueue('window', 'native-one', payload)
    before = spool_path.read_bytes()
    output = root / 'export.jsonl'
    report = source_origin.export_spool(spool_path, 'frozen-partition', 'native-one', output)
    assert report['pending_windows'] == 1 and report['ready'] is True
    assert output.read_bytes() == raw
    assert spool_path.read_bytes() == before
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        source_origin.export_spool(spool_path, 'frozen-partition', 'native-one', output)
    with Spool(spool_path, 'frozen-partition') as spool:
        payload['input_cursor'] = window.last_uuid
        payload['output_cursor'] = 'uncovered-later-cursor'
        spool.enqueue('window', 'native-one', payload)
    with pytest.raises(ValueError, match='coverage'):
        source_origin.export_spool(spool_path, 'frozen-partition', 'native-one', root / 'refused.jsonl')
    assert not (root / 'refused.jsonl').exists()


def test_playbook_export_and_namespace_inventory_snippets_execute(service_store, tmp_path):
    import subprocess
    import sys
    from agentic_rag.service.spool import Spool
    root = Path(__file__).resolve().parents[2]
    text = (root / 'docs/playbooks/agent-plugins.md').read_text()
    def snippet(marker):
        return text.split("<<'" + marker + "'\n", 1)[1].split('\n' + marker, 1)[0]
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    spool = private / 'spool.sqlite'
    raw = (json.dumps({'type': 'user', 'uuid': 'one',
           'message': {'role': 'user', 'content': 'Synthetic source'}}) + '\n').encode()
    with Spool(spool, 'synthetic-partition') as c:
        c.capture_source('synthetic-session', '/projects/a', raw)
    command = subprocess.run([sys.executable, '-', str(spool), 'synthetic-partition',
        'synthetic-session', str(private / 'original.jsonl'), str(private / 'export.json')],
        input=snippet('PYEXPORT'), text=True, capture_output=True, timeout=15, cwd=root)
    assert command.returncode == 0, command.stderr
    assert (private / 'original.jsonl').read_bytes() == raw
    assert json.loads((private / 'export.json').read_text())['ready']
    command = subprocess.run([sys.executable, '-', str(spool)], input=snippet('PYLIST'),
        text=True, capture_output=True, timeout=15, cwd=root)
    assert command.returncode == 0, command.stderr
    assert json.loads(command.stdout) == [['synthetic-partition', 'synthetic-session', '/projects/a', len(raw)]]
    cfg, _ = service_store
    policy = Policy.load(policy_file(tmp_path))
    principal = policy.authenticate_key('one.synthetic-long-random-machine-secret')
    window = read_window(private / 'original.jsonl')
    accept(cfg, principal, policy, {'version': 1, 'session_id': 'pb-inventory',
        'input_cursor': '', 'output_cursor': window.last_uuid, 'project': '/projects/a',
        'window': {'text': window.text, 'events': list(window.events),
                   'warnings': [], 'synthetic': False, 'has_more': False}})
    config = private / 'operator.toml'
    config.write_text('[db]\nname = "' + cfg.db_name + '"\nhost = "127.0.0.1"\n')
    command = subprocess.run([sys.executable, '-', str(config), str(private / 'streams.json')],
        input=snippet('PYSTREAMS'), text=True, capture_output=True, timeout=15, cwd=root)
    assert command.returncode == 0, command.stderr
    rows = json.loads((private / 'streams.json').read_text())
    assert all(r['session_id'].startswith('svc1:') for r in rows)
    match = [r for r in rows if r['client_session'] == 'pb-inventory']
    assert len(match) == 1 and match[0]['windows'] == 1
    assert match[0]['session_id'] == principal.session_id('pb-inventory')
