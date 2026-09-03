"""Lossless merge support for Codex's user-level TOML configuration."""
from __future__ import annotations

from pathlib import Path

import tomlkit


ROOT_VALUES = {
    "model_context_window": 600000,
    "model_auto_compact_token_limit": 500000,
    "model_auto_compact_token_limit_scope": "total",
}

FEATURE_VALUES = {
    "hooks": True,
    "memories": True,
}

MEMORY_VALUES = {
    "generate_memories": True,
    "use_memories": True,
    "disable_on_external_context": False,
    "min_rollout_idle_hours": 6,
    "max_rollout_age_days": 90,
    "max_rollouts_per_startup": 32,
    "max_raw_memories_for_consolidation": 1024,
    "max_unused_days": 180,
    "min_rate_limit_remaining_percent": 15,
    "extract_model": "gpt-5.6-luna",
    "consolidation_model": "gpt-5.6-luna",
}


def merge_config(text: str, *, home: Path) -> str:
    """Return Codex TOML with owned values set and all other syntax retained.

    Parsing is deliberately the first operation so malformed input fails before
    the caller can stage or replace any user file.
    """
    document = tomlkit.parse(text)
    values = {
        **ROOT_VALUES,
        "experimental_compact_prompt_file": str(
            Path(home) / ".codex" / "compact_prompt.md"
        ),
    }
    for key, value in values.items():
        document[key] = value

    features = document.get("features")
    if features is None:
        features = tomlkit.table()
        document["features"] = features
    for key, value in FEATURE_VALUES.items():
        features[key] = value

    memories = document.get("memories")
    if memories is None:
        memories = tomlkit.table()
        document["memories"] = memories
    for key, value in MEMORY_VALUES.items():
        memories[key] = value

    return tomlkit.dumps(document)
