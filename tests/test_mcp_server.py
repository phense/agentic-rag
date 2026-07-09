import asyncio
import json

from agentic_rag import mcp_server, pins


def _seed(conn):
    conn.execute("INSERT INTO domains(name, description)"
                 " VALUES ('d', 'test domain')")
    doc = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, body)"
        " VALUES ('alpha', 'd', 'concept', 'Alpha', 'alpha body text')"
        " RETURNING id").fetchone()
    conn.execute(
        "INSERT INTO chunks(document_id, idx, content)"
        " VALUES (%s, 0, 'alpha body text searchable')", (doc["id"],))
    conn.commit()
    return str(doc["id"])


def test_tool_names_readonly_gating():
    rw = mcp_server.tool_names(readonly=False)
    ro = mcp_server.tool_names(readonly=True)
    assert "memory_search" in rw and "memory_search" in ro
    assert "memory_save" in rw and "memory_save" not in ro
    assert "memory_pin" not in ro and "memory_unpin" not in ro


def test_build_server_registers_gated_tools():
    s = mcp_server.build_server(readonly=False)
    names = {t.name for t in asyncio.run(s.list_tools())}
    assert {"memory_domains", "memory_search", "memory_get",
            "memory_neighbors", "memory_path", "memory_timeline",
            "memory_save", "memory_pin", "memory_unpin"} <= names
    ro = {t.name for t in asyncio.run(
        mcp_server.build_server(readonly=True).list_tools())}
    assert "memory_save" not in ro


def test_save_tool_description_carries_verified_instruction():
    s = mcp_server.build_server(readonly=False)
    tools = {t.name: t for t in asyncio.run(s.list_tools())}
    assert "mark_verified" in tools["memory_save"].description
    assert "explicit" in tools["memory_pin"].description.lower()


def test_memory_domains_and_search_roundtrip(conn, hook_env):
    _seed(conn)
    doms = mcp_server.memory_domains()
    assert doms["domains"][0]["name"] == "d"
    res = mcp_server.memory_search("alpha searchable", k=3)
    assert res["results"], "seeded doc must be found"
    assert res["results"][0]["slug"] == "alpha"
    json.dumps(res)                       # JSON-safe by contract


def test_memory_get_resolves_slug_and_id(conn, hook_env):
    doc_id = _seed(conn)
    by_slug = mcp_server.memory_get("alpha")
    by_id = mcp_server.memory_get(doc_id)
    assert by_slug["document"]["slug"] == by_id["document"]["slug"] == "alpha"
    json.dumps(by_slug)


def test_memory_get_not_found(conn, hook_env):
    assert mcp_server.memory_get("nope")["error"] == "not found: nope"


def test_graph_tools_error_on_nonexistent_uuid(conn, hook_env):
    # a well-formed uuid with no document must be a not-found ERROR, never
    # a silent empty result (empty edges would read as "no relations")
    ghost = "00000000-0000-4000-8000-000000000000"
    assert "error" in mcp_server.memory_neighbors(ghost)
    assert "error" in mcp_server.memory_timeline(ghost)
    assert "error" in mcp_server.memory_path(ghost, ghost)


def test_memory_save_writes_through_gateway(conn, hook_env):
    _seed(conn)
    out = mcp_server.memory_save(
        title="Saved via MCP", body="knowledge", domain="d",
        dtype="lesson",
        edges=[{"predicate": "references", "dst_slug": "alpha",
                "evidence": "", "confidence": "high"}],
        mark_verified=True)
    assert out["created"] is True
    row = conn.execute(
        "SELECT verified_at FROM documents WHERE slug = %s",
        (out["slug"],)).fetchone()
    assert row["verified_at"] is not None
    edge = conn.execute(
        "SELECT evidence, created_by FROM edges WHERE dst_slug='alpha'"
    ).fetchone()
    assert edge["evidence"] is None       # "" → None (the COALESCE gate)
    assert edge["created_by"] == "claude"
    audit = conn.execute(
        "SELECT actor FROM audit_log WHERE op='save_document'"
        " ORDER BY id DESC").fetchone()
    assert audit["actor"] == "claude"


def test_memory_pin_and_unpin(conn, hook_env):
    out = mcp_server.memory_pin(body="User said: always X.")
    assert "pin_id" in out
    assert mcp_server.memory_unpin(out["pin_id"])["unpinned"] is True
    assert pins.matching_pins(conn, None) == []


def test_memory_neighbors_traverses(conn, hook_env):
    _seed(conn)
    beta = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('beta', 'd', 'concept', 'Beta') RETURNING id").fetchone()
    a = conn.execute("SELECT id FROM documents WHERE slug='alpha'").fetchone()
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, dst_slug, predicate, created_by)"
        " VALUES (%s, %s, 'beta', 'references', 'manual')",
        (a["id"], beta["id"]))
    conn.commit()
    out = mcp_server.memory_neighbors("alpha", depth=1)
    assert out["edges"], "edge must be found"
    assert out["edges"][0]["predicate"] == "references"
