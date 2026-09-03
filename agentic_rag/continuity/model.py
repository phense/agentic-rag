"""Typed contracts for deterministic and enriched continuation state."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from agentic_rag.secrets import strip_secrets, strip_secrets_json


CHECKPOINT_STATES = frozenset({"open", "superseded", "completed"})
CHECKPOINT_QUALITIES = frozenset({"snapshot", "enriched"})

_ENRICHMENT_STRING_FIELDS = frozenset({"goal", "next_action"})
_ENRICHMENT_LIST_FIELDS = frozenset({
    "success_criteria", "instructions", "approvals", "decisions",
    "rejected_alternatives", "completed_steps", "remaining_steps", "files",
    "tests", "processes", "external_states", "blockers", "risks", "rag_slugs",
})
ENRICHMENT_FIELDS = _ENRICHMENT_STRING_FIELDS | _ENRICHMENT_LIST_FIELDS
MAX_ENRICHMENT_STRING_CHARS = 2_000
MAX_ENRICHMENT_LIST_ITEMS = 32
MAX_ENRICHMENT_BYTES = 16_000
_UNSAFE_ENRICHMENT_CONTENT = re.compile(r"(?i)\b(?:transcript|diff|body)\b")
_UNIFIED_DIFF_HUNK = re.compile(
    r"(?m)^---[ \t]+[^\s\r\n][^\r\n]*\r?\n"
    r"^\+\+\+[ \t]+[^\s\r\n][^\r\n]*\r?\n"
    r"^@@[ \t]+-\d+(?:,\d+)?[ \t]+\+\d+(?:,\d+)?[ \t]+@@"
)
_CONTEXT_DIFF_HUNK = re.compile(
    r"(?ms)^\*{15}\r?\n^\*{3}[ \t]+\d+(?:,\d+)?[ \t]+\*{4}[ \t]*\r?\n"
    r".*?^---[ \t]+\d+(?:,\d+)?[ \t]-{4}[ \t]*$"
)
_SPEAKER_DIALOGUE = re.compile(
    r"(?im)^\s*(?:user|assistant|system|tool)\s*:\s*\S[^\r\n]*\r?\n"
    r"\s*(?:user|assistant|system|tool)\s*:\s*\S"
)
_JSONL_ROLE_CONTENT_DIALOGUE = re.compile(
    r'(?im)^\s*\{(?=[^\r\n{}]*"role"\s*:\s*"(?:user|assistant|system|tool)")'
    r'(?=[^\r\n{}]*"content"\s*:)[^\r\n]*\}\s*\r?\n'
    r'\s*\{(?=[^\r\n{}]*"role"\s*:\s*"(?:user|assistant|system|tool)")'
    r'(?=[^\r\n{}]*"content"\s*:)[^\r\n]*\}'
)
_UNSAFE_ENRICHMENT_STRUCTURES = (
    _UNIFIED_DIFF_HUNK,
    _CONTEXT_DIFF_HUNK,
    _SPEAKER_DIALOGUE,
    _JSONL_ROLE_CONTENT_DIALOGUE,
)


def _require_nonblank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


def _validate_enrichment_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"enrichment {field_name} must be a string")
    if len(value) > MAX_ENRICHMENT_STRING_CHARS:
        raise ValueError(f"enrichment {field_name} exceeds the character limit")
    if (_UNSAFE_ENRICHMENT_CONTENT.search(value)
            or any(pattern.search(value) for pattern in _UNSAFE_ENRICHMENT_STRUCTURES)):
        raise ValueError(f"enrichment {field_name} contains prohibited content")
    _, redactions = strip_secrets(value)
    if redactions:
        raise ValueError(f"enrichment {field_name} contains a secret")
    return value


def validate_enrichment(enrichment: Mapping[str, object]) -> dict[str, object]:
    """Accept only bounded semantic state, never transcript-like payloads.

    The deterministic snapshot is the only capture path.  This later semantic
    stage may retain concise facts, but must reject rather than redact content
    that could be a transcript, diff, document body, or credential.
    """
    if not isinstance(enrichment, Mapping):
        raise ValueError("enrichment must be a mapping")
    if len(enrichment) > len(ENRICHMENT_FIELDS):
        raise ValueError("enrichment contains too many fields")

    normalized: dict[str, object] = {}
    for key, value in enrichment.items():
        if not isinstance(key, str):
            raise ValueError("enrichment keys must be strings")
        # Reuse the repository's key-level secret policy, but reject unsafe
        # data instead of accepting its redacted replacement.
        _, key_redactions = strip_secrets_json({key: "present"})
        if key_redactions:
            raise ValueError(f"enrichment key {key!r} is secret-shaped")
        if key not in ENRICHMENT_FIELDS:
            raise ValueError(f"enrichment key {key!r} is not allowed")
        if key in _ENRICHMENT_STRING_FIELDS:
            normalized[key] = _validate_enrichment_string(value, key)
            continue
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"enrichment {key} must be a list of strings")
        if len(value) > MAX_ENRICHMENT_LIST_ITEMS:
            raise ValueError(f"enrichment {key} has too many items")
        normalized[key] = [
            _validate_enrichment_string(item, key) for item in value
        ]

    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_ENRICHMENT_BYTES:
        raise ValueError("enrichment exceeds the total byte limit")
    return normalized


@dataclass(frozen=True)
class CheckpointSnapshot:
    session_id: str
    turn_id: str | None
    cursor: str
    source: str
    trigger: str | None
    cwd: str | None
    project_root: str | None
    transcript_fingerprint: str | None = None
    git: Mapping[str, object] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonblank(self.session_id, "session_id")
        _require_nonblank(self.cursor, "cursor")
        _require_nonblank(self.source, "source")
        if not isinstance(self.git, Mapping):
            raise ValueError("git must be a mapping")
        object.__setattr__(self, "git", dict(self.git))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class Checkpoint:
    id: str
    session_id: str
    turn_id: str | None
    cursor: str
    source: str
    trigger: str | None
    cwd: str | None
    project_root: str | None
    transcript_fingerprint: str | None
    git: Mapping[str, object]
    snapshot: Mapping[str, object]
    enrichment: Mapping[str, object]
    references: tuple[str, ...]
    warnings: tuple[str, ...]
    state: str
    quality: str
    compacted_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    def __post_init__(self) -> None:
        _require_nonblank(self.id, "id")
        _require_nonblank(self.session_id, "session_id")
        _require_nonblank(self.cursor, "cursor")
        _require_nonblank(self.source, "source")
        if self.state not in CHECKPOINT_STATES:
            raise ValueError(f"unknown checkpoint state: {self.state!r}")
        if self.quality not in CHECKPOINT_QUALITIES:
            raise ValueError(f"unknown checkpoint quality: {self.quality!r}")
        for name in ("git", "snapshot", "enrichment"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping")
            object.__setattr__(self, name, dict(value))
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "warnings", tuple(self.warnings))
