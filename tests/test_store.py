import psycopg
import pytest

from agentic_rag import store
from agentic_rag.store import EdgeSpec
from agentic_rag.embed import EmbedError


@pytest.fixture
def seeded(conn):
    conn.execute("INSERT INTO domains(name, description) VALUES ('nature','')")
    conn.commit()
    return conn


def _save(conn, **kw):
    defaults = dict(title="Photosynthesis", body="# Photosynthesis\n\nConvert sunlight.",
                    domain="nature", dtype="concept")
    defaults.update(kw)
    return store.save_document(conn, _no_embed_cfg(), **defaults)


def _no_embed_cfg():
    # points at a dead port -> embedding unavailable -> NULL embeddings path
    from agentic_rag.config import Config
    return Config(db_name="agentic_rag_test", ollama_url="http://localhost:1")


def test_save_creates_document_chunks_audit(seeded):
    res = _save(seeded)
    assert res.created and res.slug == "photosynthesis" and res.n_chunks == 1
    doc = seeded.execute("SELECT * FROM documents WHERE id = %s",
                         (res.doc_id,)).fetchone()
    assert doc["domain"] == "nature" and doc["status"] == "active"
    n = seeded.execute("SELECT count(*) AS n FROM audit_log").fetchone()["n"]
    assert n == 1


def test_save_unknown_domain_raises(seeded):
    with pytest.raises(ValueError, match="unknown domain"):
        _save(seeded, domain="nope")


def test_save_redacts_secrets(seeded):
    res = _save(seeded, body="my key sk-abc123DEF456ghi789jkl012 is here")
    assert res.redactions == 1
    body = seeded.execute("SELECT body FROM documents WHERE id = %s",
                          (res.doc_id,)).fetchone()["body"]
    assert "sk-abc" not in body and "[REDACTED]" in body


def test_save_slug_collision_uniquified(seeded):
    a = _save(seeded)
    b = _save(seeded, body="different")
    assert a.slug == "photosynthesis" and b.slug == "photosynthesis-2"


def test_update_replaces_chunks(seeded):
    a = _save(seeded)
    b = store.save_document(
        seeded, _no_embed_cfg(), title="Photosynthesis",
        body="# New\n\nBody.", domain="nature", dtype="concept",
        doc_id=a.doc_id,
    )
    assert not b.created and b.doc_id == a.doc_id
    rows = seeded.execute("SELECT content FROM chunks WHERE document_id = %s",
                          (a.doc_id,)).fetchall()
    assert len(rows) == 1 and "New" in rows[0]["content"]


def test_edges_created_and_dangling_resolved(seeded):
    a = _save(seeded, edges=[EdgeSpec("depends_on", "chlorophyll",
                                      evidence="quote", confidence="high")])
    assert a.n_edges == 1
    dangling = seeded.execute(
        "SELECT * FROM edges WHERE dst_id IS NULL").fetchall()
    assert len(dangling) == 1
    # now the target appears -> dangling edge resolves
    b = _save(seeded, title="Chlorophyll", body="x")
    assert b.slug == "chlorophyll" and b.edges_resolved == 1
    assert seeded.execute(
        "SELECT count(*) AS n FROM edges WHERE dst_id IS NULL").fetchone()["n"] == 0


def test_embedding_unavailable_warns_and_queues(seeded):
    res = _save(seeded)
    assert any("embedding" in w for w in res.warnings)
    q = seeded.execute(
        "SELECT * FROM mining_queue WHERE kind = 'embed'").fetchall()
    assert len(q) == 1


def test_get_document_by_slug_with_edges(seeded):
    _save(seeded, title="Chlorophyll", body="x")
    _save(seeded, edges=[EdgeSpec("references", "chlorophyll")])
    doc = store.get_document(seeded, "photosynthesis")
    assert doc["title"] == "Photosynthesis"
    assert doc["edges_out"][0].peer_slug == "chlorophyll"
    assert store.get_document(seeded, "does-not-exist") is None
    # peer of an IN-edge is the SOURCE document
    target = store.get_document(seeded, "chlorophyll")
    assert target["edges_in"][0].peer_slug == "photosynthesis"


def test_failed_save_rolls_back_and_connection_stays_usable(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        _save(seeded, edges=[EdgeSpec("not-a-predicate", "x")])
    # rollback happened: no half-written document, connection not aborted
    n = seeded.execute("SELECT count(*) AS n FROM documents").fetchone()["n"]
    assert n == 0


def test_edge_upsert_preserves_evidence(seeded):
    a = _save(seeded, edges=[EdgeSpec("references", "chlorophyll",
                                      evidence="quoted proof", confidence="high")])
    store.save_document(seeded, _no_embed_cfg(), title="Photosynthesis",
                        body="v2", domain="nature", dtype="concept",
                        doc_id=a.doc_id,
                        edges=[EdgeSpec("references", "chlorophyll")])
    row = seeded.execute("SELECT evidence, confidence FROM edges").fetchone()
    assert row["evidence"] == "quoted proof"
    assert row["confidence"] == "high"


def test_edge_evidence_is_redacted(seeded):
    _save(seeded, edges=[EdgeSpec("references", "target",
                                  evidence="key sk-abc123DEF456ghi789jkl012")])
    ev = seeded.execute("SELECT evidence FROM edges").fetchone()["evidence"]
    assert "sk-abc" not in ev and "[REDACTED]" in ev


def test_save_strips_secrets_from_meta_and_provenance(seeded):
    res = _save(
        seeded,
        meta={"api_key": "abcdef123456", "note": "ok"},
        provenance={"origin": "session-mining",
                    "quote": "token=verysecretvalue99"},
    )
    row = seeded.execute(
        "SELECT meta, provenance FROM documents WHERE id = %s",
        (res.doc_id,)).fetchone()
    assert row["meta"]["api_key"] == "[REDACTED]"
    assert row["meta"]["note"] == "ok"
    assert "verysecretvalue99" not in row["provenance"]["quote"]
    assert res.redactions >= 2


def test_save_mark_verified_stamps_verified_at(seeded):
    res = _save(seeded, mark_verified=True)
    row = seeded.execute(
        "SELECT verified_at FROM documents WHERE id = %s",
        (res.doc_id,)).fetchone()
    assert row["verified_at"] is not None


def test_save_default_does_not_stamp_verified_at(seeded):
    res = _save(seeded)
    row = seeded.execute(
        "SELECT verified_at FROM documents WHERE id = %s",
        (res.doc_id,)).fetchone()
    assert row["verified_at"] is None


def test_update_with_mark_verified_refreshes_stamp(seeded):
    res = _save(seeded)
    _save(seeded, doc_id=res.doc_id, body="b corrected", mark_verified=True)
    row = seeded.execute(
        "SELECT verified_at, body FROM documents WHERE id = %s",
        (res.doc_id,)).fetchone()
    assert row["verified_at"] is not None
    assert row["body"] == "b corrected"


def test_reembed_document_embeds_and_audits(seeded, monkeypatch):
    res = _save(seeded)                     # dead Ollama → NULL embeddings
    monkeypatch.setattr(
        store, "embed_texts",
        lambda texts, c: [[0.5] * c.embed_dim for _ in texts])
    n = store.reembed_document(seeded, _no_embed_cfg(), res.doc_id)
    assert n >= 1
    row = seeded.execute(
        "SELECT count(*) AS n FROM chunks WHERE document_id = %s"
        " AND embedding IS NOT NULL", (res.doc_id,)).fetchone()
    assert row["n"] == n
    audits = seeded.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op = 'reembed'"
        " AND document_id = %s", (res.doc_id,)).fetchone()
    assert audits["n"] == 1


def test_reembed_document_raises_when_ollama_down(seeded, monkeypatch):
    res = _save(seeded)
    def down(texts, c):
        raise EmbedError("down")
    monkeypatch.setattr(store, "embed_texts", down)
    with pytest.raises(EmbedError):
        store.reembed_document(seeded, _no_embed_cfg(), res.doc_id)


def test_save_with_status_archived_excluded_from_search(seeded):
    res = _save(seeded, status="archived", title="Old Index")
    row = seeded.execute("SELECT status FROM documents WHERE id = %s",
                         (res.doc_id,)).fetchone()
    assert row["status"] == "archived"


def test_save_rejects_refuted_status(seeded):
    with pytest.raises(ValueError, match="status"):
        _save(seeded, status="refuted")


def test_set_domain_moves_doc_audits_and_keeps_chunks(seeded):
    seeded.execute(
        "INSERT INTO domains(name, description) VALUES ('programming','')")
    seeded.commit()
    res = _save(seeded)
    before = seeded.execute("SELECT count(*) AS n FROM chunks"
                            " WHERE document_id = %s", (res.doc_id,)).fetchone()["n"]
    store.set_domain(seeded, res.doc_id, "programming", actor="migration")
    doc = seeded.execute("SELECT domain FROM documents WHERE id = %s",
                         (res.doc_id,)).fetchone()
    after = seeded.execute("SELECT count(*) AS n FROM chunks"
                           " WHERE document_id = %s", (res.doc_id,)).fetchone()["n"]
    assert doc["domain"] == "programming" and before == after
    ops = [r["op"] for r in seeded.execute("SELECT op FROM audit_log").fetchall()]
    assert "set_domain" in ops


def test_set_domain_unknown_domain_raises(seeded):
    res = _save(seeded)
    with pytest.raises(ValueError, match="unknown domain"):
        store.set_domain(seeded, res.doc_id, "nope")


def test_update_without_status_keeps_archived(seeded):
    # MCP memory_save never passes status — an update must not silently
    # reactivate an archived document
    res = _save(seeded, status="archived")
    _save(seeded, doc_id=res.doc_id, body="updated body")
    row = seeded.execute("SELECT status FROM documents WHERE id = %s",
                         (res.doc_id,)).fetchone()
    assert row["status"] == "archived"


def test_update_with_status_active_reactivates(seeded):
    res = _save(seeded, status="archived")
    _save(seeded, doc_id=res.doc_id, body="updated body", status="active")
    row = seeded.execute("SELECT status FROM documents WHERE id = %s",
                         (res.doc_id,)).fetchone()
    assert row["status"] == "active"
