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


def drifted(event, **metadata):
    """Re-appended copy of an event whose host-only metadata changed."""
    return {**event, **metadata}


def tool_record(identity, name, role='assistant'):
    return {'uuid': identity, 'message': {'role': role, 'content': [
        {'type': 'tool_use', 'name': name, 'input': {}}]}}


def test_reappended_events_with_drifted_host_metadata_are_duplicates(tmp_path):
    # /compact of a resumed Claude Code session re-appends earlier events with
    # changed slug/promptId/toolUseResult but identical conversation content.
    one = {**record('one', 'first fact'), 'slug': 'old-slug', 'promptId': 'p1'}
    two = {**tool_record('two', 'Bash'), 'toolUseResult': {'stdout': 'x'}}
    path = write(tmp_path / 's.jsonl', one, two, record('three', 'third fact'),
                 drifted(one, slug='new-slug', promptId='p2'),
                 drifted(two, toolUseResult={'stdout': 'y'}),
                 record('four', 'after rewrite'))
    text, _ = collect(path)
    assert text.count('first fact') == 1
    assert text.count('[assistant tool: Bash]') == 1
    assert text.endswith('[user] after rewrite')


@pytest.mark.parametrize('original,changed', [
    (record('same', 'one'), record('same', 'different prose')),
    (record('same', 'one'), {'uuid': 'same', 'message': {'role': 'assistant', 'content': 'one'}}),
    (tool_record('same', 'Bash'), tool_record('same', 'Edit')),
    (record('same', 'one'), {**record('same', 'one'), 'isCompactSummary': True}),
    (record('same', 'one'), {**record('same', 'one'), 'isMeta': True}),
])
def test_duplicate_identity_with_changed_conversation_content_conflicts(tmp_path, original, changed):
    path = write(tmp_path / 's.jsonl', original, changed)
    with pytest.raises(ValueError, match='conflicting duplicate'):
        read_window(path)


def test_cursor_before_and_inside_reappended_block_resumes_without_repeats(tmp_path):
    one, two = record('one', 'alpha'), record('two', 'beta')
    path = write(tmp_path / 's.jsonl', one, two)
    before = read_window(path)
    assert before.text == '[user] alpha\n[user] beta'
    with path.open('a') as stream:
        for event in (drifted(one, slug='s2'), drifted(two, slug='s2'), record('three', 'gamma')):
            stream.write(json.dumps(event) + '\n')
    after = read_window(path, after_uuid=before.last_uuid)
    assert after.text == '[user] gamma'
    assert json.loads(after.last_uuid[4:])['line'] == 4
    # A cursor issued on a duplicate line keeps working: duplicates are empty.
    inside = 'mw1:' + json.dumps({'line': 2, 'offset': 0, 'hash': _prefix_hash(path, 2)},
                                 separators=(',', ':'))
    assert read_window(path, after_uuid=inside).text == '[user] gamma'


def _prefix_hash(path, line):
    import hashlib
    chain = hashlib.sha256()
    with path.open('rb') as stream:
        for number, raw in enumerate(stream):
            chain.update(raw)
            if number == line:
                return chain.hexdigest()


def test_unchanged_transcripts_keep_their_windows_and_cursors(tmp_path):
    path = write(tmp_path / 's.jsonl', record('one', 'a' * 50), tool_record('two', 'Read'),
                 record('three', 'tail'))
    first = read_window(path, max_chars=40, per_block=800)
    assert first.text == '[user] ' + 'a' * 33
    assert json.loads(first.last_uuid[4:]) == {'line': 0, 'offset': 40, 'hash': _prefix_hash(path, 0)}
    text, cursor = collect(path, max_chars=40)
    assert text == '[user] ' + 'a' * 50 + '\n[assistant tool: Read][user] tail'
    assert json.loads(cursor[4:])['line'] == 2


def test_legacy_uuid_cursor_on_reappended_identity_stays_fail_closed(tmp_path):
    one = record('one', 'alpha')
    path = write(tmp_path / 's.jsonl', one, record('two', 'beta'), drifted(one, slug='s2'))
    with pytest.raises(ValueError, match='legacy mining cursor missing or ambiguous'):
        read_window(path, after_uuid='one')


def test_codex_duplicates_tolerate_metadata_and_agy_steps_stay_strict(tmp_path):
    codex = {'type': 'response_item', 'timestamp': 't1', 'payload': {
        'type': 'message', 'id': 'msg_1', 'role': 'user',
        'content': [{'type': 'input_text', 'text': 'codex words'}]}}
    path = write(tmp_path / 'codex.jsonl', codex, drifted(codex, timestamp='t2'))
    assert read_window(path).text == '[user] codex words'
    changed = {**codex, 'payload': {**codex['payload'],
               'content': [{'type': 'input_text', 'text': 'other words'}]}}
    write(path, codex, changed)
    with pytest.raises(ValueError, match='conflicting duplicate'):
        read_window(path)
    # An agy identity is only a step index: a repeated step stays strict.
    step = {'step_index': 0, 'type': 'USER_INPUT', 'content': 'agy words', 'created_at': 'c1'}
    path = write(tmp_path / 'agy.jsonl', step, dict(step))
    assert read_window(path).text.count('agy words') == 1
    write(path, step, drifted(step, created_at='c2'))
    with pytest.raises(ValueError, match='conflicting duplicate'):
        read_window(path)


def test_lone_surrogate_duplicate_is_digestible(tmp_path):
    path = tmp_path / 's.jsonl'
    line = '{"uuid": "one", "message": {"role": "user", "content": "bad \\ud800 text"}}\n'
    path.write_text(line + line.replace('"uuid"', '"slug": "x", "uuid"'))
    assert read_window(path).text.count('bad') == 1
