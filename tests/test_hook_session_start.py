import io
import json

from agentic_rag import pins, provider_health
from agentic_rag.hooks import session_start


def _payload(**over):
    p = {"session_id": "s1", "cwd": "/Users/example/proj",
         "hook_event_name": "SessionStart", "source": "startup"}
    p.update(over)
    return p


def _run(payload):
    out = io.StringIO()
    session_start.run(payload, out)
    raw = out.getvalue()
    assert raw, "SessionStart must always inject something"
    return json.loads(raw)["hookSpecificOutput"]["additionalContext"]


def _seed(conn):
    conn.execute("INSERT INTO domains(name, description) VALUES"
                 " ('nature', 'field observations')")
    conn.commit()


def test_injects_pins_domains_and_project_docs(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    _seed(conn)
    pins.add_pin(conn, body="Never skip the calibration step.")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance)"
        " VALUES ('proj-note', 'nature', 'memory', 'Project note',"
        " '{\"project\": \"/Users/example/proj\"}')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance)"
        " VALUES ('other-note', 'nature', 'memory', 'Other note',"
        " '{\"project\": \"/elsewhere\"}')")
    conn.commit()
    ctx = _run(_payload())
    assert "Never skip the calibration step." in ctx
    assert "nature" in ctx and "field observations" in ctx
    assert "proj-note" in ctx
    assert "other-note" not in ctx


def test_project_docs_match_by_path_prefix(conn, hook_env, monkeypatch):
    # same semantics as pin scopes: a session in a SUBDIRECTORY of the
    # mined project still sees its knowledge
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    _seed(conn)
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance)"
        " VALUES ('proj-note', 'nature', 'memory', 'Project note',"
        " '{\"project\": \"/Users/example/proj\"}')")
    conn.commit()
    ctx = _run(_payload(cwd="/Users/example/proj/deeply/nested"))
    assert "proj-note" in ctx


def test_over_budget_pins_warn_but_all_injected(conn, hook_env, tmp_path,
                                                monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    hook_env.write_text(hook_env.read_text()
                        + "[hooks]\npin_budget_chars = 200\n")
    _seed(conn)
    for i in range(10):
        pins.add_pin(conn, body=f"rule {i} " + "x" * 50)
    ctx = _run(_payload())
    assert all(f"rule {i}" in ctx for i in range(10))
    assert "exceed" in ctx and "curate" in ctx


def test_surfaces_backup_warning_and_queue_errors(conn, hook_env, tmp_path,
                                                  monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    warn = tmp_path / "backup_warning"
    warn.write_text("2026-07-05 cloud backup dir unavailable")
    monkeypatch.setattr(session_start, "WARNING_STATE", warn)
    conn.execute(
        "INSERT INTO mining_queue(kind, status, attempts, last_error)"
        " VALUES ('mine', 'error', 3, 'llm timeout')")
    conn.commit()
    ctx = _run(_payload())
    assert "cloud backup dir unavailable" in ctx
    assert "1 queue job(s) in error state" in ctx


def test_surfaces_provider_remediation(conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(provider_health, "HEALTH_PATH", health)
    provider_health.record_failure(
        "codex", "login required", path=health)
    ctx = _run(_payload())
    assert "session mining provider codex unavailable" in ctx
    assert "codex login" in ctx


def test_recovered_provider_is_quiet(conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(provider_health, "HEALTH_PATH", health)
    provider_health.record_failure("codex", "login", path=health)
    provider_health.record_success("codex", path=health)
    ctx = _run(_payload())
    assert "session mining provider" not in ctx


def test_malformed_provider_health_is_visible(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    health = tmp_path / "provider-health.json"
    monkeypatch.setattr(provider_health, "HEALTH_PATH", health)
    health.write_text("not json")
    ctx = _run(_payload())
    assert "session mining provider unknown unavailable" in ctx
    assert "rag status" in ctx


def test_stale_curation_enqueues_and_spawns(conn, hook_env, monkeypatch):
    spawned = []
    monkeypatch.setattr(session_start.common, "spawn_worker",
                        lambda: spawned.append(True))
    _seed(conn)
    ctx = _run(_payload())          # no curation_pass audit row → stale
    row = conn.execute(
        "SELECT * FROM mining_queue WHERE kind = 'curate'").fetchone()
    assert row is not None
    assert spawned


def test_fresh_curation_does_not_enqueue(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    _seed(conn)
    conn.execute("INSERT INTO audit_log(actor, op, summary)"
                 " VALUES ('mining', 'curation_pass', 'fresh')")
    conn.commit()
    _run(_payload())
    assert conn.execute(
        "SELECT count(*) AS n FROM mining_queue WHERE kind='curate'"
    ).fetchone()["n"] == 0


def test_db_down_injects_visible_unavailability(hook_env):
    hook_env.write_text('[db]\nname = "no_such_database_xyz"\n')
    ctx = _run(_payload())
    assert "agentic-rag unavailable" in ctx      # fail closed, VISIBLY


def test_non_interactive_source_injects_nothing(conn, hook_env):
    out = io.StringIO()
    session_start.run(_payload(source="cron-thing"), out)
    assert out.getvalue() == ""
