import threading

import psycopg
import pytest

from agentic_rag import db
from agentic_rag.continuity import store
from agentic_rag.continuity.model import CheckpointSnapshot


def snapshot(**changes) -> CheckpointSnapshot:
    values = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "cursor": "cursor-1",
        "source": "PreCompact",
        "trigger": "auto",
        "cwd": "/work/project",
        "project_root": "/work/project",
        "transcript_fingerprint": "sha256:abc",
        "git": {"branch": "main", "head": "abc123"},
        "artifacts": ("AGENTS.md", "docs/superpowers/plans/plan.md"),
        "warnings": ("git status truncated",),
    }
    values.update(changes)
    return CheckpointSnapshot(**values)


def test_checkpoint_upsert_is_idempotent_and_audited(conn):
    snap = snapshot(session_id="s1", turn_id="t1", cursor="u7")
    first = store.upsert_snapshot(conn, snap)
    second = store.upsert_snapshot(conn, snap)

    assert second.id == first.id
    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints"
    ).fetchone()["n"] == 1
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op='checkpoint_snapshot'"
    ).fetchone()["n"] == 1
    saved = store.get(conn, first.id)
    assert saved is not None
    assert saved.git == {"branch": "main", "head": "abc123"}
    assert saved.references == ("AGENTS.md", "docs/superpowers/plans/plan.md")
    assert saved.warnings == ("git status truncated",)


def test_new_cursor_supersedes_without_deleting(conn):
    old = store.upsert_snapshot(conn, snapshot(cursor="u7"))
    new = store.upsert_snapshot(conn, snapshot(cursor="u8"))

    assert store.get(conn, old.id).state == "superseded"
    assert store.get(conn, new.id).state == "open"
    assert conn.execute(
        "SELECT count(*) AS n FROM continuation_checkpoints"
    ).fetchone()["n"] == 2


def test_concurrent_new_cursors_leave_one_open_checkpoint(dbinit, cfg, conn):
    """The first session scan pauses while it holds the real DB lock.

    Without a per-session advisory lock, the second connection completes its
    own empty-session scan and inserts before the first transaction continues,
    leaving two open rows.  The test uses two independent psycopg connections,
    not a mocked database or a timing-dependent race.
    """
    first_ready = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    errors = []

    class PauseAfterSessionScan:
        def __init__(self, real_conn):
            self.real_conn = real_conn

        def execute(self, query, *args, **kwargs):
            cursor = self.real_conn.execute(query, *args, **kwargs)
            if "FOR UPDATE" in query:
                first_ready.set()
                assert release_first.wait(timeout=3)
            return cursor

        def __getattr__(self, name):
            return getattr(self.real_conn, name)

    first_conn = db.connect(cfg, role="owner")
    second_conn = db.connect(cfg, role="owner")

    def save_first():
        try:
            store.upsert_snapshot(PauseAfterSessionScan(first_conn), snapshot(cursor="u7"))
        except BaseException as exc:  # recorded so cleanup cannot hide a thread failure
            errors.append(exc)

    def save_second():
        try:
            store.upsert_snapshot(second_conn, snapshot(cursor="u8"))
        except BaseException as exc:  # recorded so cleanup cannot hide a thread failure
            errors.append(exc)
        finally:
            second_finished.set()

    first = threading.Thread(target=save_first)
    second = threading.Thread(target=save_second)
    try:
        first.start()
        assert first_ready.wait(timeout=3)
        second.start()
        blocked_by_session_lock = not second_finished.wait(timeout=0.2)
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)

        assert blocked_by_session_lock
        assert not first.is_alive() and not second.is_alive()
        assert errors == []
        rows = conn.execute(
            "SELECT state FROM continuation_checkpoints WHERE session_id = 'session-1'"
        ).fetchall()
        assert sorted(row["state"] for row in rows) == ["open", "superseded"]
    finally:
        release_first.set()
        first.join(timeout=3)
        second.join(timeout=3)
        first_conn.close()
        second_conn.close()


def test_replayed_superseded_cursor_cannot_replace_newer_open_checkpoint(conn):
    old = store.upsert_snapshot(conn, snapshot(cursor="u7"))
    new = store.upsert_snapshot(conn, snapshot(cursor="u8"))

    replayed = store.upsert_snapshot(conn, snapshot(cursor="u7"))

    assert replayed.id == old.id
    assert store.get(conn, old.id).state == "superseded"
    assert store.get(conn, new.id).state == "open"
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_snapshot'"
    ).fetchone()["n"] == 2


def test_enrichment_and_compaction_are_audited(conn):
    checkpoint = store.upsert_snapshot(conn, snapshot())

    enriched = store.apply_enrichment(
        conn, checkpoint.id, {"goal": "ship continuity", "tests": ["pytest"]}
    )
    assert enriched.quality == "enriched"
    assert enriched.enrichment == {"goal": "ship continuity", "tests": ["pytest"]}
    assert store.mark_compacted(conn, checkpoint.session_id, checkpoint.cursor)
    assert store.mark_compacted(conn, checkpoint.session_id, checkpoint.cursor)
    assert store.get(conn, checkpoint.id).compacted_at is not None
    assert not store.mark_compacted(conn, "missing", checkpoint.cursor)
    rows = conn.execute(
        "SELECT op, summary, document_id FROM audit_log "
        "WHERE op LIKE 'checkpoint_%' ORDER BY id"
    ).fetchall()
    assert [row["op"] for row in rows] == [
        "checkpoint_snapshot", "checkpoint_enriched", "checkpoint_compacted"
    ]
    assert all(row["document_id"] is None for row in rows)
    assert all(str(checkpoint.id) in row["summary"] for row in rows)


@pytest.mark.parametrize("enrichment", [
    {"transcript": "verbatim transcript"},
    {"goal": "transcript content must not be stored"},
    {"diff": "diff --git a/secret b/secret"},
    {"goal": "diff --git a/secret b/secret"},
    {"body": "copied body"},
    {"api_key": "sk-abcdefghijklmnopqrstuv"},
    {"goal": "password=super-secret-value"},
    {"not_in_the_contract": "unknown"},
    {"goal": ["not a string"]},
    {"tests": "not a list"},
    {"goal": "x" * 2_001},
])
def test_enrichment_rejects_unsafe_or_oversized_payload_before_sql(conn, enrichment):
    checkpoint = store.upsert_snapshot(conn, snapshot())

    with pytest.raises(ValueError):
        store.apply_enrichment(conn, checkpoint.id, enrichment)

    unchanged = store.get(conn, checkpoint.id)
    assert unchanged.quality == "snapshot"
    assert unchanged.enrichment == {}
    assert conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'checkpoint_enriched'"
    ).fetchone()["n"] == 0


def test_enrichment_rejects_total_payload_over_the_byte_limit_before_sql(conn):
    checkpoint = store.upsert_snapshot(conn, snapshot())
    enrichment = {
        "goal": "x" * 2_000,
        "next_action": "x" * 2_000,
        "tests": ["x" * 2_000] * 7,
    }

    with pytest.raises(ValueError, match="byte limit"):
        store.apply_enrichment(conn, checkpoint.id, enrichment)

    assert store.get(conn, checkpoint.id).enrichment == {}


@pytest.mark.parametrize("enrichment", [
    {"goal": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"},
    {"tests": ["--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new"]},
    {"goal": "--- old.py\n+++ new.py\n@@ -1 +1 @@\n-old\n+new"},
    {"goal": "***************\n*** 1,2 ****\n-old\n--- 1,2 ----\n+new"},
    {"goal": "user: Please implement the change.\nassistant: I will inspect it."},
    {"next_action": (
        '{"role":"user","content":"Please implement the change."}\n'
        '{"role":"assistant","content":"I will inspect it."}'
    )},
])
def test_enrichment_rejects_structural_diff_and_dialogue_payloads(conn, enrichment):
    checkpoint = store.upsert_snapshot(conn, snapshot())

    with pytest.raises(ValueError, match="prohibited content"):
        store.apply_enrichment(conn, checkpoint.id, enrichment)

    assert store.get(conn, checkpoint.id).enrichment == {}


def test_enrichment_allows_a_single_user_label_in_ordinary_short_prose(conn):
    checkpoint = store.upsert_snapshot(conn, snapshot())

    enriched = store.apply_enrichment(
        conn, checkpoint.id, {"goal": "The user: admin owns this next action."}
    )

    assert enriched.enrichment == {"goal": "The user: admin owns this next action."}


def test_enrichment_allows_header_like_short_prose_without_a_unified_hunk(conn):
    checkpoint = store.upsert_snapshot(conn, snapshot())

    enriched = store.apply_enrichment(
        conn, checkpoint.id, {"goal": "--- old.py\n+++ new.py\nReview the names."}
    )

    assert enriched.enrichment["goal"].endswith("Review the names.")


def test_latest_selectors_only_return_open_checkpoints(conn):
    first = store.upsert_snapshot(conn, snapshot(cursor="first"))
    second = store.upsert_snapshot(conn, snapshot(cursor="second"))
    other = store.upsert_snapshot(
        conn, snapshot(session_id="other", cursor="other", project_root="/work/other")
    )

    assert store.latest_for_session(conn, first.session_id).id == second.id
    assert store.latest_for_project(conn, "/work/project").id == second.id
    assert store.latest_for_project(conn, "/work/other").id == other.id
    assert store.latest_for_session(conn, "missing") is None


@pytest.mark.parametrize("field", ["session_id", "cursor"])
def test_snapshot_rejects_blank_identity_before_sql(field):
    values = {field: "   "}
    with pytest.raises(ValueError, match=field):
        snapshot(**values)


def test_model_rejects_unknown_lifecycle_values():
    with pytest.raises(ValueError, match="state"):
        store.Checkpoint(
            id="00000000-0000-0000-0000-000000000000",
            session_id="s",
            turn_id=None,
            cursor="c",
            source="PreCompact",
            trigger=None,
            cwd=None,
            project_root=None,
            transcript_fingerprint=None,
            git={},
            snapshot={},
            enrichment={},
            references=(),
            warnings=(),
            state="unknown",
            quality="snapshot",
            compacted_at=None,
            created_at=None,
            updated_at=None,
        )


def test_checkpoint_schema_allows_only_known_lifecycle_values(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO continuation_checkpoints(session_id, cursor, source, state)"
            " VALUES ('s', 'c', 'PreCompact', 'wrong')"
        )


def test_writer_can_mutate_checkpoints_and_reader_can_only_select(dbinit, cfg, conn):
    writer = db.connect(cfg, role="writer")
    try:
        checkpoint = store.upsert_snapshot(writer, snapshot())
        assert store.apply_enrichment(writer, checkpoint.id, {"goal": "g"}).quality == "enriched"
    finally:
        writer.close()

    reader = db.connect(cfg, role="reader")
    try:
        assert reader.execute(
            "SELECT count(*) AS n FROM continuation_checkpoints"
        ).fetchone()["n"] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute(
                "INSERT INTO continuation_checkpoints(session_id, cursor, source)"
                " VALUES ('r', 'c', 'PreCompact')"
            )
    finally:
        reader.close()
