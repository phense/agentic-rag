"""Synthetic Codex rollout shapes; no private transcript content."""
import json

import pytest

from agentic_rag.transcript import build_digest
from agentic_rag.continuity.capture import _transcript_state


def record(payload, timestamp="2026-10-05T10:00:00Z"):
    return {"timestamp": timestamp, "type": "response_item", "payload": payload}


def message(role, text, **extra):
    return record({"type": "message", "role": role, "id": None,
                   "content": [{"type": "input_text" if role == "user" else "output_text",
                                "text": text}], **extra})


def write(path, *events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def test_codex_prose_cursor_and_capture_agree_without_message_ids(tmp_path):
    path = write(tmp_path / "rollout.jsonl", message("user", "ship the fix"),
                 message("assistant", "next action run focused checks"))
    digest = build_digest(path)
    assert digest.text == "[user] ship the fix\n[assistant] next action run focused checks"
    assert digest.last_uuid.startswith("codex-event-v1:")
    assert _transcript_state(str(path))[0] == digest.last_uuid


def test_codex_append_reuses_prior_checkpoint_cursor_and_excludes_old_delta(tmp_path):
    path = write(tmp_path / "rollout.jsonl", message("user", "old work"))
    cursor = build_digest(path).last_uuid
    assert cursor
    with path.open("a") as stream:
        stream.write(json.dumps(message("assistant", "new work")) + "\n")
    digest = build_digest(path, after_uuid=cursor)
    assert digest.text == "[assistant] new work"
    assert digest.last_uuid != cursor
    assert not build_digest(path, after_uuid=digest.last_uuid).text


def test_codex_ignores_internal_context_reasoning_outputs_and_duplicate_event_mirrors(tmp_path):
    path = write(tmp_path / "rollout.jsonl",
        message("system", "SYSTEM_PRIVATE"), message("developer", "DEVELOPER_PRIVATE"),
        message("assistant", "ANALYSIS_PRIVATE", phase="analysis"),
        record({"type": "reasoning", "summary": [{"text": "REASONING_PRIVATE"}],
                "encrypted_content": "ENCRYPTED_PRIVATE"}),
        record({"type": "function_call_output", "output": "RESULT_PRIVATE"}),
        record({"type": "custom_tool_call_output", "output": "RESULT_PRIVATE"}),
        {"type": "compacted", "payload": {"message": "SUMMARY_PRIVATE"}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "visible"}},
        message("assistant", "visible", phase="final"))
    assert build_digest(path).text == "[assistant] visible"


def test_codex_tool_names_memory_hints_and_redaction(tmp_path):
    secret = "sk-abcdefghijklmnop1234"
    path = write(tmp_path / "rollout.jsonl", message("user", "key " + secret),
        record({"type": "function_call", "name": "exec_command",
                "arguments": json.dumps({"cmd": "COMMAND_PRIVATE"})}),
        record({"type": "custom_tool_call", "name": "apply_patch", "input": "PATCH_PRIVATE"}),
        record({"type": "function_call", "name": "mcp__agentic_rag__memory_get",
                "arguments": json.dumps({"id_or_slug": "old-claim", "other": "ARG_PRIVATE"})}),
        record({"type": "function_call", "name": "web_search",
                "arguments": json.dumps({"query": "QUERY_PRIVATE"})}),
        record({"type": "function_call", "name": "memory_search",
                "arguments": json.dumps({"query": secret})}))
    text = build_digest(path).text
    assert "[user] key [REDACTED]" in text
    assert "[assistant tool: exec_command]" in text
    assert "[assistant tool: apply_patch]" in text
    assert "mcp__agentic_rag__memory_get old-claim" in text
    assert "memory_search [REDACTED]" in text
    for private in (secret, "COMMAND_PRIVATE", "PATCH_PRIVATE", "ARG_PRIVATE", "QUERY_PRIVATE"):
        assert private not in text


@pytest.mark.parametrize("payload", [None, [], 42, {"type": "message", "role": "user", "content": 42},
    {"type": "message", "role": "user", "content": [42, {"type": "input_text", "text": 42}]},
    {"type": "function_call", "name": "memory_get", "arguments": "bad-json"}])
def test_codex_malformed_payloads_degrade(tmp_path, payload):
    path = write(tmp_path / "rollout.jsonl", record(payload), message("user", "still usable"))
    assert "still usable" in build_digest(path).text


def test_codex_digest_limits_keep_latest_action(tmp_path):
    path = write(tmp_path / "rollout.jsonl", message("user", "old " * 300),
                 message("assistant", "next action verify recovery"))
    text = build_digest(path, max_chars=80, per_block=100, keep="tail").text
    assert len(text) <= 80
    assert "next action verify recovery" in text


def test_codex_metadata_tail_and_partial_record_do_not_displace_usable_cursor(tmp_path):
    path = write(tmp_path / "rollout.jsonl", message("user", "latest complete"))
    cursor = build_digest(path).last_uuid
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n")
        stream.write('{"type":"response_item","payload":')
    assert cursor
    assert build_digest(path).last_uuid == cursor
    assert _transcript_state(str(path))[0] == cursor
