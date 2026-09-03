import json
import shlex
from pathlib import Path

import psycopg
import pytest

from agentic_rag import cli, jobs
from agentic_rag.cli import main
from agentic_rag.continuity import store as continuity_store
from agentic_rag.continuity.model import CheckpointSnapshot
from agentic_rag.provider_health import ProviderHealth

from tests._mig_fixture import build_source


@pytest.fixture
def cli_env(tmp_path, cfg, conn, monkeypatch):
    """Point the CLI at the test DB; dead Ollama port -> deterministic warnings."""
    p = tmp_path / "config.toml"
    p.write_text(
        f'[db]\nname = "{cfg.db_name}"\n\n[ollama]\nurl = "http://localhost:1"\n'
    )
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(p))
    return conn


@pytest.fixture
def mig_source(tmp_path: Path) -> Path:
    return build_source(tmp_path)


def test_domain_add_and_list(cli_env, capsys):
    assert main(["domain", "add", "nature", "--description",
                 "field observations"]) == 0
    assert main(["domain", "list"]) == 0
    out = capsys.readouterr().out
    assert "nature" in out


def test_save_get_search_roundtrip(cli_env, capsys):
    main(["domain", "add", "nature"])
    rc = main(["save", "--title", "Photosynthesis", "--domain", "nature",
               "--dtype", "concept", "--body", "Leaves convert sunlight to energy.",
               "--edge", "references:chlorophyll"])
    assert rc == 0
    capsys.readouterr()  # drain non-JSON output before parsing JSON below
    assert main(["get", "photosynthesis", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["title"] == "Photosynthesis"
    assert doc["edges_out"][0]["peer_slug"] == "chlorophyll"
    assert main(["search", "convert sunlight", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits["results"][0]["slug"] == "photosynthesis"
    assert any("embedding" in w for w in hits["warnings"])


def test_save_slug_upserts_in_place(cli_env, capsys):
    """--slug updates the doc with that slug (read-modify-write / idempotent
    re-ingest) instead of minting a slug-2 duplicate — the briefing write path
    relies on this to append video citations to existing atomics."""
    main(["domain", "add", "nature"])
    assert main(["save", "--title", "River Delta", "--domain", "nature",
                 "--dtype", "concept", "--body", "First body.",
                 "--slug", "river-delta"]) == 0
    out1 = capsys.readouterr().out
    assert "created river-delta" in out1
    # second save with the SAME slug must UPDATE, not create river-delta-2
    assert main(["save", "--title", "River Delta", "--domain", "nature",
                 "--dtype", "concept", "--body", "First body.\n\nAppended.",
                 "--slug", "river-delta"]) == 0
    out2 = capsys.readouterr().out
    assert "updated river-delta" in out2
    assert main(["get", "river-delta", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert "Appended." in doc["body"]
    # exactly one doc carries this slug (no -2 duplicate)
    assert main(["get", "river-delta-2"]) == 1


def test_get_missing_returns_nonzero(cli_env, capsys):
    assert main(["get", "no-such-slug"]) == 1


def test_status_runs(cli_env, capsys):
    assert main(["status"]) == 0
    assert "documents" in capsys.readouterr().out


def test_db_down_maps_to_exit_3(cli_env, monkeypatch):
    def boom(*a, **k):
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(cli.db, "connect", boom)
    assert main(["status"]) == 3


def test_unexpected_error_maps_to_exit_4(cli_env, monkeypatch):
    def boom(*a, **k):
        raise KeyError("surprise")
    monkeypatch.setattr(cli.db, "connect", boom)
    assert main(["status"]) == 4


def test_status_surfaces_backup_warning(cli_env, tmp_path, monkeypatch, capsys):
    warn = tmp_path / "backup_warning"
    warn.write_text("cloud backup dir unavailable (X not mounted)")
    monkeypatch.setattr(cli.status_mod, "WARNING_STATE", warn)
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "WARNING: cloud backup dir unavailable" in out


def test_status_surfaces_provider_health(cli_env, capsys):
    cli.status_mod.provider_health.record_failure("codex", "login required")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "provider: codex unavailable" in out
    assert "codex login" in out


def test_status_sanitizes_provider_diagnostics(cli_env, monkeypatch, capsys):
    secret = "sk-abcdefghijklmnop1234"
    monkeypatch.setattr(
        cli.status_mod.provider_health,
        "read_health",
        lambda: ProviderHealth(secret, False, reason=f"token={secret}"),
    )

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert secret not in out
    assert "[REDACTED]" in out


def test_status_prints_checkpoint_health(cli_env, capsys):
    checkpoint = continuity_store.upsert_snapshot(
        cli_env,
        CheckpointSnapshot(
            session_id="status-session",
            turn_id="turn-1",
            cursor="event-1",
            source="PreCompact",
            trigger="auto",
            cwd="/project",
            project_root="/project",
        ),
    )
    jobs.enqueue_checkpoint_enrichment(
        cli_env,
        checkpoint_id=checkpoint.id,
        session_id="status-session",
        transcript_path="/transcript.jsonl",
        after_cursor=None,
    )

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "checkpoints: 1 open" in out
    assert "[snapshot] /project" in out
    assert "checkpoint enrichments: 1 pending" in out


def test_queue_requeue_requires_yes_and_exact_count(cli_env, capsys):
    cli_env.execute(
        "INSERT INTO mining_queue(kind, status, attempts, last_error, finished_at) "
        "VALUES ('mine', 'error', 3, 'claude exited 1: ', now())")
    cli_env.commit()
    assert main(["queue", "requeue-legacy-provider-failures", "--expect", "1"]) == 1
    assert "candidate count: 1" in capsys.readouterr().out
    assert main(["queue", "requeue-legacy-provider-failures", "--expect", "2", "--yes"]) == 1
    assert "count mismatch" in capsys.readouterr().err
    assert main(["queue", "requeue-legacy-provider-failures", "--expect", "1", "--yes"]) == 0
    assert "requeued 1" in capsys.readouterr().out


def test_pin_add_list_rm_roundtrip(cli_env, capsys):
    assert main(["pin", "add", "--body", "Immer uv benutzen."]) == 0
    pid = capsys.readouterr().out.split()[-1]
    assert main(["pin", "list"]) == 0
    assert "Immer uv benutzen." in capsys.readouterr().out
    assert main(["pin", "verify", pid]) == 0
    assert main(["pin", "rm", pid]) == 0
    assert main(["pin", "rm", pid]) == 1


def test_review_renders_empty_worklists(cli_env, capsys):
    assert main(["review"]) == 0
    out = capsys.readouterr().out
    assert "duplicate candidates:" in out
    assert "stale pins:" in out


def test_purge_refuses_without_yes(cli_env, capsys):
    assert main(["purge"]) == 1


def test_install_command_wires_everything(tmp_path, monkeypatch, capsys):
    # hermetic: _main's unconditional load_config() must never read the
    # real ~/.agentic-rag/config.toml during tests
    cfg_toml = tmp_path / "config.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))
    monkeypatch.setattr(cli.install_mod, "register_mcp",
                        lambda python, run: None)
    monkeypatch.setattr(cli.install_mod.backup, "install_launchd",
                        lambda cfg, rag_bin: tmp_path / "plist")
    monkeypatch.setattr(cli.install_mod, "SETTINGS_PATH",
                        tmp_path / "settings.json")
    assert main(["install"]) == 0
    out = capsys.readouterr().out
    assert "registered" in out and "settings.json" in out


def test_install_no_launchd_skips_plist(tmp_path, monkeypatch, capsys):
    cfg_toml = tmp_path / "config.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))
    monkeypatch.setattr(cli.install_mod, "register_mcp",
                        lambda python, run: None)
    def exploding_launchd(cfg, rag_bin):
        raise AssertionError("--no-launchd must skip install_launchd")
    monkeypatch.setattr(cli.install_mod.backup, "install_launchd",
                        exploding_launchd)
    monkeypatch.setattr(cli.install_mod, "SETTINGS_PATH",
                        tmp_path / "settings.json")
    assert main(["install", "--no-launchd"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_install_codex_check_reports_changed_paths_without_writing(
        tmp_path, monkeypatch, capsys):
    cfg_toml = tmp_path / "config.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))
    monkeypatch.setattr(
        cli.install_mod.codex_install,
        "_probe_codex",
        lambda paths, run: ("codex-cli test", "managed configuration validated"),
    )

    assert main([
        "install", "--codex", "--check", "--codex-home", str(tmp_path),
    ]) == 0

    out = capsys.readouterr().out
    assert ".codex/config.toml" in out
    assert "no files written" in out.lower()
    assert "/hooks" in out
    assert "managed: model_context_window=600000" in out
    assert "managed: model_auto_compact_token_limit=500000" in out
    assert 'managed: model_auto_compact_token_limit_scope="total"' in out
    assert "managed: features.memories=true" in out
    assert "managed: memories.generate_memories=true" in out
    assert "managed: memories.use_memories=true" in out
    assert "managed: memories.disable_on_external_context=false" in out
    assert 'managed: memories.extract_model="gpt-5.6-luna"' in out
    assert 'managed: memories.consolidation_model="gpt-5.6-luna"' in out
    assert "rollback: not needed in check mode" in out
    assert not (tmp_path / ".codex").exists()


def test_install_check_requires_explicit_codex_target(tmp_path, monkeypatch):
    cfg_toml = tmp_path / "config.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))

    with pytest.raises(SystemExit) as exc:
        cli._main(["install", "--check"])

    assert exc.value.code == 2


def test_install_error_diagnostic_is_sanitized(tmp_path, monkeypatch, capsys):
    cfg_toml = tmp_path / "config.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))
    secret = "sk-abcdefghijklmnop1234"

    def fail(*args, **kwargs):
        raise RuntimeError(f"Codex rejected token={secret}")

    monkeypatch.setattr(cli.install_mod, "install", fail)

    assert main(["install", "--codex", "--check"]) == 3
    err = capsys.readouterr().err
    assert secret not in err
    assert "[REDACTED]" in err


def _seed_codex_cli_home(tmp_path, monkeypatch):
    cfg_toml = tmp_path / "agentic-rag.toml"
    cfg_toml.write_text("")
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(cfg_toml))
    paths = cli.install_mod.codex_install.CodexPaths.for_home(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    originals = {
        paths.config_path: b'custom = "keep"\n',
        paths.hooks_path: b'{"metadata": "keep"}\n',
        paths.prompt_path: b"original prompt\n",
    }
    for path, content in originals.items():
        path.write_bytes(content)
    monkeypatch.setattr(
        cli.install_mod.codex_install,
        "_probe_codex",
        lambda paths, run: ("codex-cli test", "managed configuration validated"),
    )
    return paths, originals


def _rollback_command(output):
    line = next(line for line in output.splitlines()
                if line.startswith("rollback: rag "))
    return line.removeprefix("rollback: ")


def test_install_codex_printed_rollback_command_restores_all_originals(
        tmp_path, monkeypatch, capsys):
    home = tmp_path / "home with spaces"
    home.mkdir()
    paths, originals = _seed_codex_cli_home(home, monkeypatch)

    assert main([
        "install", "--codex", "--codex-home", str(home),
    ]) == 0

    install_output = capsys.readouterr().out
    assert install_output.count("backup:") == 3
    command = _rollback_command(install_output)
    assert main(shlex.split(command)[1:]) == 0
    assert "restored:" in capsys.readouterr().out
    assert {path: path.read_bytes() for path in paths.targets} == originals


def test_install_codex_restore_rejects_missing_backup_without_changes(
        tmp_path, monkeypatch, capsys):
    paths, _ = _seed_codex_cli_home(tmp_path, monkeypatch)
    assert main([
        "install", "--codex", "--codex-home", str(tmp_path),
    ]) == 0
    command = _rollback_command(capsys.readouterr().out)
    record_path = Path(shlex.split(command)[-1])
    record = json.loads(record_path.read_text())
    Path(record["backups"][0]["backup_path"]).unlink()
    installed = {path: path.read_bytes() for path in paths.targets}

    assert main(shlex.split(command)[1:]) == 3

    assert "valid rollback backup" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in paths.targets} == installed


def test_install_codex_restore_rejects_modified_backup_without_changes(
        tmp_path, monkeypatch, capsys):
    paths, _ = _seed_codex_cli_home(tmp_path, monkeypatch)
    assert main([
        "install", "--codex", "--codex-home", str(tmp_path),
    ]) == 0
    command = _rollback_command(capsys.readouterr().out)
    record_path = Path(shlex.split(command)[-1])
    record = json.loads(record_path.read_text())
    Path(record["backups"][-1]["backup_path"]).write_text("not the backup")
    installed = {path: path.read_bytes() for path in paths.targets}

    assert main(shlex.split(command)[1:]) == 3

    assert "valid rollback backup" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in paths.targets} == installed


def test_install_codex_restore_preserves_conflicting_target(
        tmp_path, monkeypatch, capsys):
    paths, _ = _seed_codex_cli_home(tmp_path, monkeypatch)
    assert main([
        "install", "--codex", "--codex-home", str(tmp_path),
    ]) == 0
    command = _rollback_command(capsys.readouterr().out)
    conflict = b'custom = "concurrent edit"\n'
    paths.config_path.write_bytes(conflict)
    before = {path: path.read_bytes() for path in paths.targets}

    assert main(shlex.split(command)[1:]) == 3

    assert "changed since installation" in capsys.readouterr().err
    assert paths.config_path.read_bytes() == conflict
    assert {path: path.read_bytes() for path in paths.targets} == before


def test_migrate_run_refuses_without_yes(cli_env, mig_source):
    rc = cli.main(["migrate", "run", "--source", str(mig_source)])
    assert rc == 1


def test_migrate_dry_run_needs_no_yes_and_writes_nothing(cli_env, mig_source,
                                                         conn, capsys):
    rc = cli.main(["migrate", "run", "--dry-run", "--source", str(mig_source)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "source scan:" in out
    assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0


def test_migrate_run_aborts_when_ollama_down(cli_env, mig_source):
    # cli_env's config points Ollama at a dead port — preflight must refuse
    rc = cli.main(["migrate", "run", "--yes", "--skip-backup",
                   "--source", str(mig_source)])
    assert rc == 3


def test_migrate_run_aborts_when_worker_lock_held(cli_env, mig_source,
                                                  monkeypatch):
    from agentic_rag import cli as cli_mod
    monkeypatch.setattr(cli_mod.embed, "try_embed_texts",
                        lambda texts, cfg: [[0.0] * cfg.embed_dim
                                            for _ in texts])
    from agentic_rag import worker
    held = worker.acquire_lock(worker.LOCK_PATH)   # simulate a live worker
    try:
        rc = cli.main(["migrate", "run", "--yes", "--skip-backup",
                       "--source", str(mig_source)])
        assert rc == 3
    finally:
        held.close()


def test_migrate_classify_prints_report_path(cli_env, tmp_path, monkeypatch,
                                             capsys):
    from agentic_rag import cli as cli_mod
    report = tmp_path / "domain-report.md"
    report.write_text("# report\n")
    monkeypatch.setattr(cli_mod.migration_mod, "classify_domains",
                        lambda conn, cfg: report)
    rc = cli.main(["migrate", "classify"])
    assert rc == 0
    assert str(report) in capsys.readouterr().out


def test_migrate_apply_domains_refuses_without_yes(cli_env, tmp_path, capsys):
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\n")
    rc = cli.main(["migrate", "apply-domains", str(tsv)])
    assert rc == 1
    assert "refusing without --yes" in capsys.readouterr().err


def test_migrate_apply_domains_aborts_when_worker_lock_held(cli_env, tmp_path,
                                                             capsys):
    # apply-domains writes (set_domain) — it must take the same worker
    # flock as `migrate run` so it never races the worker's own writes.
    from agentic_rag import worker
    tsv = tmp_path / "r.tsv"
    tsv.write_text("slug\tcurrent\tproposed\n")
    held = worker.acquire_lock(worker.LOCK_PATH)   # simulate a live worker
    try:
        rc = cli.main(["migrate", "apply-domains", str(tsv), "--yes"])
        assert rc == 3
        assert "another writer (worker) is active" in capsys.readouterr().err
    finally:
        held.close()
