"""Configuration: one TOML file, flat dataclass, env override for tests."""
from __future__ import annotations

import dataclasses
import os
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_PATH = Path.home() / ".agentic-rag" / "config.toml"
MIN_DIGEST_CHARS = 128
MIN_HANDOFF_CHARS = 400
MIN_CONTEXT_CHARS = 1_000
MAX_CONTEXT_CHARS = 10_000   # Claude Code's per-hook additionalContext limit

# TOML section -> field prefix. [db] name  ->  db_name, etc.
_SECTION_PREFIX = {
    "db": "db",
    "embed": "embed",
    "rerank": "rerank",
    "ollama": "ollama",
    "backup": "backup",
    "hooks": "hooks",
    "llm": "llm",
    "mining": "mine",
    "curation": "curation",
    "worker": "worker",
    "pg": "pg",
    "continuity": "checkpoint",
    "service": "service",
    "temporal": "temporal",
    "synthesis": "synthesis",
}


class _FrozenProfiles(dict):
    """Immutable mapping that preserves Config's dataclasses.asdict wire path."""
    def _immutable(self, *args, **kwargs):
        raise TypeError('embedding profiles are immutable')
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


@dataclass(frozen=True)
class Config:
    service_max_database_bytes: int = 8*1024**3
    service_min_free_bytes: int = 2*1024**3
    service_max_pending: int = 1000
    service_max_pending_per_owner: int = 100
    service_max_pending_bytes: int = 64*1024**2
    service_storage_path: Path | None = None
    service_tool_wait_seconds: float = 30
    service_hook_wait_seconds: float = 1
    service_poll_seconds: float = 1
    service_mode: str = "standalone"
    service_url: str = ""
    service_token_file: Path | None = None
    service_auth_file: Path | None = None
    service_spool_dir: Path = field(default_factory=lambda: Path.home()/'.agentic-rag'/'spool')
    db_name: str = "agentic_rag"
    db_host: str = ""  # "" = local unix socket
    embed_model: str = "bge-m3"
    embed_dim: int = 1024
    ollama_url: str = "http://localhost:11434"
    rerank_url: str = "http://127.0.0.1:8766"
    rerank_policy: str = "focused-v1"
    rerank_model: str = "agentic-rag-mmarco-int8"
    rerank_revision: str = "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b"
    rerank_timeout_seconds: float = 1.5
    rerank_diagnostics: bool = False
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
    # Managed vector spaces are opt-in; legacy [embed]/[ollama] stay independent.
    embedding_profiles: Mapping = field(default_factory=dict)
    llm_url: str = ""
    llm_revision: str = ""
    llm_credential_env: str = ""
    llm_credential_file: str = ""
    llm_max_input_chars: int = 24000
    llm_max_output_tokens: int = 2048
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
    checkpoint_handoff_max_chars: int = 8000
    context_max_chars: int = 9500
    # Temporal query interpretation is opt-in; explicit request modes still apply.
    temporal_enabled: bool = False
    temporal_timezone: str = "UTC"
    # Pattern synthesis is off globally; a scoped policy is also required.
    synthesis_enabled: bool = False
    synthesis_provider: str = ""
    synthesis_model: str = ""
    synthesis_timeout_seconds: int = 30
    synthesis_max_input_chars: int = 12000
    synthesis_max_output_tokens: int = 1024
    synthesis_max_runs_per_tick: int = 2

    def __post_init__(self) -> None:
        if self.rerank_policy not in ('legacy-v1', 'focused-v1'):
            raise ValueError('invalid rerank policy')
        if not isinstance(self.rerank_model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',self.rerank_model):
            raise ValueError('invalid rerank model alias')
        if not isinstance(self.rerank_revision,str) or not re.fullmatch(r'[0-9a-f]{64}',self.rerank_revision):
            raise ValueError('rerank revision must be a pinned SHA256')
        from .reranker_profiles import catalogue
        for profile in catalogue():
            if self.rerank_model == profile['alias'] and self.rerank_revision != profile['files']['model.onnx']['sha256']:
                raise ValueError('rerank preset identity must match pinned SHA256')
        if type(self.temporal_enabled) is not bool:
            raise ValueError('temporal enabled must be boolean')
        if type(self.synthesis_enabled) is not bool:
            raise ValueError('synthesis enabled must be boolean')
        if self.synthesis_provider not in ('', 'claude', 'codex', 'openai-compatible'):
            raise ValueError('invalid synthesis provider')
        if not isinstance(self.synthesis_model, str) or len(self.synthesis_model) > 200:
            raise ValueError('synthesis model must be at most 200 characters')
        for name, low, high in [('synthesis_timeout_seconds', 1, 300), ('synthesis_max_input_chars', 1000, 24000),
                                ('synthesis_max_output_tokens', 128, 4096), ('synthesis_max_runs_per_tick', 1, 10)]:
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise ValueError(f'{name} must be an integer between {low} and {high}')
        from .temporal import parse_zone
        parse_zone(self.temporal_timezone)
        if type(self.rerank_diagnostics) is not bool:
            raise ValueError('rerank diagnostics must be boolean')
        if (type(self.rerank_timeout_seconds) not in (float,int)
                or not math.isfinite(self.rerank_timeout_seconds)
                or not .01 <= self.rerank_timeout_seconds <= 1.5):
            raise ValueError('rerank timeout must be between0.01 and1.5 seconds')
        from .providers import EmbeddingProfile, ProviderError
        if not isinstance(self.embedding_profiles, Mapping):
            raise ProviderError('configuration', False, 'Embedding profiles must be a named mapping.')
        profiles = {}
        for name, value in self.embedding_profiles.items():
            if not isinstance(name, str) or not name or len(name) > 80:
                raise ProviderError('configuration', False, 'Invalid embedding profile name.')
            profiles[name] = value if isinstance(value, EmbeddingProfile) else EmbeddingProfile.from_mapping(value)
        object.__setattr__(self, 'embedding_profiles', _FrozenProfiles(profiles))
        for name,minimum in [('backup_keep_local',1),('backup_keep_daily',1),('backup_keep_weekly',0)]:
            value=getattr(self,name)
            if type(value) is not int or not minimum<=value<=366:
                raise ValueError(name+' must be a finite retention count (maximum 366)')
        for name in ('service_max_database_bytes','service_min_free_bytes','service_max_pending',
                     'service_max_pending_per_owner','service_max_pending_bytes'):
            if type(getattr(self,name)) is not int or getattr(self,name)<1:
                raise ValueError(name+' must be a positive integer')
        for name,upper in [('service_tool_wait_seconds',300),('service_hook_wait_seconds',5),('service_poll_seconds',30)]:
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not .01<=value<=upper:
                raise ValueError(name+' must be a finite bounded duration')
        if self.service_mode not in {"standalone","client","server"}:
            raise ValueError("invalid service mode")
        if (
            not isinstance(self.mine_max_digest_chars, int)
            or isinstance(self.mine_max_digest_chars, bool)
            or self.mine_max_digest_chars < MIN_DIGEST_CHARS
        ):
            raise ValueError(
                "mining max_digest_chars must be an integer of at least "
                f"{MIN_DIGEST_CHARS}"
            )
        if (
            not isinstance(self.checkpoint_handoff_max_chars, int)
            or isinstance(self.checkpoint_handoff_max_chars, bool)
            or self.checkpoint_handoff_max_chars < MIN_HANDOFF_CHARS
        ):
            raise ValueError(
                "continuity handoff_max_chars must be an integer of at least "
                f"{MIN_HANDOFF_CHARS}"
            )
        if (
            not isinstance(self.context_max_chars, int)
            or isinstance(self.context_max_chars, bool)
            or not MIN_CONTEXT_CHARS <= self.context_max_chars <= MAX_CONTEXT_CHARS
        ):
            raise ValueError(
                "continuity context_max_chars must be an integer between "
                f"{MIN_CONTEXT_CHARS} and {MAX_CONTEXT_CHARS}"
            )


_PATH_FIELDS = {"service_storage_path","backup_cloud_dir", "backup_local_dir", "pg_bin_dir", "service_token_file", "service_auth_file", "service_spool_dir"}


def load_config(path: Path | None = None) -> Config:
    from .service.context import CURRENT
    request = CURRENT.get()
    if request is not None:
        return request.config
    p = path or Path(os.environ.get("AGENTIC_RAG_CONFIG", DEFAULT_PATH))
    if not p.exists():
        return Config()
    data = tomllib.loads(p.read_text())
    known = {f.name for f in dataclasses.fields(Config)}
    kwargs: dict = {}
    for section, values in data.items():
        if section == 'embedding_profiles':
            kwargs['embedding_profiles'] = values
            continue
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
    rerank = data.get('rerank', {})
    if isinstance(rerank, dict):
        if 'profile' in rerank:
            if {'model', 'revision', 'policy'} & rerank.keys():
                raise ValueError('rerank profile cannot be mixed with model/revision/policy')
            from .reranker_profiles import configuration
            kwargs.update(configuration(rerank['profile']))
        elif {'model', 'revision'} & rerank.keys():
            # Explicit pre-0.6.15 identities keep all omitted legacy defaults.
            kwargs.setdefault('rerank_model', 'agentic-rag-qwen3-reranker-0.6b-q8')
            kwargs.setdefault('rerank_revision', '22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48')
            kwargs.setdefault('rerank_policy', 'legacy-v1')
    return Config(**kwargs)
