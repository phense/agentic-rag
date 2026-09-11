"""Bounded JSON stdin bridge. No provider calls, arbitrary file paths or direct SQL writes."""
from __future__ import annotations

from dataclasses import replace
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from ...hooks import common

TRANSCRIPT_DIR = Path.home() / '.agentic-rag' / 'opencode' / 'transcripts'
MAX_BYTES = 8 * 1024 * 1024
MAX_INPUT = 4 * 1024 * 1024
COMPACT_PROMPT = '''Preserve a concise evidence-backed continuation handoff: current objective,
user constraints and approvals, decisions, verified repository/worktree state,
completed and remaining tasks, actual test results, blockers and next exact action.
Label historical facts. Reference canonical RAG knowledge by slug; do not repeat
memory bodies, tool results, reasoning, credentials or secret-shaped values.'''


def identity(payload):
    sid = payload.get('session_id')
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', sid):
        raise ValueError('invalid OpenCode session identity')
    cwd = payload.get('cwd')
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError('absolute session cwd required')
    return 'opencode:' + sid


def plain_parents(path):
    for p in reversed((path, *path.parents)):
        if p.is_symlink() or (p.exists() and not p.is_dir()):
            raise ValueError('refusing unsafe adapter directory')


def project_transcript(payload, *, boundary_id=None):
    """Private projection in the existing digest format; no host file is opened."""
    from ...secrets import strip_secrets
    sid = identity(payload)
    plain_parents(TRANSCRIPT_DIR)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(sid.encode()).hexdigest()
    path = TRANSCRIPT_DIR / (key + '.jsonl')
    lock = TRANSCRIPT_DIR / (key + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        rows = {}
        if path.is_symlink():
            raise ValueError('refusing symlinked projection')
        if path.exists():
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as old:
                raw = old.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('existing projection exceeds bound')
            for line in raw.splitlines():
                row = json.loads(line)
                rows[row['uuid']] = row
        messages = payload.get('messages', [])
        if not isinstance(messages, list) or len(messages) > 200:
            raise ValueError('invalid bounded message projection')
        for msg in messages:
            if not isinstance(msg, dict) or msg.get('role') not in ('user', 'assistant'):
                continue
            mid = msg.get('id')
            if not isinstance(mid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', mid):
                continue
            content = []
            text = msg.get('text')
            if isinstance(text, str) and text.strip():
                content.append({'type': 'text', 'text': strip_secrets(text[:16000])[0]})
            tools = msg.get('tools', [])
            if isinstance(tools, list):
                for tool in tools[:100]:
                    if isinstance(tool, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', tool):
                        content.append({'type': 'tool_use', 'name': tool, 'input': {}})
            if content:
                uid = 'opencode:' + mid
                rows[uid] = {'uuid': uid, 'type': msg['role'], 'client': 'opencode',
                             'message': {'role': msg['role'], 'content': content}}
        if boundary_id is not None:
            # The checkpoint cursor must be an actual digest offset, including
            # back-to-back compactions with no new prose.
            uid = 'opencode:' + boundary_id
            rows.setdefault(uid, {'uuid': uid, 'type': 'compaction_boundary',
                                  'client': 'opencode', 'message': {'role': 'user', 'content': []}})
        encoded = [json.dumps(row, ensure_ascii=False).encode() + b'\n' for row in rows.values()]
        size = sum(map(len, encoded))
        omitted = False
        while encoded and size > MAX_BYTES:
            size -= len(encoded.pop(0))
            omitted = True
        if omitted:
            common.log_hook_error('opencode.projection', 'Older projection records omitted at 8 MiB bound')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=TRANSCRIPT_DIR, delete=False) as out:
                temporary = Path(out.name)
                for line in encoded:
                    out.write(line)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return path


def startup_context(payload):
    from ...hooks import session_start
    output = io.StringIO()
    session_start.run({'session_id': identity(payload), 'cwd': payload['cwd'],
                       'source': payload.get('source', 'resume')}, output)
    result = json.loads(output.getvalue() or '{}')
    return result.get('hookSpecificOutput', {}).get('additionalContext', '')


def dispatch(event, payload):
    if os.environ.get('AGENTIC_RAG_HOOKS_DISABLE', '').strip():
        return {'ok': True}
    try:
        sid = identity(payload)
        from ...secrets import strip_secrets
        if event == 'context':
            text = startup_context(payload)
            from ...hooks.prompt_recall import recall_context
            prompt = payload.get('prompt', '')
            if isinstance(prompt, str) and prompt:
                try:
                    recall = recall_context(prompt[:12000], payload['cwd'])
                    if recall:
                        text += '\n\n' + recall
                except Exception as exc:
                    common.log_hook_error('opencode.recall', repr(exc))
            return {'ok': True, 'context': strip_secrets(text)[0]}
        if event not in ('idle', 'pre-compact', 'post-compact'):
            raise ValueError('unknown OpenCode event')
        from ... import db, jobs
        from ...config import load_config
        from ...continuity import capture, store
        cfg = load_config()
        if event == 'idle':
            path = project_transcript(payload)
            with db.connect(cfg, role='writer') as conn:
                jobs.enqueue_mine(conn, cfg, session_id=sid, transcript_path=str(path), project=payload['cwd'])
            common.spawn_worker()
            return {'ok': True}
        boundary = payload.get('boundary_id')
        trigger = payload.get('trigger')
        if not isinstance(boundary, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', boundary):
            raise ValueError('compaction request identity required')
        if trigger not in ('manual', 'auto'):
            raise ValueError('compaction trigger required')
        with db.connect(cfg, role='writer') as conn:
            checkpoint = store.matching_compaction(conn, sid, boundary, trigger)
            if event == 'post-compact':
                if checkpoint is None:
                    raise ValueError('matching pre-compaction checkpoint unavailable')
                summary = payload.get('summary')
                if not isinstance(summary, str) or not summary.strip():
                    raise ValueError('completed compaction summary required')
                if checkpoint.compacted_at is None:
                    store.mark_compacted(conn, sid, checkpoint.cursor)
                if checkpoint.handoff is None:
                    store.attach_handoff(conn, checkpoint.id, summary, max_chars=cfg.checkpoint_handoff_max_chars)
                return {'ok': True, 'checkpoint_id': checkpoint.id}
            if checkpoint is None:
                path = project_transcript(payload, boundary_id=boundary)
                seed = capture.capture_snapshot_seed({'session_id': sid, 'cwd': payload['cwd'],
                    'turn_id': boundary, 'hook_event_name': 'PreCompact', 'trigger': trigger,
                    'transcript_path': str(path)})
                seed = replace(seed, cursor='opencode:' + boundary)
                checkpoint = store.upsert_snapshot(conn, seed, update_existing=False)
                try:
                    checkpoint = store.upsert_snapshot(conn, capture.capture_repository_state(seed, cwd=payload['cwd']))
                except Exception as exc:
                    conn.rollback()
                    common.log_hook_error('opencode.repository', repr(exc))
                jobs.enqueue_checkpoint_enrichment(conn, checkpoint_id=checkpoint.id, session_id=sid,
                    transcript_path=str(path), after_cursor=checkpoint.predecessor_cursor)
                common.spawn_worker()
            return {'ok': True, 'checkpoint_id': checkpoint.id,
                    'context': COMPACT_PROMPT + '\nagentic-rag checkpoint: ' + checkpoint.id}
    except Exception as exc:
        common.log_hook_error('opencode.' + str(event), repr(exc))
        return {'ok': False, 'context': 'agentic-rag unavailable: ' + common.sanitize_error(str(exc))}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('OpenCode hook input exceeds bound')
        payload = json.loads(raw)
        result = dispatch(sys.argv[1] if len(sys.argv) > 1 else '', payload)
    except Exception as exc:
        common.log_hook_error('opencode.input', repr(exc))
        result = {'ok': False, 'context': 'agentic-rag unavailable: invalid hook input'}
    print(json.dumps(result))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
