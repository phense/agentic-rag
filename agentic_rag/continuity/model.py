"""Typed contracts for deterministic and enriched continuation state."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


CHECKPOINT_STATES = frozenset({"open", "superseded", "completed"})
CHECKPOINT_QUALITIES = frozenset({"snapshot", "enriched"})


def _require_nonblank(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


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
