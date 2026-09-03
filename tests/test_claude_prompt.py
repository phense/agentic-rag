from agentic_rag.integrations.claude import prompt


def test_claude_compact_prompt_is_versioned_bounded_and_reference_oriented():
    text = prompt.compact_prompt_text()

    assert text.startswith("# Claude compact continuation instructions")
    assert "Version: 1.0" in text
    assert len(text) <= prompt.MAX_PROMPT_CHARS
    assert "agentic-rag checkpoint:" in text
    assert "[[slug]]" in text
    assert "SessionStart" in text
    for forbidden in ("transcript", "diff", "credential"):
        assert forbidden in text  # named only as things to omit
    assert "Do not copy" in text
