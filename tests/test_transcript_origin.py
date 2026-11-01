"""Native generated records must not acquire original human-source authority."""
import hashlib
import json

import pytest

from agentic_rag.mining import ground_assertions, ground_claim_items
from agentic_rag.mining_window import read_window
from agentic_rag.transcript import build_digest


def transcript(tmp_path, generated):
    # Shape observed in Claude Code2.1.314, synthetic text only. The mutation
    # caught here is trusting message.role='user' in a generated host record.
    records = [
        {'type': 'user', 'uuid': 'original', 'message': {
            'role': 'user', 'content': 'Sensor mode is blue.'}},
        {'type': 'user', 'uuid': 'generated', 'message': {
            'role': 'user', 'content': 'Sensor mode is red.'}, **generated},
        {'type': 'user', 'uuid': 'tail', 'message': {
            'role': 'user', 'content': 'Wait for fixture approval Z4.'}},
    ]
    raw = [json.dumps(record).encode() + b'\n' for record in records]
    path = tmp_path / 'native.jsonl'
    path.write_bytes(b''.join(raw))
    return path, raw


GENERATED = [{'isCompactSummary': True}, {'isMeta': True},
             {'type': 'api-request-blob'}]


@pytest.mark.parametrize('generated', GENERATED)
def test_generated_host_prose_cannot_ground_claims_or_assertions(tmp_path, generated):
    path, raw = transcript(tmp_path, generated)
    window = read_window(path)
    phantom = '1:' + hashlib.sha256(b''.join(raw[:2])).hexdigest()
    claims = ground_claim_items({'memories': [{
        'body': 'Sensor mode is red.', 'claim_kind': 'stated',
        'evidence': [{'source_id': phantom, 'quote': 'Sensor mode is red.'}],
    }]}, window.events, 'native-fixture')
    assertions = ground_assertions([{
        'entity': 'Sensor', 'attribute': 'mode', 'value': 'red',
        'domain': 'general', 'relation': 'assertion',
        'source_id': phantom, 'quote': 'Sensor mode is red.',
    }], window.events)

    assert claims['memories'][0]['evidence'] == []
    assert claims['memories'][0]['claim_kind'] == 'inference'
    assert assertions == []
    assert window.text == '[user] Sensor mode is blue.\n[user] Wait for fixture approval Z4.'
    assert [event['role'] for event in window.events] == ['user', 'user']
    assert path.read_bytes() == b''.join(raw)


@pytest.mark.parametrize('generated', GENERATED)
@pytest.mark.parametrize('offset', [0, 12, 26])
def test_legacy_cursor_in_generated_record_preserves_next_original(tmp_path, generated, offset):
    path, raw = transcript(tmp_path, generated)
    # 0.6.20 offsets include the historical '[user] ' prefix. An upgrade must
    # consume an already partially mined generated record without shifting any
    # subsequent original source ID or silently rewinding the user turn.
    cursor = 'mw1:' + json.dumps({
        'line': 1, 'offset': offset,
        'hash': hashlib.sha256(b''.join(raw[:2])).hexdigest(),
    }, separators=(',', ':'))
    window = read_window(path, after_uuid=cursor)
    assert window.text == '[user] Wait for fixture approval Z4.'
    assert len(window.events) == 1
    assert window.events[0]['source_id'] == '2:' + hashlib.sha256(b''.join(raw)).hexdigest()
    assert window.events[0]['offset'] == 0
    assert window.events[0]['complete'] is True
    assert read_window(path, after_uuid=window.last_uuid).text == ''


@pytest.mark.parametrize('generated', GENERATED)
def test_digest_excludes_generated_host_records_but_advances_identity(tmp_path, generated):
    path, raw = transcript(tmp_path, generated)
    path.write_bytes(b''.join(raw[:2]))
    digest = build_digest(path)
    assert digest.text == '[user] Sensor mode is blue.'
    assert digest.last_uuid == 'generated'
    assert digest.n_events == 2


def test_user_words_about_compaction_are_still_original_evidence(tmp_path):
    path, _ = transcript(tmp_path, {'isCompactSummary': False, 'isMeta': False})
    assert [event['role'] for event in read_window(path).events] == ['user'] * 3
    assert '[user] Sensor mode is red.' in build_digest(path).text
