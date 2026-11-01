"""RAG-067 frozen extraction-policy fixtures and a deterministic mock provider.

The fixture cases run through actual mining: a Claude-format transcript file,
`read_window`, the real prompt, the mock provider below, unchanged grounding,
policy enforcement and the audited gateways. The mock provider returns the
predetermined output of each case and only maps fixture source IDs to the IDs
`read_window` assigned. It proves enforcement and replay, not model quality.
Used by the tests and by docs/benchmarks/2026-11-01-extraction-policy/measure.py.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / 'docs/benchmarks/2026-11-01-extraction-policy/fixtures'
SOURCE_MARKER = '\nSOURCE EVENTS (consumed fragments only):\n'


def _frozen() -> dict:
    listed = {}
    for line in (FIXTURES / 'FROZEN.sha256').read_text().splitlines():
        digest, name = line.split(None, 1)
        listed[name.strip()] = digest
    return listed


def load(name: str) -> dict:
    data = (FIXTURES / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != _frozen()[name]:
        raise ValueError('frozen fixture changed: ' + name)
    return json.loads(data)


def policy_path(name: str) -> Path:
    path = FIXTURES / 'policies' / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != _frozen()['policies/' + name]:
        raise ValueError('frozen fixture changed: ' + name)
    return path


def case(case_id: str) -> dict:
    return load('cases.json')['cases'][case_id]


def write_transcript(path, events) -> str:
    """Claude-format JSONL whose read_window text equals each fixture event text."""
    lines = []
    for event in events:
        prefix = f"[{event['role']}] "
        assert event['text'].startswith(prefix)
        lines.append(json.dumps({'uuid': event['source_id'], 'type': event['role'], 'timestamp': event['timestamp'],
                                 'message': {'role': event['role'], 'content': event['text'][len(prefix):]}}))
    Path(path).write_text('\n'.join(lines) + '\n')
    return str(path)


class MockProvider:
    """Stands in for llm.run_structured; counts calls and keeps prompts in memory."""

    def __init__(self, outputs, fixture_events):
        self.outputs = list(outputs)
        self.fixture_ids = [e['source_id'] for e in fixture_events]
        self.calls = 0
        self.prompts = []

    def __call__(self, prompt, schema, cfg, *, system=None, runner=None, **kwargs):
        from ..llm import LLMUnavailableError
        self.calls += 1
        self.prompts.append(prompt)
        if not self.outputs:
            raise AssertionError('unexpected provider call')
        output = self.outputs.pop(0)
        if output == 'PROVIDER_UNAVAILABLE':
            raise LLMUnavailableError('synthetic provider outage')
        events = json.loads(prompt.split(SOURCE_MARKER, 1)[1]) if SOURCE_MARKER in prompt else []
        mapping = {fixture: event['source_id'] for fixture, event in zip(self.fixture_ids, events)}
        return _map_ids(copy.deepcopy(output), mapping)


def _map_ids(value, mapping):
    if isinstance(value, dict):
        return {k: (mapping.get(v, v) if k == 'source_id' else _map_ids(v, mapping)) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_ids(v, mapping) for v in value]
    return value


def batch_policy(conn, session_id) -> dict:
    row = conn.execute("SELECT extraction FROM mining_batches WHERE session_id=%s ORDER BY created_at DESC LIMIT 1",
                       (session_id,)).fetchone()
    return (row['extraction'] or {}).get('_policy') if row else None


def retained(conn, session_id) -> dict:
    """Retained documents and suggestion audits of one mined session, by channel."""
    out = {}
    for row in conn.execute("SELECT d.dtype,d.title FROM documents d WHERE d.provenance->>'session_id'=%s"
                            " ORDER BY d.created_at,split_part(d.provenance->>'mining_item',':',2)::int", (session_id,)):
        out.setdefault({'memory': 'memories', 'lesson': 'lessons', 'signal': 'signals'}.get(row['dtype'], row['dtype']),
                       []).append(row['title'])
    for op, channel in (('pin_suggestion', 'pin_suggestions'), ('domain_proposal', 'domain_proposals'),
                        ('pin_contradiction', 'contradictions_with_pins')):
        n = conn.execute("SELECT count(*) n FROM audit_log WHERE op=%s AND summary LIKE %s",
                         (op, f'%(session {session_id})')).fetchone()['n']
        if n:
            out[channel] = n
    return out
