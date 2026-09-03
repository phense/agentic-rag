import json

from agentic_rag.transcript import Digest, build_digest


def _write(tmp_path, events):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return p


def _user(uuid, text):
    return {"uuid": uuid, "type": "user",
            "message": {"role": "user", "content": text}}


def _assistant(uuid, blocks):
    return {"uuid": uuid, "type": "assistant",
            "message": {"role": "assistant", "content": blocks}}


def test_digest_keeps_prose_and_tool_names_not_results(tmp_path):
    p = _write(tmp_path, [
        _user("u1", "please fix the flaky test"),
        _assistant("a1", [
            {"type": "text", "text": "Looking at the test now."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]),
        {"uuid": "r1", "type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result",
             "content": "SECRET_OUTPUT sk-abcdefghijklmnop1234"}]}},
    ])
    d = build_digest(p)
    assert "please fix the flaky test" in d.text
    assert "Looking at the test now." in d.text
    assert "Bash" in d.text
    assert "SECRET_OUTPUT" not in d.text          # tool_result bodies excluded
    assert d.last_uuid == "r1"
    assert d.n_events == 3


def test_digest_resumes_after_uuid(tmp_path):
    p = _write(tmp_path, [
        _user("u1", "old turn already mined"),
        _user("u2", "new turn to mine"),
    ])
    d = build_digest(p, after_uuid="u1")
    assert "old turn" not in d.text
    assert "new turn to mine" in d.text
    assert d.last_uuid == "u2"


def test_unknown_after_uuid_falls_back_to_full_transcript(tmp_path):
    p = _write(tmp_path, [_user("u1", "only turn")])
    d = build_digest(p, after_uuid="vanished-uuid")
    assert "only turn" in d.text


def test_bad_lines_and_unknown_shapes_are_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        'not json at all\n'
        '{"uuid": "x1", "novel_field": {"deep": true}}\n'
        + json.dumps(_user("u1", "still mined")) + "\n"
        '{"uuid": "x2", "message": {"role": "assistant", "content": 42}}\n')
    d = build_digest(p)
    assert "still mined" in d.text
    assert d.last_uuid == "x2"


def test_missing_file_degrades_to_empty(tmp_path):
    d = build_digest(tmp_path / "nope.jsonl")
    assert d == Digest(text="", last_uuid=None, n_events=0)


def test_secrets_are_stripped_from_prose(tmp_path):
    p = _write(tmp_path, [_user("u1", "my key is sk-abcdefghijklmnop1234")])
    d = build_digest(p)
    assert "sk-abcdefghijklmnop1234" not in d.text
    assert "[REDACTED]" in d.text


def test_tool_use_slug_and_query_hints_are_kept(tmp_path):
    # grounding for mining: slugs/queries name EXISTING documents, so
    # contradictions and edges can reference them — but never tool inputs
    # in general (a Bash command is not a hint, it is a secret surface)
    p = _write(tmp_path, [_assistant("a1", [
        {"type": "tool_use", "name": "mcp__agentic-rag__memory_get",
         "input": {"id_or_slug": "old-claim"}},
        {"type": "tool_use", "name": "memory_search",
         "input": {"query": "photosynthesis", "k": 8}},
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "rm -rf /tmp/whatever"}},
        {"type": "tool_use", "name": "WebSearch",
         "input": {"query": "leaked search terms"}},
    ])])
    d = build_digest(p)
    assert "old-claim" in d.text
    assert "photosynthesis" in d.text
    assert "rm -rf" not in d.text
    # the gate is the tool NAME: a non-memory tool's `query` field must
    # never leak into the digest
    assert "leaked search terms" not in d.text


def test_truncated_utf8_degrades_instead_of_crashing(tmp_path):
    # a LIVE session file can end mid-multibyte-character; the digest must
    # degrade (skip the mangled line), never raise UnicodeDecodeError
    p = tmp_path / "t.jsonl"
    good = json.dumps(_user("u1", "still mined")).encode() + b"\n"
    p.write_bytes(good + b'{"uuid": "u2", "type": "user"' + b"\xe2\x82")
    d = build_digest(p)
    assert "still mined" in d.text
    assert d.n_events >= 1


def test_per_block_and_total_caps(tmp_path):
    p = _write(tmp_path, [_user(f"u{i}", f"block {i} " + "y" * 900)
                          for i in range(40)])
    d = build_digest(p, per_block=100, max_chars=1500)
    assert len(d.text) <= 1500
    assert "block 0" in d.text                     # head kept, deterministic


def test_tail_digest_honors_budget_smaller_than_omission_marker(tmp_path):
    p = _write(tmp_path, [_user("u1", "latest action " * 20)])

    d = build_digest(p, max_chars=10, keep="tail")

    assert len(d.text) <= 10


import os
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not list(Path.home().glob(".claude/projects/*/*.jsonl")),
    reason="no local Claude Code transcripts")
def test_canary_digest_of_a_real_transcript():
    """Format-drift canary (spec §12): the digest of a real local transcript
    must be non-empty and carry a last_uuid. If Claude Code changes its
    format, THIS test fails first — the parser itself must still not crash."""
    real = max(Path.home().glob(".claude/projects/*/*.jsonl"),
               key=os.path.getmtime)
    d = build_digest(real)
    assert d.n_events > 0
    assert d.last_uuid
    assert d.text.strip()
