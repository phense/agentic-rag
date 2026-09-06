import json

from agentic_rag import transcript_agy as ta
from agentic_rag.continuity import capture
from agentic_rag.mining_window import read_window
from agentic_rag.transcript import build_digest


def user(idx, text, *, wrapped=True):
    content = (
        f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n"
        "The current local time is: 2026-09-06T01:14:37+02:00.\n"
        "</ADDITIONAL_METADATA>\n<USER_SETTINGS_CHANGE>\nmodel changed\n"
        "</USER_SETTINGS_CHANGE>" if wrapped else text)
    return {"step_index": idx, "source": "USER_EXPLICIT", "type": "USER_INPUT",
            "status": "DONE", "created_at": "2026-09-05T23:14:37Z",
            "content": content}


def model(idx, text=None, tool_calls=None):
    step = {"step_index": idx, "source": "MODEL", "type": "PLANNER_RESPONSE",
            "status": "DONE", "created_at": "2026-09-05T23:14:39Z"}
    if text is not None:
        step["content"] = text
    if tool_calls is not None:
        step["tool_calls"] = tool_calls
    return step


def write(path, *steps):
    path.write_text("".join(json.dumps(s) + "\n" for s in steps))
    return path


def test_user_request_text_unwraps_and_drops_client_blocks():
    text = ta.user_request_text(user(0, "fix the flaky test")["content"])
    assert text == "fix the flaky test"
    assert ta.user_request_text("plain words") == "plain words"


def test_compact_request_detection_accepts_instructions():
    assert ta.is_compact_request(user(2, "/compact")["content"])
    assert ta.is_compact_request(user(2, "/compact focus on tests")["content"])
    assert not ta.is_compact_request(user(2, "/compaction theory?")["content"])
    assert not ta.is_compact_request(user(2, "please /compact later")["content"])


def test_step_prose_keeps_words_and_tool_names_only():
    calls = [
        {"name": "run_command", "args": {"CommandLine": "cat ~/.ssh/id_rsa"}},
        {"name": "call_mcp_tool", "args": {
            "ToolName": "memory_search", "Arguments": {"query": "flaky test"}}},
    ]
    lines = ta.step_prose(model(1, "Looking now sk-abcdefghijklmnop1234", calls))
    assert lines[0].startswith("[assistant] Looking now")
    assert "sk-abcdefghijklmnop1234" not in lines[0]
    assert lines[1] == "[assistant tool: run_command]"
    assert lines[2] == "[assistant tool: memory_search flaky test]"
    assert "id_rsa" not in "\n".join(lines)
    assert ta.step_prose({"step_index": 3, "type": "TOOL_RESULT",
                          "content": "SECRET"}) == []
    assert ta.step_prose({"uuid": "x", "message": {}}) == []


def test_read_tail_steps_skips_partial_tail_and_respects_window(tmp_path):
    path = write(tmp_path / "t.jsonl", user(0, "a"), model(1, "b"))
    with path.open("ab") as fh:
        fh.write(b'{"step_index": 2, "type": "USER_INPUT", "content": "unfinished')
    steps = ta.read_tail_steps(path)
    assert [s.index for s in steps] == [0, 1]
    assert ta.read_tail_steps(path, max_bytes=40) == [] or all(
        s.index >= 1 for s in ta.read_tail_steps(path, max_bytes=120))
    assert ta.read_tail_steps(tmp_path / "missing.jsonl") == []


def test_manual_compaction_and_summary_lookup(tmp_path):
    steps = ta.read_tail_steps(write(
        tmp_path / "t.jsonl", user(0, "remember X"), model(1, "OK"),
        user(2, "/compact"), model(3, "### Conversation Summary\n- X")))
    request = ta.manual_compaction(steps[:3])
    assert request is not None and request.index == 2
    assert request.identity == "agy-step-2"
    assert ta.compaction_summary(steps, 2) == "### Conversation Summary\n- X"
    assert ta.manual_compaction(steps[:2]) is None
    later = steps + [ta.parse_step(user(4, "what now?"))]
    assert ta.manual_compaction(later) is None
    assert ta.compaction_summary(later[:3], 2) is None


def test_auto_compaction_marker_detection():
    marker = {"step_index": 7, "source": "SYSTEM", "type": "CHECKPOINT",
              "status": "DONE", "content": "<CONTEXT_SUMMARY>\nsummary body\n</CONTEXT_SUMMARY>"}
    steps = [ta.parse_step(s) for s in (user(6, "a"), marker, user(8, "b"))]
    found = ta.latest_auto_compaction(steps)
    assert found is not None and found.index == 7
    assert ta.auto_compaction_summary(found) == "summary body"
    tagged = ta.parse_step({"step_index": 9, "source": "SYSTEM", "type": "GENERIC",
                            "content": "<CONTEXT_SUMMARY>x</CONTEXT_SUMMARY>"})
    assert ta.latest_auto_compaction([tagged]) is tagged
    assert ta.latest_auto_compaction([ta.parse_step(user(1, "a"))]) is None


def test_build_digest_handles_agy_steps_and_cursor(tmp_path):
    path = write(tmp_path / "t.jsonl", user(0, "fix it"),
                 model(1, "Working", [{"name": "view_file", "args": {"AbsolutePath": "/x"}}]),
                 user(2, "thanks"))
    digest = build_digest(path)
    assert "[user] fix it" in digest.text
    assert "[assistant] Working" in digest.text
    assert "[assistant tool: view_file]" in digest.text
    assert "/x" not in digest.text
    assert digest.last_uuid == "agy-step-2"
    assert digest.n_events == 3
    after = build_digest(path, after_uuid="agy-step-1")
    assert after.text == "[user] thanks"


def test_read_window_treats_agy_steps_as_identities(tmp_path):
    path = write(tmp_path / "t.jsonl", user(0, "first"), model(1, "second"))
    window = read_window(path)
    assert "[user] first" in window.text and "[assistant] second" in window.text
    roles = [e["role"] for e in window.events]
    assert roles == ["user", "assistant"]
    assert window.events[0]["timestamp"] == "2026-09-05T23:14:37Z"


def test_transcript_state_uses_step_identity_as_cursor(tmp_path):
    path = write(tmp_path / "t.jsonl", user(0, "a"), model(1, "b"), user(4, "c"))
    cursor, fingerprint = capture._transcript_state(str(path))
    assert cursor == "agy-step-4"
    assert fingerprint.startswith("sha256:")
