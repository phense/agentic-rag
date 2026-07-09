from pathlib import Path

from agentic_rag.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.db_name == "agentic_rag"
    assert cfg.embed_model == "bge-m3"
    assert cfg.embed_dim == 1024
    assert cfg.ollama_url == "http://localhost:11434"
    assert cfg.backup_cloud_dir is None          # opt-in: unset by default
    assert cfg.pg_bin_dir is None                # auto-detected unless set
    assert cfg.backup_keep_daily == 14


def test_load_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
[db]
name = "otherdb"

[embed]
model = "embeddinggemma"
dim = 768

[ollama]
url = "http://localhost:9999"

[backup]
cloud_dir = "/Volumes/Elsewhere/bk"
keep_daily = 3
"""
    )
    # config parses any dim; init-db enforces 1024 (see tests/test_db_init.py)
    cfg = load_config(p)
    assert cfg.db_name == "otherdb"
    assert cfg.embed_model == "embeddinggemma"
    assert cfg.embed_dim == 768
    assert cfg.ollama_url == "http://localhost:9999"
    assert cfg.backup_cloud_dir == Path("/Volumes/Elsewhere/bk")
    assert cfg.backup_keep_daily == 3
    # untouched defaults survive
    assert cfg.backup_keep_weekly == 8


def test_env_var_points_to_config(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text('[db]\nname = "envdb"\n')
    monkeypatch.setenv("AGENTIC_RAG_CONFIG", str(p))
    cfg = load_config()
    assert cfg.db_name == "envdb"


def test_hooks_section_fields(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[hooks]\nstale_days = 7\npin_budget_chars = 2000\n")
    cfg = load_config(p)
    assert cfg.stale_days == 7
    assert cfg.pin_budget_chars == 2000


def test_hooks_defaults():
    cfg = Config()
    assert cfg.stale_days == 30
    assert cfg.pin_budget_chars == 16000


def test_llm_section_fields(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[llm]\nmodel = "sonnet"\ntimeout = 60\n')
    cfg = load_config(p)
    assert cfg.llm_model == "sonnet"
    assert cfg.llm_timeout == 60
    assert cfg.llm_bin == "claude"


def test_mining_section_fields(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[mining]\ndebounce_seconds = 5\n")
    assert load_config(p).mine_debounce_seconds == 5


def test_mining_caps_and_dedup(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[mining]\nmax_digest_chars = 100\ndedup_threshold = 0.5\n")
    cfg = load_config(p)
    assert cfg.mine_max_digest_chars == 100
    assert cfg.dedup_threshold == 0.5
    assert cfg.mine_per_block_chars == 800


def test_curation_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[curation]\nbudget = 5\n")
    assert load_config(p).curation_budget == 5
    assert Config().curation_budget == 20


def test_worker_section(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[worker]\nmax_attempts = 5\nbackoff_seconds = 10\n")
    cfg = load_config(p)
    assert cfg.worker_max_attempts == 5
    assert cfg.worker_backoff_seconds == 10


def test_context_docs_field(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[hooks]\ncontext_docs = 3\n")
    assert load_config(p).context_docs == 3
    assert Config().context_docs == 5


def test_pg_section_sets_bin_dir(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[pg]\nbin_dir = "/opt/pg/bin"\n')
    assert load_config(p).pg_bin_dir == Path("/opt/pg/bin")
