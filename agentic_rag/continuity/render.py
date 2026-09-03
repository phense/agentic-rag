"""Strict-budget, reference-oriented continuation rendering."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from agentic_rag.secrets import strip_secrets

from .model import Checkpoint


_SPACE = re.compile(r"\s+")
_ROOT_ARTIFACTS = frozenset({"AGENTS.md", "CLAUDE.md", "BACKLOG.md", "FEATURES.md"})
_ARTIFACT_PREFIXES = ("docs/superpowers/specs/", "docs/superpowers/plans/")


@dataclass(frozen=True)
class _Section:
    order: int
    drop_order: int | None
    label: str
    value: str

    @property
    def line(self) -> str:
        return f"{self.label}{self.value}"


def _clean(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned, _ = strip_secrets(_SPACE.sub(" ", value).strip())
    return cleaned


def _items(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [cleaned for item in value if (cleaned := _clean(item))]


def _joined(value: object) -> str:
    return "; ".join(_items(value))


def _artifact(value: object) -> str:
    cleaned = _clean(value)
    if cleaned in _ROOT_ARTIFACTS or cleaned.startswith(_ARTIFACT_PREFIXES):
        return cleaned
    return ""


def _slug(value: object) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return ""
    if cleaned.startswith("[[") and cleaned.endswith("]]" ):
        return cleaned
    return f"[[{cleaned}]]"


def _repository(checkpoint: Checkpoint) -> str:
    git = checkpoint.git if isinstance(checkpoint.git, Mapping) else {}
    details = []
    for label, key in (
        ("worktree", "worktree"),
        ("branch", "branch"),
        ("HEAD", "head"),
        ("status", "status"),
    ):
        if value := _clean(git.get(key)):
            details.append(f"{label}={value}")
    if not any(part.startswith("worktree=") for part in details):
        if cwd := _clean(checkpoint.cwd):
            details.insert(0, f"worktree={cwd}")
    return "; ".join(details)


def _render(sections: Iterable[_Section]) -> str:
    return "\n".join(section.line for section in sorted(sections, key=lambda item: item.order))


def _fit_required(required: list[_Section], max_chars: int) -> str:
    label_chars = sum(len(section.label) for section in required) + len(required) - 1
    if max_chars <= label_chars:
        return _render(required)[:max_chars]
    available = max_chars - label_chars
    values = [section.value for section in required]
    while sum(len(value) for value in values) > available:
        index = max(range(len(values)), key=lambda item: len(values[item]))
        excess = sum(len(value) for value in values) - available
        new_length = max(1, len(values[index]) - excess)
        if new_length >= len(values[index]):
            break
        values[index] = values[index][:new_length]
    fitted = [
        _Section(section.order, section.drop_order, section.label, value)
        for section, value in zip(required, values, strict=True)
    ]
    return _render(fitted)[:max_chars]


def _fit_sections(
    required: list[_Section], optional: list[_Section], max_chars: int
) -> str:
    if len(_render(required)) > max_chars:
        return _fit_required(required, max_chars)

    selected = [*required, *optional]
    while len(_render(selected)) > max_chars and len(optional) > 1:
        removable = max(optional, key=lambda section: section.drop_order or 0)
        optional.remove(removable)
        selected.remove(removable)
    rendered = _render(selected)
    if len(rendered) <= max_chars:
        return rendered
    if not optional:
        return _fit_required(required, max_chars)

    retained = optional[0]
    without_value = _render([*required, _Section(
        retained.order, retained.drop_order, retained.label, ""
    )])
    value_budget = max_chars - len(without_value)
    if value_budget <= 0:
        return _fit_required(required, max_chars)
    truncated = _Section(
        retained.order,
        retained.drop_order,
        retained.label,
        retained.value[:value_budget],
    )
    return _render([*required, truncated])


def render_checkpoint(checkpoint: Checkpoint, *, max_chars: int) -> str:
    """Render checkpoint state in semantic priority order within ``max_chars``."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    enrichment = checkpoint.enrichment if isinstance(checkpoint.enrichment, Mapping) else {}
    quality = _clean(checkpoint.quality) or "unknown"
    identity = f"{_clean(checkpoint.id)} [{quality}]"
    if quality == "snapshot":
        identity += " — semantic enrichment pending"

    blockers = _joined(enrichment.get("blockers")) or "none recorded"
    next_action = _clean(enrichment.get("next_action")) or "Revalidate state and determine the next action"
    required = [
        _Section(0, None, "Checkpoint ", identity),
        _Section(60, None, "Blockers: ", blockers),
        _Section(70, None, "Next exact action: ", next_action),
    ]
    optional: list[_Section] = []
    if goal := _clean(enrichment.get("goal")):
        optional.append(_Section(10, 40, "Goal: ", goal))
    criteria = _items(enrichment.get("success_criteria"))
    remaining = _items(enrichment.get("remaining_steps"))
    if criteria or remaining:
        value = "; ".join([*criteria, *remaining])
        optional.append(_Section(20, 50, "Remaining criteria/steps: ", value))
    if repository := _repository(checkpoint):
        optional.append(_Section(30, 60, "Repository: ", repository))
    if tests := _joined(enrichment.get("tests")):
        optional.append(_Section(40, 70, "Verified tests: ", tests))

    volatile = []
    if processes := _joined(enrichment.get("processes")):
        volatile.append(f"processes={processes}")
    if external := _joined(enrichment.get("external_states")):
        volatile.append(f"external={external}")
    if volatile:
        optional.append(
            _Section(50, 110, "Volatile state (revalidate): ", "; ".join(volatile))
        )

    references = [
        reference for value in checkpoint.references if (reference := _artifact(value))
    ]
    references.extend(
        slug for value in _items(enrichment.get("rag_slugs")) if (slug := _slug(value))
    )
    if references:
        optional.append(_Section(80, 90, "Artifacts/slugs: ", "; ".join(references)))
    if warnings := "; ".join(_clean(value) for value in checkpoint.warnings if _clean(value)):
        optional.append(_Section(90, 100, "Warnings: ", warnings))

    return _fit_sections(required, optional, max_chars)
