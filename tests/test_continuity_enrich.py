import json
import subprocess

import pytest

from agentic_rag import jobs, worker
from agentic_rag.config import Config
from agentic_rag.continuity import enrich, store
from agentic_rag.continuity.model import CheckpointSnapshot, ENRICHMENT_FIELDS
from agentic_rag.llm import LLMUnavailableError


def _checkpoint(conn, *, session_id="s", cursor="u2"):
    return store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id=session_id, turn_id="turn-2", cursor=cursor,
        source="PreCompact", trigger="auto", cwd="/work/project",
        project_root="/work/project",
    ))


def _job(checkpoint_id, *, last_uuid="u1", transcript_path="/t"):
    return {
        "id": 1, "kind": "checkpoint_enrich", "session_id": "s",
        "transcript_path": transcript_path,
        "payload": {"checkpoint_id": checkpoint_id},
        "last_uuid": last_uuid, "attempts": 1,
    }


def _valid_enrichment(**overrides):
    data = {
        "goal": "Ship checkpoint enrichment",
        "success_criteria": ["Focused checks report success"],
        "instructions": ["Preserve the audited gateway"],
        "approvals": [],
        "decisions": ["Use the single writer"],
        "rejected_alternatives": [],
        "completed_steps": ["Captured deterministic state"],
        "remaining_steps": ["Integrate lifecycle hooks"],
        "files": ["agentic_rag/continuity/enrich.py"],
        "tests": [],
        "processes": [],
        "external_states": [],
        "blockers": [],
        "risks": ["volatile state requires revalidation"],
        "next_action": "Run the focused checks",
        "rag_slugs": [],
    }
    data.update(overrides)
    return data


def _transcript(path, *events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def _event(uuid, role, content):
    return {"uuid": uuid, "message": {"role": role, "content": content}}


def test_enrich_checkpoint_uses_delta_schema_and_audited_gateway(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    secret = "sk-abcdefghijklmnopqrstuv"
    _transcript(
        transcript,
        _event("u1", "user", "old context must be skipped"),
        _event("u2", "assistant", (
            f"new context credential {secret}. Pytest focused: PASSED. "
            "Worker   PID 42 was observed running. Provider login was "
            "observed healthy. Related memory [[checkpoint-continuity]]."
        )),
    )
    seen = {}
    expected = _valid_enrichment(
        tests=[
            "pytest focused: passed | evidence: pytest focused: passed",
        ],
        processes=[
            "worker pid 42 was observed running | evidence: "
            "worker pid 42 was observed running",
        ],
        external_states=[
            "provider login was observed healthy | evidence: "
            "provider login was observed healthy",
        ],
        rag_slugs=["checkpoint-continuity"],
    )

    def runner(cmd, **kwargs):
        seen["prompt"] = cmd[cmd.index("-p") + 1]
        seen["schema"] = json.loads(cmd[cmd.index("--json-schema") + 1])
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(expected), stderr="")

    cursor = enrich.enrich_checkpoint(
        conn, cfg, _job(checkpoint.id, transcript_path=str(transcript)), runner)

    assert cursor == "u2"
    assert "old context must be skipped" not in seen["prompt"]
    assert "new context" in seen["prompt"]
    assert secret not in seen["prompt"]
    assert "[REDACTED]" in seen["prompt"]
    assert set(seen["schema"]["properties"]) == set(ENRICHMENT_FIELDS)
    assert set(seen["schema"]["required"]) == set(ENRICHMENT_FIELDS)
    assert seen["schema"]["additionalProperties"] is False
    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    assert saved.enrichment == expected
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_enriched'"
    ).fetchone()["n"] == 1


def test_enrich_checkpoint_caps_digest_with_existing_mining_config(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "z" * 500))
    cfg2 = Config(
        db_name=cfg.db_name, mine_max_digest_chars=128,
        mine_per_block_chars=200,
    )
    seen = {}

    def runner(cmd, **kwargs):
        seen["prompt"] = cmd[cmd.index("-p") + 1]
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(_valid_enrichment()), stderr="")

    enrich.enrich_checkpoint(
        conn, cfg2, _job(checkpoint.id, last_uuid=None,
                         transcript_path=str(transcript)), runner)

    assert "z" * 90 in seen["prompt"]
    assert "[... earlier delta omitted ...]" in seen["prompt"]


def test_enrich_checkpoint_keeps_latest_action_when_digest_is_bounded(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(
        transcript,
        _event("u2", "user", "old context " * 100),
        _event("u3", "assistant", "NEXT ACTION run release-check now"),
    )
    cfg2 = Config(
        db_name=cfg.db_name, mine_max_digest_chars=128,
        mine_per_block_chars=500,
    )
    seen = {}

    def runner(cmd, **kwargs):
        seen["prompt"] = cmd[cmd.index("-p") + 1]
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(_valid_enrichment()), stderr="")

    cursor = enrich.enrich_checkpoint(
        conn, cfg2, _job(checkpoint.id, last_uuid=None,
                         transcript_path=str(transcript)), runner)

    assert cursor == "u3"
    assert "NEXT ACTION run release-check now" in seen["prompt"]
    assert "[... earlier delta omitted ...]" in seen["prompt"]


@pytest.mark.parametrize("unsafe", [
    _valid_enrichment(goal="transcript content copied verbatim"),
    _valid_enrichment(goal="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"),
])
def test_enrich_checkpoint_drops_unstorable_values_and_keeps_the_rest(
        conn, cfg, tmp_path, unsafe):
    # Issue #2: one transcript- or diff-shaped value must not void the other
    # fifteen fields.  The value is dropped and named in the warnings.
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "safe concise context"))

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(unsafe), stderr="")

    enrich.enrich_checkpoint(
        conn, cfg, _job(checkpoint.id, transcript_path=str(transcript)), runner)

    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    assert saved.enrichment["goal"] == ""
    assert saved.enrichment["next_action"] == "Run the focused checks"
    assert saved.warnings == (
        "enrichment goal: 1 item dropped (prohibited content)",)


def test_enrich_checkpoint_fails_loudly_on_a_credential(
        conn, cfg, tmp_path, monkeypatch):
    # A secret in the output means the digest's own redaction seam failed:
    # a pipeline defect that must reach last_error, never a warning line.
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "safe concise context"))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    monkeypatch.setattr(
        enrich.llm, "run_structured",
        lambda *args, **kwargs: _valid_enrichment(goal="api_key=super-secret-value"))

    assert worker.drain(conn, cfg) == {
        "done": 0, "failed": 1, "provider_unavailable": 0,
    }
    row = conn.execute("SELECT status, last_error FROM mining_queue").fetchone()
    assert row["status"] == "pending"
    assert row["last_error"] == "enrichment goal contains a secret"
    assert "super-secret-value" not in row["last_error"]
    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "snapshot"
    assert saved.enrichment == {}


def test_enrich_checkpoint_keeps_filenames_that_name_a_filtered_word(
        conn, cfg, tmp_path):
    # Issue #2, measured on a real Haiku run: paths are facts, prose that
    # names the payload is not.
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event(
        "u2", "assistant", "Resolved conflicts. uv run pytest: 622 tests passed."))
    output = _valid_enrichment(
        instructions=[
            "Resolve conflicts manually (transcript.py, config.py, llm.py)",
            "Do not paste the transcript into the checkpoint",
        ],
        risks=["deviations span transcript.py, config.py, and hooks/transcript"],
        blockers=["word filter (transcript|diff|body) blocks legitimate output"],
        tests=[
            "uv run pytest: 622 tests passed | evidence: 622 grün",
            "uv run pytest: 622 tests passed | evidence: uv run pytest: 622 tests passed",
        ],
    )

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(output), stderr="")

    enrich.enrich_checkpoint(
        conn, cfg, _job(checkpoint.id, transcript_path=str(transcript)), runner)

    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    assert saved.enrichment["instructions"] == [
        "Resolve conflicts manually (transcript.py, config.py, llm.py)"]
    assert saved.enrichment["risks"] == output["risks"]
    assert saved.enrichment["blockers"] == []
    assert saved.enrichment["tests"] == [output["tests"][1]]
    assert saved.enrichment["goal"] == "Ship checkpoint enrichment"
    assert saved.warnings == (
        "enrichment instructions: 1 item dropped (prohibited content)",
        "enrichment blockers: 1 item dropped (prohibited content)",
        "enrichment tests: 1 item dropped (lacks digest evidence)",
    )


@pytest.mark.parametrize(("field", "claim", "digest_text"), [
    ("tests", "All tests passed | evidence: pytest", "pytest was requested"),
    ("processes", "Worker is running | evidence: worker",
     "worker configuration changed"),
    ("external_states", "Provider is healthy | evidence: provider",
     "provider setting documented"),
])
def test_enrich_checkpoint_drops_ungrounded_volatile_claims(
        conn, cfg, tmp_path, monkeypatch, field, claim, digest_text):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", digest_text))
    output = _valid_enrichment(**{field: [claim]})
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    monkeypatch.setattr(
        enrich.llm, "run_structured", lambda *args, **kwargs: output)

    assert worker.drain(conn, cfg) == {
        "done": 1, "failed": 0, "provider_unavailable": 0,
    }
    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    assert saved.enrichment[field] == []
    assert saved.enrichment["goal"] == "Ship checkpoint enrichment"
    assert saved.warnings == (
        f"enrichment {field}: 1 item dropped (lacks digest evidence)",)


def test_enrich_checkpoint_drops_slug_without_accepted_digest_reference(
        conn, cfg, tmp_path, monkeypatch):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event(
        "u2", "user", "checkpoint-continuity appears only as plain prose"))
    output = _valid_enrichment(rag_slugs=["checkpoint-continuity"])
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    monkeypatch.setattr(
        enrich.llm, "run_structured", lambda *args, **kwargs: output)

    assert worker.drain(conn, cfg) == {
        "done": 1, "failed": 0, "provider_unavailable": 0,
    }
    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    assert saved.enrichment["rag_slugs"] == []
    assert saved.warnings == (
        "enrichment rag_slugs: 1 item dropped (no accepted digest reference)",)


@pytest.mark.parametrize(("reference", "accepted"), [
    ("not-a-slug: checkpoint-continuity", False),
    ("xslug: checkpoint-continuity", False),
    ("slug: checkpoint-continuity", True),
    ("id_or_slug: checkpoint-continuity", True),
    ("[[checkpoint-continuity]]", True),
])
def test_enrich_checkpoint_requires_exact_slug_reference_label(
        conn, cfg, tmp_path, reference, accepted):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", f"Related memory {reference}"))
    output = _valid_enrichment(rag_slugs=["checkpoint-continuity"])

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(output), stderr="")

    enrich.enrich_checkpoint(
        conn, cfg, _job(checkpoint.id, transcript_path=str(transcript)), runner)

    saved = store.get(conn, checkpoint.id)
    assert saved.quality == "enriched"
    if accepted:
        assert saved.enrichment["rag_slugs"] == ["checkpoint-continuity"]
        assert saved.warnings == ()
    else:
        assert saved.enrichment["rag_slugs"] == []
        assert saved.warnings == (
            "enrichment rag_slugs: 1 item dropped (no accepted digest reference)",)


def test_malformed_enrichment_uses_ordinary_retry_policy(
        conn, cfg, tmp_path, monkeypatch):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "continue implementation"))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    malformed = _valid_enrichment()
    malformed.pop("next_action")
    monkeypatch.setattr(
        enrich.llm, "run_structured",
        lambda *args, **kwargs: malformed,
    )

    assert worker.drain(conn, cfg) == {
        "done": 0, "failed": 1, "provider_unavailable": 0,
    }
    row = conn.execute("SELECT * FROM mining_queue").fetchone()
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert store.get(conn, checkpoint.id).quality == "snapshot"


def test_malformed_provider_output_does_not_persist_raw_content_or_secret(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "continue implementation"))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    secret = "sk-abcdefghijklmnopqrstuv"

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=f"raw conversation {secret}", stderr="")

    assert worker.drain(conn, cfg, runner=runner)["failed"] == 1
    error = conn.execute(
        "SELECT last_error FROM mining_queue"
    ).fetchone()["last_error"]
    assert "raw conversation" not in error
    assert secret not in error


def test_provider_outage_preserves_attempt_then_recovers_same_checkpoint(
        conn, cfg, tmp_path, monkeypatch):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event("u2", "user", "continue implementation"))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    calls = iter([LLMUnavailableError("codex login required"),
                  _valid_enrichment()])

    def run_structured(*args, **kwargs):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(enrich.llm, "run_structured", run_structured)
    cfg2 = Config(
        db_name=cfg.db_name, llm_provider="codex",
        provider_backoff_seconds=3600,
    )

    first = worker.drain(conn, cfg2)
    row = conn.execute("SELECT * FROM mining_queue").fetchone()
    assert first == {"done": 0, "failed": 0, "provider_unavailable": 1}
    assert (row["status"], row["attempts"]) == ("pending", 0)
    assert worker.provider_health.read_health().available is False
    assert store.get(conn, checkpoint.id).quality == "snapshot"

    conn.execute("UPDATE mining_queue SET next_attempt_at = now()")
    conn.commit()
    second = worker.drain(conn, cfg2)
    row = conn.execute("SELECT * FROM mining_queue").fetchone()
    assert second == {"done": 1, "failed": 0, "provider_unavailable": 0}
    assert (row["status"], row["attempts"], row["last_uuid"]) == (
        "done", 1, "u2",
    )
    assert store.get(conn, checkpoint.id).quality == "enriched"
    assert worker.provider_health.read_health().available is True


def test_empty_digest_completion_does_not_clear_unavailable_provider_health(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    missing_transcript = tmp_path / "missing.jsonl"
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(missing_transcript), after_cursor="u1",
    )
    worker.provider_health.record_failure("codex", "login required")
    cfg2 = Config(db_name=cfg.db_name, llm_provider="codex")

    assert worker.drain(conn, cfg2) == {
        "done": 1, "failed": 0, "provider_unavailable": 0,
    }

    row = conn.execute("SELECT status, last_uuid FROM mining_queue").fetchone()
    assert (row["status"], row["last_uuid"]) == ("done", "u1")
    assert store.get(conn, checkpoint.id).quality == "snapshot"
    assert worker.provider_health.read_health().available is False


def test_provider_success_without_new_cursor_clears_unavailable_health(
        conn, cfg, tmp_path):
    checkpoint = _checkpoint(conn)
    transcript = tmp_path / "session.jsonl"
    _transcript(transcript, _event(None, "user", "continue implementation"))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id="s",
        transcript_path=str(transcript), after_cursor="u1",
    )
    worker.provider_health.record_failure("claude", "login required")
    cfg2 = Config(db_name=cfg.db_name, llm_provider="claude")

    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(_valid_enrichment()), stderr="")

    assert worker.drain(conn, cfg2, runner=runner)["done"] == 1

    row = conn.execute("SELECT status, last_uuid FROM mining_queue").fetchone()
    assert (row["status"], row["last_uuid"]) == ("done", "u1")
    assert store.get(conn, checkpoint.id).quality == "enriched"
    assert worker.provider_health.read_health().available is True
