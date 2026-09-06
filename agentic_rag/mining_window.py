"""Lossless windows of eligible redacted prose; independent of continuity digests."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .secrets import strip_secrets
from .transcript_agy import is_step, step_identity, step_prose

PREFIX = 'mw1:'


@dataclass(frozen=True)
class MiningWindow:
    text: str
    last_uuid: str | None
    has_more: bool = False
    warnings: tuple[str, ...] = ()
    synthetic: bool = False
    events: tuple[dict, ...] = ()


def _content(event: dict) -> tuple[str | None, str]:
    if is_step(event):
        # Antigravity CLI trajectory step (no uuid; identity = step index)
        return step_identity(event), '\n'.join(step_prose(event))
    message = event.get('message')
    if event.get('type') == 'response_item':
        payload = event.get('payload')
        if isinstance(payload, dict) and payload.get('type') == 'message':
            message = payload
    identity = event.get('uuid')
    if not isinstance(identity, str):
        identity = message.get('id') if isinstance(message, dict) else None
    if not isinstance(identity, str):
        identity = None
    if not isinstance(message, dict):
        return identity, ''
    role = message.get('role')
    if role not in {'user', 'assistant'}:
        return identity, ''
    content = message.get('content')
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    if not isinstance(blocks, list):
        return identity, ''
    lines = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') in {'text', 'input_text', 'output_text'}:
            value = block.get('text')
            if isinstance(value, str) and value.strip():
                lines.append(f'[{role}] {strip_secrets(value.strip())[0]}')
        elif block.get('type') == 'tool_use':
            name = str(block.get('name', '?'))
            inp = block.get('input')
            if 'memory_' in name and isinstance(inp, dict):
                hint = inp.get('slug') or inp.get('id_or_slug') or inp.get('query')
                if isinstance(hint, str) and hint.strip():
                    name += ' ' + strip_secrets(hint)[0][:120]
            lines.append(f'[{role} tool: {strip_secrets(name)[0]}]')
    return identity, '\n'.join(lines)


def read_window(path: str | Path, *, after_uuid: str | None = None,
                max_chars: int = 12000, per_block: int = 800) -> MiningWindow:
    if type(max_chars) is not int or max_chars < 32 or type(per_block) is not int or per_block < 1:
        raise ValueError('mining windows require max_chars >= 32 and per_block >= 1')
    records = []
    metadata = []
    chain = hashlib.sha256()
    seen = {}
    warnings = []
    # An opening failure must not acknowledge missing input.
    with Path(path).open('rb') as stream:
        for number, raw in enumerate(stream):
            if not raw.endswith(b'\n'):
                warnings.append('incomplete trailing record; awaiting completion')
                break
            try:
                ev = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                warnings.append(f'malformed record at line {number + 1}; awaiting repair')
                break
            chain.update(raw)
            identity, text = _content(ev) if isinstance(ev, dict) else (None, '')
            if identity:
                digest = hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()
                if identity in seen:
                    if seen[identity] != digest:
                        raise ValueError('conflicting duplicate transcript identity; recovery required')
                    text = ''
                seen[identity] = digest
            records.append((number, identity, text, chain.hexdigest()))
            message = ev.get('message', ev.get('payload', {})) if isinstance(ev, dict) else {}
            role = message.get('role') if isinstance(message, dict) else None
            timestamp = ev.get('timestamp') if isinstance(ev, dict) else None
            if isinstance(ev, dict) and is_step(ev):
                role = {'USER_INPUT': 'user', 'PLANNER_RESPONSE': 'assistant'}.get(ev['type'])
                timestamp = ev.get('created_at')
            metadata.append({'source_id': f'{number}:{chain.hexdigest()}',
                             'role': role, 'timestamp': timestamp})
    start = offset = 0
    if after_uuid and after_uuid.startswith(PREFIX):
        try:
            cursor = json.loads(after_uuid[len(PREFIX):])
            start, offset, expected = cursor['line'], cursor['offset'], cursor['hash']
            if (type(start) is not int or type(offset) is not int or start < 0 or offset < 0
                    or start >= len(records) or records[start][3] != expected
                    or offset > len(records[start][2])):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('mining cursor source changed or disappeared; recovery required') from None
    elif after_uuid:
        matches = [i for i, r in enumerate(records) if r[1] == after_uuid]
        if len(matches) != 1:
            raise ValueError('legacy mining cursor missing or ambiguous; explicit recovery required')
        start = matches[-1] + 1
    parts = []
    events = []
    used = 0
    next_cursor = after_uuid
    more = False
    for index in range(start, len(records)):
        number, identity, text, prefix_hash = records[index]
        begin = offset if index == start else 0
        remaining = text[begin:]
        separator = '\n' if parts and remaining else ''
        budget = max_chars - used - len(separator)
        if remaining and (budget <= 0 or len(events) >= 64):
            more = True
            break
        # per_block is a per-window event budget, never an omission policy.
        take = min(len(remaining), budget, per_block)
        if take:
            parts.append(separator + remaining[:take])
            events.append({**metadata[index], "text": remaining[:take], "offset": begin, "complete": begin == 0 and begin + take == len(text)})
            used += len(separator) + take
        end = begin + take
        next_cursor = PREFIX + json.dumps({'line': number, 'offset': end,
                                           'hash': prefix_hash}, separators=(',', ':'))
        if end < len(text):
            more = True
            break
    first = next((r[2] for r in records if r[2]), '')
    synthetic = first.startswith('[user] SESSION DIGEST (user/assistant prose + tool names; tool outputs omitted):')
    return MiningWindow(''.join(parts), next_cursor, more, tuple(warnings), synthetic, tuple(events))
