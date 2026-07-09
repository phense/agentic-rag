from datetime import date, datetime, timedelta, timezone

from agentic_rag import pins


def _pin(body, *, priority=100, created=None, verified=None, scope="global"):
    return pins.PinInfo(
        id="00000000-0000-0000-0000-000000000000", document_id=None,
        body=body, scope=scope, priority=priority, active=True,
        created_at=created or datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_verified=verified)


def test_add_and_list_global_pin(conn):
    pid = pins.add_pin(conn, body="Always use uv, never pip.")
    got = pins.matching_pins(conn, "/anywhere")
    assert [p.id for p in got] == [pid]
    assert got[0].body == "Always use uv, never pip."


def test_add_pin_requires_body_or_document(conn):
    import pytest
    with pytest.raises(ValueError):
        pins.add_pin(conn)


def test_document_pin_derives_body_from_slug_and_title(conn):
    conn.execute("INSERT INTO domains(name) VALUES ('d')")
    doc = conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title)"
        " VALUES ('rule-x', 'd', 'lesson', 'Rule X') RETURNING id").fetchone()
    conn.commit()
    pid = pins.add_pin(conn, document_id=str(doc["id"]))
    got = pins.matching_pins(conn, None)
    assert got[0].body == "[[rule-x]] — Rule X"


def test_scope_path_prefix_matching(conn):
    pins.add_pin(conn, body="global one")
    pins.add_pin(conn, body="project one", scope="/Users/example/Agents/agentic-rag")
    pins.add_pin(conn, body="other project", scope="/Users/example/other")
    got = pins.matching_pins(conn, "/Users/example/Agents/agentic-rag/sub")
    assert {p.body for p in got} == {"global one", "project one"}


def test_unpin_deactivates_and_audits(conn):
    pid = pins.add_pin(conn, body="temp rule")
    assert pins.unpin(conn, pid) is True
    assert pins.matching_pins(conn, None) == []
    n = conn.execute(
        "SELECT count(*) AS n FROM audit_log WHERE op='pin_remove'"
    ).fetchone()["n"]
    assert n == 1
    assert pins.unpin(conn, pid) is False


def test_verify_pin_stamps_last_verified(conn):
    pid = pins.add_pin(conn, body="rule to verify")
    assert pins.verify_pin(conn, pid) is True
    got = pins.matching_pins(conn, None)
    assert got[0].last_verified is not None
    assert pins.unpin(conn, pid) is True
    assert pins.verify_pin(conn, pid) is False   # inactive pin -> no stamp


def test_deterministic_order_priority_then_created(conn):
    a = pins.add_pin(conn, body="late high", priority=10)
    b = pins.add_pin(conn, body="early low", priority=200)
    c = pins.add_pin(conn, body="second high", priority=10)
    got = pins.matching_pins(conn, None)
    assert [p.body for p in got] == ["late high", "second high", "early low"]


def test_render_marks_stale_and_never_truncates():
    today = date(2026, 7, 5)
    fresh = _pin("fresh rule",
                 verified=datetime(2026, 7, 1, tzinfo=timezone.utc))
    stale = _pin("old rule",
                 created=datetime(2026, 1, 1, tzinfo=timezone.utc))
    text, warnings = pins.render_pins([fresh, stale], stale_days=30,
                                      budget_chars=10_000, today=today)
    assert "fresh rule" in text and "old rule" in text
    assert "(unverified since 2026-01-01)" in text
    assert "unverified since" not in text.split("old rule")[0]
    assert warnings == []


def test_render_over_budget_warns_explicitly_but_keeps_all():
    many = [_pin(f"rule number {i} " + "x" * 80) for i in range(60)]
    text, warnings = pins.render_pins(many, stale_days=30, budget_chars=500)
    assert all(f"rule number {i}" in text for i in range(60))
    assert any("exceed" in w and "curate" in w for w in warnings)


def test_add_pin_rejects_prefixed_path_scope(conn):
    import pytest
    with pytest.raises(ValueError, match="invalid pin scope"):
        pins.add_pin(conn, body="rule", scope="path:/Users/example/x")


def test_add_pin_rejects_unknown_domain_scope(conn):
    import pytest
    with pytest.raises(ValueError, match="invalid pin scope"):
        pins.add_pin(conn, body="rule", scope="no-such-domain")


def test_add_pin_accepts_global_path_and_domain(conn):
    conn.execute("INSERT INTO domains(name, description) VALUES ('nature','')")
    conn.commit()
    assert pins.add_pin(conn, body="r1", scope="global")
    assert pins.add_pin(conn, body="r2", scope="/Users/example/Agents/x")
    assert pins.add_pin(conn, body="r3", scope="nature")
