"""Configuration: one TOML file, flat dataclass, env override for tests."""
from __future__ import annotations

import dataclasses
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path.home() / ".agentic-rag" / "config.toml"
MIN_DIGEST_CHARS = 128

# TOML section -> field prefix. [db] name  ->  db_name, etc.
_SECTION_PREFIX = {
    "db": "db",
    "embed": "embed",
    "ollama": "ollama",
    "backup": "backup",
    "hooks": "hooks",
    "llm": "llm",
    "mining": "mine",
    "curation": "curation",
    "worker": "worker",
    "pg": "pg",
    "continuity": "checkpoint",
}


@dataclass(frozen=True)
class Config:
    db_name: str = "agentic_rag"
    db_host: str = ""  # "" = local unix socket
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    ollama_url: str = "http://localhost:11434"
    backup_cloud_dir: Path | None = None   # opt-in: no cloud copy unless set
    backup_local_dir: Path = field(
        default_factory=lambda: Path.home() / ".agentic-rag" / "backups"
    )
    pg_bin_dir: Path | None = None         # auto-detected; override for odd installs
    backup_keep_daily: int = 14
    backup_keep_weekly: int = 8
    backup_keep_local: int = 7
    stale_days: int = 30
    pin_budget_chars: int = 16000
    context_docs: int = 5
    llm_provider: str = "claude"
    llm_model: str = "haiku"
    llm_reasoning_effort: str = "high"
    llm_timeout: int = 300
    llm_bin: str = "claude"
    provider_backoff_seconds: int = 3600
    mine_debounce_seconds: int = 600
    mine_max_digest_chars: int = 12000
    mine_per_block_chars: int = 800
    dedup_threshold: float = 0.90
    curation_budget: int = 20
    worker_max_attempts: int = 3
    worker_backoff_seconds: int = 300
    checkpoint_status_max_chars: int = 4000
    checkpoint_render_max_chars: int = 8000
    checkpoint_artifact_max: int = 16

    def __post_init__(self) -> None:
        if (
            not isinstance(self.mine_max_digest_chars, int)
            or isinstance(self.mine_max_digest_chars, bool)
            or self.mine_max_digest_chars < MIN_DIGEST_CHARS
        ):
            raise ValueError(
                "mining max_digest_chars must be an integer of at least "
                f"{MIN_DIGEST_CHARS}"
            )


_PATH_FIELDS = {"backup_cloud_dir", "backup_local_dir", "pg_bin_dir"}


def load_config(path: Path | None = None) -> Config:
    p = path or Path(os.environ.get("AGENTIC_RAG_CONFIG", DEFAULT_PATH))
    if not p.exists():
        return Config()
    data = tomllib.loads(p.read_text())
    known = {f.name for f in dataclasses.fields(Config)}
    kwargs: dict = {}
    for section, values in data.items():
        prefix = _SECTION_PREFIX.get(section)
        if prefix is None or not isinstance(values, dict):
            continue
        for key, value in values.items():
            name = f"{prefix}_{key}" if f"{prefix}_{key}" in known else (
                key if key in known else None
            )
            # [ollama] url -> ollama_url
            if name is None and f"{section}_{key}" in known:
                name = f"{section}_{key}"
            if name is None:
                continue
            if name in _PATH_FIELDS:
                value = Path(str(value)).expanduser()
            kwargs[name] = value
    return Config(**kwargs)
