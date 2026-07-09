import io
import json

from agentic_rag.hooks import prompt_recall


def _run(payload):
    out = io.StringIO()
    prompt_recall.run(payload, out)
    raw = out.getvalue()
    if not raw:
        return None
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


def test_detects_python_traceback():
    sig = prompt_recall.detect_signature(
        "why does this happen?\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 3\n'
        "ValueError: dimension mismatch")
    assert sig is not None
    assert "ValueError" in sig


def test_detects_file_line_reference():
    assert prompt_recall.detect_signature(
        "tests fail at agentic_rag/embed.py:33 again") is not None


def test_plain_question_never_fires():
    assert prompt_recall.detect_signature(
        "how should we structure the mining module?") is None
    assert prompt_recall.detect_signature("") is None


def test_tokens_to_tsquery_sanitizes():
    q = prompt_recall.tokens_to_tsquery(
        "ValueError: dimension mismatch at embed.py:33 <weird&chars>")
    parts = q.split(" | ")
    assert "ValueError" in parts and "dimension" in parts
    assert all(t.replace("_", "").isalnum() for t in parts)


def _seed_signal(conn, slug, signal_text):
    conn.execute("INSERT INTO domains(name) VALUES ('d')"
                 " ON CONFLICT DO NOTHING")
    doc = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body)"
        " VALUES (%s, 'd', 'signal', %s, %s) RETURNING id",
        (slug, slug, f"lesson body\n\n## Signal\n\n{signal_text}")
    ).fetchone()
    conn.execute(
        "INSERT INTO chunks(document_id, idx, content)"
        " VALUES (%s, 0, %s)", (doc["id"], f"lesson body {signal_text}"))
    conn.commit()


def test_recall_injects_pointer_on_signal_match(conn, hook_env):
    _seed_signal(conn, "jetsam-oom-lesson", "jetsam killed process")
    ctx = _run({"prompt": "help!\nError: jetsam killed process 4432",
                "hook_event_name": "UserPromptSubmit"})
    assert ctx is not None
    assert "[[jetsam-oom-lesson]]" in ctx
    assert "advisory" in ctx.lower()


def test_no_injection_without_error_signature(conn, hook_env):
    _seed_signal(conn, "some-signal", "whatever text")
    assert _run({"prompt": "please refactor the worker"}) is None


def test_no_injection_when_nothing_matches(conn, hook_env):
    assert _run({"prompt": "Error: totally novel failure xyzzy"}) is None


def test_matching_pin_is_injected(conn, hook_env):
    from agentic_rag import pins
    pins.add_pin(conn, body="On jetsam errors: check Ollama RAM first.")
    ctx = _run({"prompt": "Error: jetsam killed process again"})
    assert ctx is not None
    assert "check Ollama RAM first" in ctx


def test_db_down_is_silent(hook_env):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    assert _run({"prompt": "Error: anything at all"}) is None
