import psycopg
import pytest

from agentic_rag import db
from agentic_rag.config import Config

TEST_DB = "agentic_rag_test"
# order matters only for readability; TRUNCATE ... CASCADE handles FKs
TABLES = "documents, domains, edges, pins, mining_queue, audit_log, continuation_checkpoints"


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config(db_name=TEST_DB)


@pytest.fixture(scope="session")
def dbinit(cfg):
    admin = psycopg.connect("dbname=postgres", autocommit=True)
    exists = admin.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)
    ).fetchone()
    if not exists:
        admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    admin.close()
    c = db.connect(cfg, role="owner")
    c.autocommit = True
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    db.apply_migrations(c, db.SQL_DIR)
    c.close()
    yield


@pytest.fixture
def conn(dbinit, cfg):
    c = db.connect(cfg, role="owner")
    c.autocommit = True
    c.execute(f"TRUNCATE {TABLES} CASCADE")
    c.autocommit = False
    yield c
    c.rollback()
    c.close()


@pytest.fixture(autouse=True)
def _isolate_home_paths(tmp_path, monkeypatch):
    """No test may touch the real ~/.agentic-rag — worker and hook modules
    hold module-level Path.home() constants, so patch them all, always.
    Individual tests may still re-patch with their own tmp paths."""
    from agentic_rag import migration, provider_health, worker
    from agentic_rag.hooks import common
    monkeypatch.setattr(worker, "LOCK_PATH", tmp_path / "worker.lock")
    monkeypatch.setattr(worker, "LOG_PATH", tmp_path / "worker.log")
    monkeypatch.setattr(
        provider_health, "HEALTH_PATH", tmp_path / "provider-health.json")
    monkeypatch.setattr(common, "HOOK_LOG", tmp_path / "hooks.log")
    monkeypatch.setattr(common, "WORKER_LOG", tmp_path / "worker.log")
    monkeypatch.setattr(migration, "MIGRATION_DIR", tmp_path / "migration")


@pytest.fixture
def hook_env(dbinit, tmp_path, monkeypatch):
    """Point hooks/MCP (which call load_config themselves) at the test DB;
    dead Ollama port → deterministic embed-unavailable path (the cli_env
    pattern from tests/test_cli.py). Also isolates the hook error log —
    db-down tests must never append to the real ~/.agentic-rag/log."""
    # imported inside the fixture: conftest must stay importable while the
    # hooks package does not exist yet (Task 12's own red phase)
    from agentic_rag.hooks import common
    monkeypatch.setattr(common, "HOOK_LOG", tmp_path / "hooks.log")
    p = tmp_path / "config.toml"
    p.write_text(f'[db]\nname = "{TEST_DB}"\n\n'
                 '[ollama]\nurl = "http://localhost:1"\n')
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(p))
    monkeypatch.delenv("AGENTIC_RAG_HOOKS_DISABLE", raising=False)
    return p
