import json

import pytest

from agentic_rag.mining_window import read_window


def record(identity, text):
    return {'uuid': identity, 'message': {'role': 'user', 'content': text}}


def write(path, *records):
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    return path


def collect(path, **kwargs):
    cursor = None
    parts = []
    for _ in range(200):
        window = read_window(path, after_uuid=cursor, **kwargs)
        if window.last_uuid == cursor:
            return ''.join(parts), cursor
        parts.append(window.text)
        cursor = window.last_uuid
    pytest.fail('reader did not terminate')


def test_exact_issue_80_character_reproduction_and_oversized_block(tmp_path):
    path = write(tmp_path / 's.jsonl', record('first', 'A' * 200), record('last', 'TAIL_FACT_ONLY'))
    text, cursor = collect(path, max_chars=80, per_block=31)
    assert text.count('A') == 200 + 'TAIL_FACT_ONLY'.count('A')
    assert text.count('TAIL_FACT_ONLY') == 1
    assert read_window(path, after_uuid=cursor).text == ''


def test_incomplete_utf8_tail_is_not_consumed_and_can_be_completed(tmp_path):
    path = write(tmp_path / 's.jsonl', record('one', 'first'))
    complete = json.dumps(record('two', 'second ä'), ensure_ascii=False).encode() + b'\n'
    with path.open('ab') as stream:
        stream.write(complete[:-4])
    first = read_window(path)
    assert first.text == '[user] first'
    assert first.warnings
    with path.open('ab') as stream:
        stream.write(complete[-4:])
    assert read_window(path, after_uuid=first.last_uuid).text == '[user] second ä'


def test_malformed_complete_record_blocks_acknowledgement_until_repaired(tmp_path):
    path = write(tmp_path / 's.jsonl', record('one', 'first'))
    prefix = path.read_text()
    path.write_text(prefix + 'not-json\n' + json.dumps(record('three', 'third')) + '\n')
    first = read_window(path)
    assert first.warnings and 'third' not in first.text
    path.write_text(prefix + json.dumps(record('two', 'second')) + '\n' + json.dumps(record('three', 'third')) + '\n')
    resumed = read_window(path, after_uuid=first.last_uuid)
    assert 'second' in resumed.text and 'third' in resumed.text


def test_legacy_cursor_append_duplicate_and_changed_prefix(tmp_path):
    path = write(tmp_path / 's.jsonl', record('one', 'old'), record('two', 'new'), record('two', 'new'))
    window = read_window(path, after_uuid='one')
    assert window.text.count('new') == 1 and 'old' not in window.text
    with path.open('a') as stream:
        stream.write(json.dumps(record('three', 'appended')) + '\n')
    assert read_window(path, after_uuid=window.last_uuid).text == '[user] appended'
    write(path, record('one', 'changed'), record('two', 'new'))
    with pytest.raises(ValueError, match='recovery required'):
        read_window(path, after_uuid=window.last_uuid)
    with pytest.raises(ValueError, match='recovery required'):
        read_window(path, after_uuid='missing')


def test_conflicting_duplicate_identity_is_not_silently_dropped(tmp_path):
    path = write(tmp_path / 's.jsonl', record('same', 'one'), record('same', 'different'))
    with pytest.raises(ValueError, match='conflicting duplicate'):
        read_window(path)


def test_codex_records_redaction_and_excluded_tool_payloads(tmp_path):
    path = write(tmp_path / 's.jsonl',
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
         'content': [{'type': 'input_text', 'text': 'remember sk-abcdefghijklmnop1234'}]}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
         'content': [{'type': 'output_text', 'text': 'recorded'}]}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': 'PRIVATE_TOOL_BODY'}},
        {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'recorded'}})
    text = read_window(path).text
    assert '[user] remember [REDACTED]' in text
    assert text.count('recorded') == 1
    assert 'PRIVATE_TOOL_BODY' not in text
    assert 'sk-abcdefghijklmnop1234' not in text


def test_missing_source_and_invalid_cursor_fail_visibly(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_window(tmp_path / 'missing')
    path = write(tmp_path / 's.jsonl', record('one', 'value'))
    for cursor in ['mw1:{}', 'mw1:[]', 'mw1:broken']:
        with pytest.raises(ValueError, match='recovery required'):
            read_window(path, after_uuid=cursor)


def test_ambiguous_legacy_cursor_never_skips_intervening_event(tmp_path):
    path = write(tmp_path / 's.jsonl', record('old', 'processed'),
                 record('unseen', 'must not skip'), record('old', 'processed'))
    with pytest.raises(ValueError, match='recovery required'):
        read_window(path, after_uuid='old')
