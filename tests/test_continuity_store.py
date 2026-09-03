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
