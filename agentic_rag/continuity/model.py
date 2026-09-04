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
MIN_HANDOFF_CHARS = 400
HANDOFF_TRUNCATION_MARKER = "…[truncated]"
_HORIZONTAL_SPACE = re.compile(r"[ \t]+")
_BLANK_RUN = re.compile(r"\n{3,}")
# Claude's PostCompact ``compact_summary`` carries the model's raw compaction
# output: an ``<analysis>`` scratch block followed by the ``<summary>`` that
# Claude Code itself keeps.  Only the summary is worth a bounded handoff.
# The real tags start or end a line of their own; the prose may quote the
# same tags inline (observed live 2026-09-04 in a session about this very
# mechanism), so inline occurrences are content, never boundaries.
_ANALYSIS_CLOSE_LINE = re.compile(r"</analysis>[ \t]*$", re.MULTILINE)
_SUMMARY_OPEN_LINE = re.compile(r"^[ \t]*<summary>[ \t]*", re.MULTILINE)
_SUMMARY_CLOSE_LINE = re.compile(r"</summary>[ \t]*$", re.MULTILINE)
_SUMMARY_OPEN_INLINE = re.compile(r"<summary>")
_SUMMARY_CLOSE_INLINE = re.compile(r"</summary>")
_ANALYSIS_BLOCK = re.compile(r"<analysis>.*?(?:</analysis>|$)", re.DOTALL)
# Share of a truncated handoff kept from its head; the rest is its tail.
_HANDOFF_HEAD_SHARE = 0.6
# Labelled copies name their payload ("transcript", "diff", "body").  A path
# or identifier that merely contains the word — ``transcript.py``,
# ``hooks/transcript``, ``transcript_delta`` — is a fact a checkpoint must be
# able to state, so only prose occurrences count (issue #2).
_UNSAFE_ENRICHMENT_CONTENT = re.compile(
    r"(?i)(?<![/\\.])\b(?:transcript|diff|body)\b(?![/\\]|\.[a-z0-9])"
)
PROHIBITED_CONTENT = "prohibited content"
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


def _check_enrichment_string(value: object, field_name: str) -> str | None:
    """Return why ``value`` may not be stored as content, or ``None``.

    Shape and size faults and credentials raise: they are pipeline defects
    (malformed output, or the digest's own redaction seam failed) that must
    fail loudly.  Transcript-, diff-, or dialogue-shaped content is merely
    unstorable; the caller decides whether to reject or drop it.
    """
    if not isinstance(value, str):
        raise ValueError(f"enrichment {field_name} must be a string")
    if len(value) > MAX_ENRICHMENT_STRING_CHARS:
        raise ValueError(f"enrichment {field_name} exceeds the character limit")
    _, redactions = strip_secrets(value)
    if redactions:
        raise ValueError(f"enrichment {field_name} contains a secret")
    if (_UNSAFE_ENRICHMENT_CONTENT.search(value)
            or any(pattern.search(value) for pattern in _UNSAFE_ENRICHMENT_STRUCTURES)):
        return PROHIBITED_CONTENT
    return None


def _validate_enrichment_string(value: object, field_name: str) -> str:
    if (reason := _check_enrichment_string(value, field_name)) is not None:
        raise ValueError(f"enrichment {field_name} contains {reason}")
    return value


def _check_enrichment_key(key: object) -> str:
    if not isinstance(key, str):
        raise ValueError("enrichment keys must be strings")
    # Reuse the repository's key-level secret policy, but reject unsafe
    # data instead of accepting its redacted replacement.
    _, key_redactions = strip_secrets_json({key: "present"})
    if key_redactions:
        raise ValueError(f"enrichment key {key!r} is secret-shaped")
    if key not in ENRICHMENT_FIELDS:
        raise ValueError(f"enrichment key {key!r} is not allowed")
    return key


def _check_enrichment_list(value: object, key: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"enrichment {key} must be a list of strings")
    if len(value) > MAX_ENRICHMENT_LIST_ITEMS:
        raise ValueError(f"enrichment {key} has too many items")
    return list(value)


def _check_enrichment_size(normalized: Mapping[str, object]) -> None:
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_ENRICHMENT_BYTES:
        raise ValueError("enrichment exceeds the total byte limit")


def validate_enrichment(enrichment: Mapping[str, object]) -> dict[str, object]:
    """Accept only bounded semantic state, never transcript-like payloads.

    The deterministic snapshot is the only capture path.  This later semantic
    stage may retain concise facts, but must reject rather than redact content
    that could be a transcript, diff, document body, or credential.  This is
    the store's gate: any offending value voids the whole object.
    """
    if not isinstance(enrichment, Mapping):
        raise ValueError("enrichment must be a mapping")
    if len(enrichment) > len(ENRICHMENT_FIELDS):
        raise ValueError("enrichment contains too many fields")

    normalized: dict[str, object] = {}
    for key, value in enrichment.items():
        key = _check_enrichment_key(key)
        if key in _ENRICHMENT_STRING_FIELDS:
            normalized[key] = _validate_enrichment_string(value, key)
            continue
        normalized[key] = [
            _validate_enrichment_string(item, key)
            for item in _check_enrichment_list(value, key)
        ]
    _check_enrichment_size(normalized)
    return normalized


def dropped_warning(field: str, count: int, reason: str) -> str:
    """The checkpoint warning recorded for values screened out of enrichment."""
    noun = "item" if count == 1 else "items"
    return f"enrichment {field}: {count} {noun} dropped ({reason})"


def screen_enrichment(
        enrichment: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    """Drop unstorable values from model output instead of voiding it.

    A string field becomes empty and a list loses only its offending items;
    each drop is named in the returned warnings (field, count, reason — never
    the value).  Shape faults and credentials still raise, exactly as
    ``validate_enrichment`` does, so the result always passes that gate.
    """
    if not isinstance(enrichment, Mapping):
        raise ValueError("enrichment must be a mapping")
    if len(enrichment) > len(ENRICHMENT_FIELDS):
        raise ValueError("enrichment contains too many fields")

    screened: dict[str, object] = {}
    warnings: list[str] = []
    for key, value in enrichment.items():
        key = _check_enrichment_key(key)
        if key in _ENRICHMENT_STRING_FIELDS:
            if (reason := _check_enrichment_string(value, key)) is None:
                screened[key] = value
            else:
                screened[key] = ""
                warnings.append(dropped_warning(key, 1, reason))
            continue
        kept: list[str] = []
        dropped: dict[str, int] = {}
        for item in _check_enrichment_list(value, key):
            if (reason := _check_enrichment_string(item, key)) is None:
                kept.append(item)
            else:
                dropped[reason] = dropped.get(reason, 0) + 1
        screened[key] = kept
        warnings.extend(
            dropped_warning(key, count, reason) for reason, count in dropped.items()
        )
    _check_enrichment_size(screened)
    return screened, warnings


def _summary_only(text: str) -> str:
    """Keep the ``<summary>`` body of a raw Claude compaction output and drop
    the ``<analysis>`` scratch block; plain text passes through unchanged.

    Boundaries are tags on lines of their own: the first ``<summary>`` that
    starts a line after the first ``</analysis>`` that ends one opens the
    body, and the last ``</summary>`` ending a line after it closes the body
    (else the text end).  Tags quoted inline in the prose are content.  Without
    line tags the first inline ``<summary>`` opens the body up to the last
    inline ``</summary>``; without any ``<summary>`` an ``<analysis>`` block is
    stripped.
    """
    for opener, closer, start in (
        (_SUMMARY_OPEN_LINE, _SUMMARY_CLOSE_LINE, _analysis_end(text)),
        (_SUMMARY_OPEN_INLINE, _SUMMARY_CLOSE_INLINE, 0),
    ):
        if (opened := opener.search(text, start)) is None:
            continue
        closes = list(closer.finditer(text, opened.end()))
        body = text[opened.end():closes[-1].start() if closes else len(text)]
        if body.strip():
            return body
    stripped = _ANALYSIS_BLOCK.sub("", text)
    return stripped if stripped.strip() else text


def _analysis_end(text: str) -> int:
    match = _ANALYSIS_CLOSE_LINE.search(text)
    return match.end() if match else 0


def truncate_middle(text: str, max_chars: int) -> str:
    """Shorten ``text`` to at most ``max_chars`` by cutting out its middle.

    A compact summary states the objective and constraints first and the
    pending work, current state, and next step last, so both ends survive;
    ``HANDOFF_TRUNCATION_MARKER`` stands on a line of its own between them.
    """
    if len(text) <= max_chars:
        return text
    marker = f"\n{HANDOFF_TRUNCATION_MARKER}\n"
    budget = max_chars - len(marker)
    if budget < 2:
        return text[:max_chars]
    head = int(budget * _HANDOFF_HEAD_SHARE)
    tail = budget - head
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def bound_handoff(text: object, *, max_chars: int) -> str:
    """Normalize, secret-strip, and truncate a client compact summary.

    The handoff keeps its line structure (it is prose the client wrote for
    its own continuation) but never grows past ``max_chars`` and never
    carries a secret-shaped value into the store.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("handoff must be a non-blank string")
    if (
        not isinstance(max_chars, int)
        or isinstance(max_chars, bool)
        or max_chars < MIN_HANDOFF_CHARS
    ):
        raise ValueError(
            f"max_chars must be an integer of at least {MIN_HANDOFF_CHARS}"
        )
    text = _summary_only(text)
    normalized = _HORIZONTAL_SPACE.sub(" ", text.replace("\r\n", "\n")).strip()
    normalized = _BLANK_RUN.sub("\n\n", normalized)
    stripped, _ = strip_secrets(normalized)
    return truncate_middle(stripped, max_chars)


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
    predecessor_cursor: str | None = None
    handoff: str | None = None
    handoff_at: datetime | None = None

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
