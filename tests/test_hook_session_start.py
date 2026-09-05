import io
import json
import subprocess

from agentic_rag import pins, provider_health
from agentic_rag.continuity import store
from agentic_rag.continuity.model import CheckpointSnapshot
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


def _checkpoint(conn, *, session_id, project_root, cursor, goal):
    checkpoint = store.upsert_snapshot(conn, CheckpointSnapshot(
        session_id=session_id,
        turn_id="turn-7",
        cursor=cursor,
        source="PreCompact",
        trigger="auto",
        cwd=project_root,
        project_root=project_root,
    ))
    return store.apply_enrichment(conn, checkpoint.id, {
        "goal": goal,
        "next_action": f"Continue {goal}",
    })


def _git_project(tmp_path, name):
    project = tmp_path / name
    project.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(project)], check=True,
        capture_output=True, text=True,
    )
    nested = project / "nested"
    nested.mkdir()
    return project, nested


def test_injects_pins_domains_and_project_docs(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    _seed(conn)
    pins.add_pin(conn, body="Never skip the calibration step.")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance, project_scope)"
        " VALUES ('proj-note', 'nature', 'memory', 'Project note',"
        " '{\"project\": \"/Users/example/proj\"}', '/Users/example/proj')")
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance, project_scope)"
        " VALUES ('other-note', 'nature', 'memory', 'Other note',"
        " '{\"project\": \"/elsewhere\"}', '/elsewhere')")
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
        "INSERT INTO documents(slug, domain, dtype, title, provenance, project_scope)"
        " VALUES ('proj-note', 'nature', 'memory', 'Project note',"
        " '{\"project\": \"/Users/example/proj\"}', '/Users/example/proj')")
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


def test_provider_health_warning_sanitizes_provider_diagnostic(
        conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    secret = "sk-abcdefghijklmnop1234"
    monkeypatch.setattr(
        provider_health,
        "read_health",
        lambda: provider_health.ProviderHealth(secret, False),
    )

    ctx = _run(_payload())

    assert secret not in ctx
    assert "[REDACTED]" in ctx


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


def test_visible_session_start_failure_sanitizes_stdout_and_log(
        hook_env, tmp_path, monkeypatch):
    secret = "sk-abcdefghijklmnop1234"
    monkeypatch.setattr(
        session_start.db,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"connection failed with {secret}")),
    )
    stdout = io.StringIO()

    session_start.run(_payload(), stdout)

    assert secret not in stdout.getvalue()
    assert "[REDACTED]" in stdout.getvalue()
    logged = (tmp_path / "hooks.log").read_text()
    assert secret not in logged
    assert "[REDACTED]" in logged


def test_non_interactive_source_injects_nothing(conn, hook_env):
    out = io.StringIO()
    session_start.run(_payload(source="cron-thing"), out)
    assert out.getvalue() == ""


def test_compact_session_start_restores_same_session_checkpoint(
        conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    checkpoint = _checkpoint(
        conn,
        session_id="s1",
        project_root="/Users/example/proj",
        cursor="event-9",
        goal="finish lifecycle hooks",
    )

    ctx = _run(_payload(source="compact"))

    assert checkpoint.id in ctx
    assert "finish lifecycle hooks" in ctx


def test_startup_falls_back_to_same_canonical_project(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    project, nested = _git_project(tmp_path, "project")
    checkpoint = _checkpoint(
        conn,
        session_id="older-session",
        project_root=str(project.resolve()),
        cursor="event-project",
        goal="resume project work",
    )

    ctx = _run(_payload(
        session_id="new-session", cwd=str(nested), source="startup"))

    assert checkpoint.id in ctx
    assert "resume project work" in ctx


def test_same_session_wins_over_newer_same_project_checkpoint(
        conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    current = _checkpoint(
        conn,
        session_id="s1",
        project_root="/Users/example/proj",
        cursor="current-session",
        goal="continue this session",
    )
    other = _checkpoint(
        conn,
        session_id="other-session",
        project_root="/Users/example/proj",
        cursor="newer-project",
        goal="do not restore this checkpoint",
    )

    ctx = _run(_payload(source="startup"))

    assert current.id in ctx
    assert other.id not in ctx


def test_compact_does_not_fall_back_to_another_session(
        conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    other = _checkpoint(
        conn,
        session_id="other-session",
        project_root="/Users/example/proj",
        cursor="other-session-only",
        goal="must not cross the compact boundary",
    )

    ctx = _run(_payload(session_id="new-session", source="compact"))

    assert other.id not in ctx
    assert "must not cross the compact boundary" not in ctx


def test_startup_never_falls_back_across_projects(
        conn, hook_env, tmp_path, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    project_a, _ = _git_project(tmp_path, "project-a")
    _, project_b_nested = _git_project(tmp_path, "project-b")
    other = _checkpoint(
        conn,
        session_id="other-session",
        project_root=str(project_a.resolve()),
        cursor="other-project",
        goal="private project-a state",
    )

    ctx = _run(_payload(
        session_id="new-session", cwd=str(project_b_nested), source="startup"))

    assert other.id not in ctx
    assert "private project-a state" not in ctx


def test_checkpoint_context_follows_warnings_and_pins(
        conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    pins.add_pin(conn, body="Pinned instruction before continuation.")
    conn.execute(
        "INSERT INTO mining_queue(kind, status, attempts, last_error)"
        " VALUES ('mine', 'error', 3, 'timeout')")
    conn.commit()
    _checkpoint(
        conn,
        session_id="s1",
        project_root="/Users/example/proj",
        cursor="ordered",
        goal="ordered continuation",
    )

    ctx = _run(_payload(source="compact"))

    assert ctx.index("queue job(s) in error") < ctx.index("Pinned instruction")
    assert ctx.index("Pinned instruction") < ctx.index("Continuation checkpoint")


def test_continuity_failure_keeps_existing_context_and_runs_maintenance(
        conn, hook_env, tmp_path, monkeypatch):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    pins.add_pin(conn, body="Keep this pinned rule visible.")
    _seed(conn)
    conn.execute(
        "INSERT INTO documents(slug, domain, dtype, title, provenance, project_scope)"
        " VALUES ('kept-note', 'nature', 'memory', 'Kept note',"
        " '{\"project\": \"/Users/example/proj\"}', '/Users/example/proj')")
    conn.commit()
    _checkpoint(
        conn,
        session_id="s1",
        project_root="/Users/example/proj",
        cursor="render-failure",
        goal="continuity renderer will fail",
    )
    maintained = []
    monkeypatch.setattr(
        session_start,
        "render_checkpoint",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(f"render failed with {secret}")),
    )
    monkeypatch.setattr(
        session_start, "_trigger_maintenance", lambda _conn: maintained.append(True))

    ctx = _run(_payload(source="compact"))

    assert "Keep this pinned rule visible." in ctx
    assert "nature" in ctx and "field observations" in ctx
    assert "kept-note" in ctx
    assert "checkpoint restoration delayed" in ctx
    assert secret not in ctx
    assert "[REDACTED]" in ctx
    assert maintained == [True]
    logged = (tmp_path / "hooks.log").read_text()
    assert secret not in logged


def test_continuity_query_failure_rolls_back_before_maintenance(
        conn, hook_env, monkeypatch):
    pins.add_pin(conn, body="Context survives a selector failure.")
    maintained = []

    def broken_selector(runtime_conn, **kwargs):
        runtime_conn.execute("SELECT 1 / 0")

    def maintenance(runtime_conn):
        assert runtime_conn.execute("SELECT 1 AS n").fetchone()["n"] == 1
        maintained.append(True)

    monkeypatch.setattr(
        session_start, "_checkpoint_for_context", broken_selector)
    monkeypatch.setattr(session_start, "_trigger_maintenance", maintenance)

    ctx = _run(_payload(source="compact"))

    assert "Context survives a selector failure." in ctx
    assert "checkpoint restoration delayed" in ctx
    assert maintained == [True]


def test_compact_restores_handoff_within_budget(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    checkpoint = _checkpoint(
        conn, session_id="s1", project_root="/Users/example/proj",
        cursor="c1", goal="ship handoff")
    store.attach_handoff(conn, checkpoint.id, "Goal: ship handoff\nNext: docs",
                         max_chars=400)

    ctx = _run(_payload(source="compact"))

    assert "Handoff (Claude compact summary, CURRENT" in ctx
    assert "Next: docs" in ctx


def test_startup_keeps_knowledge_beside_a_full_length_handoff(
        conn, hook_env, monkeypatch):
    """A real Claude compact summary fills the 8,000-char handoff bound; the
    9,500-char total cap must shorten it instead of evicting pins, domains,
    knowledge, or the checkpoint itself."""
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    _seed(conn)
    for i in range(12):
        pins.add_pin(conn, body=f"Rule {i}: " + "r" * 100)
    checkpoint = _checkpoint(
        conn, session_id="s1", project_root="/Users/example/proj",
        cursor="c1", goal="ship handoff")
    store.attach_handoff(
        conn, checkpoint.id,
        "Goal: ship handoff\n" + "\n".join(f"- fact {i} " + "f" * 60
                                           for i in range(110)),
        max_chars=8000)

    ctx = _run(_payload(source="resume"))

    assert len(ctx) <= 9500
    assert "## Pinned rules" in ctx and "Rule 11:" in ctx
    assert "## Knowledge domains" in ctx
    assert "## Continuation checkpoint" in ctx
    assert "Goal: ship handoff" in ctx
    assert "Handoff (Claude compact summary, CURRENT" in ctx
    assert "…[truncated]" in ctx
    assert "checkpoint shortened" in ctx
    assert "dropped" not in ctx


def test_fit_context_shrinks_elastic_section_before_dropping_others():
    def render(budget):
        return ("Checkpoint c1\nHandoff: " + "h" * 20000)[:budget]

    parts = [
        ("header", "# agentic-rag memory"),
        ("pins", "## Pinned rules\n" + "\n".join(
            f"- pin {i} " + "p" * 80 for i in range(10))),
        ("domains", "## Knowledge domains\n" + "d" * 500),
        ("knowledge", "## Recent knowledge\n" + "k" * 500),
        ("checkpoint", "## Continuation checkpoint\n" + render(8000)),
    ]
    elastic = {"checkpoint": (render, 400)}

    fitted = session_start.fit_context(parts, [], 6000, elastic=elastic)

    assert len(fitted) <= 6000
    assert "## Recent knowledge" in fitted
    assert "## Knowledge domains" in fitted
    assert "## Continuation checkpoint" in fitted and "Checkpoint c1" in fitted
    assert "checkpoint shortened" in fitted
    assert "dropped" not in fitted

    # Below the elastic minimum the usual whole-section trimming resumes, and
    # the checkpoint is re-shrunk into whatever each drop frees up.
    tight = session_start.fit_context(parts, [], 2300, elastic=elastic)

    assert len(tight) <= 2300
    assert "## Recent knowledge" not in tight
    assert "## Continuation checkpoint" in tight
    assert "checkpoint shortened; dropped knowledge" in tight

    # Without an elastic renderer the behaviour is the historical one.
    plain = session_start.fit_context(parts, [], 6000)
    assert "## Recent knowledge" not in plain and "dropped knowledge" in plain


def test_fit_context_trims_in_order_and_warns_visibly():
    parts = [
        ("header", "# agentic-rag memory"),
        ("pins", "## Pinned rules\n" + "\n".join(
            f"- pin {i} " + "p" * 80 for i in range(40))),
        ("domains", "## Knowledge domains\n" + "d" * 1500),
        ("knowledge", "## Recent knowledge\n" + "k" * 1500),
        ("checkpoint", "## Continuation checkpoint\n" + "c" * 1500),
    ]

    fitted = session_start.fit_context(parts, [], 6000)

    assert len(fitted) <= 6000
    assert "## Recent knowledge" not in fitted
    assert "## Knowledge domains" not in fitted
    assert "## Continuation checkpoint" in fitted
    assert "pin 0 " in fitted
    assert "⚠️ context truncated" in fitted
    assert "knowledge" in fitted and "domains" in fitted

    tighter = session_start.fit_context(parts, ["⚠️ existing warning"], 1500)

    assert len(tighter) <= 1500
    assert "⚠️ existing warning" in tighter
    assert "## Continuation checkpoint" not in tighter
    assert "pins cut" in tighter
    assert "pin 0 " in tighter


def test_fit_context_never_exceeds_hard_limit_even_with_one_huge_pin():
    parts = [("header", "# agentic-rag memory"),
             ("pins", "## Pinned rules\n- " + "x" * 20000)]

    fitted = session_start.fit_context(parts, [], 1000)

    assert len(fitted) <= 1000
    assert "⚠️ context truncated" in fitted


def test_session_start_caps_total_output_from_config(conn, hook_env, monkeypatch):
    monkeypatch.setattr(session_start.common, "spawn_worker", lambda: None)
    hook_env.write_text(
        hook_env.read_text() + "\n[continuity]\ncontext_max_chars = 1000\n")
    for i in range(30):
        pins.add_pin(conn, body=f"Rule {i}: " + "r" * 100)

    ctx = _run(_payload())

    assert len(ctx) <= 1000
    assert "⚠️ context truncated" in ctx
    assert "Rule 0:" in ctx
