"""Schema-constrained semantic enrichment for continuation checkpoints."""
from __future__ import annotations

import json
import re
from typing import cast

from agentic_rag import llm
from agentic_rag.config import Config
from agentic_rag.secrets import strip_secrets
from agentic_rag.transcript import build_digest

from . import store
from .model import (
    ENRICHMENT_FIELDS,
    MAX_ENRICHMENT_LIST_ITEMS,
    MAX_ENRICHMENT_STRING_CHARS,
    validate_enrichment,
)


FIELD_ORDER = (
    "goal",
    "success_criteria",
    "instructions",
    "approvals",
    "decisions",
    "rejected_alternatives",
    "completed_steps",
    "remaining_steps",
    "files",
    "tests",
    "processes",
    "external_states",
    "blockers",
    "risks",
    "next_action",
    "rag_slugs",
)
_STRING_FIELDS = frozenset({"goal", "next_action"})
_EVIDENCE_FIELDS = ("tests", "processes", "external_states")
_EVIDENCE_MARKER = " | evidence: "
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _field_schema(name: str) -> dict:
    item = {"type": "string", "maxLength": MAX_ENRICHMENT_STRING_CHARS}
    if name in _STRING_FIELDS:
        return item
    schema = {
        "type": "array",
        "items": item,
        "maxItems": MAX_ENRICHMENT_LIST_ITEMS,
    }
    if name in _EVIDENCE_FIELDS:
        schema["description"] = (
            "Each item must use '<concise claim> | evidence: <brief literal "
            "fragment from the session delta>'; the evidence fragment must "
            "contain the claim verbatim after whitespace normalization."
        )
    elif name == "rag_slugs":
        schema["description"] = (
            "Only slugs explicitly referenced by [[slug]], slug=slug, "
            "slug: slug, or a memory-tool hint in the session delta."
        )
    return schema


ENRICHMENT_SCHEMA = {
    "type": "object",
    "properties": {name: _field_schema(name) for name in FIELD_ORDER},
    "required": list(FIELD_ORDER),
    "additionalProperties": False,
}

SYSTEM = (
    "Extract a concise continuation checkpoint from one bounded session delta. "
    "Use only facts explicitly evidenced in the supplied delta; do not invent "
    "or extrapolate. Keep every value short and semantic: never copy a "
    "transcript, file body, patch, or diff, and never emit a credential. "
    "Tests must include only commands and outcomes explicitly observed in the "
    "delta; never infer that a test passed. Every item in tests, processes, "
    "and external_states must use exactly '<concise claim> | evidence: "
    "<brief literal fragment from the session delta>', and that literal "
    "fragment must contain the claim verbatim. Processes and external states "
    "must include only observations explicitly present in the delta, phrased "
    "as past observations; never infer current process liveness or current "
    "external state. Use empty strings or arrays when evidence is absent. "
    "rag_slugs may contain only explicit [[slug]], slug=slug, slug: slug, or "
    "memory-tool references present in the delta."
)


def _prompt(digest: str) -> str:
    return (
        "SESSION DELTA (user/assistant prose and safe tool-name hints only):\n"
        f"{digest}\n\n"
        "Produce the continuation checkpoint object using every schema field."
    )


def _payload(job: dict) -> dict:
    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("checkpoint enrichment payload must be an object")
    return payload


def _normalize_evidence(value: str) -> str:
    return " ".join(value.split()).casefold()


def _slug_is_referenced(slug: str, digest: str) -> bool:
    escaped = re.escape(slug)
    explicit = re.compile(
        rf"(?:\[\[\s*{escaped}\s*\]\]|"
        rf"(?<![A-Za-z0-9_-])(?:slug|id_or_slug)\s*[:=]\s*{escaped}"
        rf"(?![a-z0-9-]))"
    )
    if explicit.search(digest):
        return True
    memory_hint = re.compile(
        rf"(?im)^\[[^\]\n]+ tool: [^\]\n]*memory_[^\]\s]+\s+"
        rf"[^\]\n]*(?<![a-z0-9-]){escaped}(?![a-z0-9-])[^\]\n]*\]$"
    )
    return memory_hint.search(digest) is not None


def _validate_grounding(enrichment: dict[str, object], digest: str) -> None:
    normalized_digest = _normalize_evidence(digest)
    for field in _EVIDENCE_FIELDS:
        for item in cast(list[str], enrichment[field]):
            claim, marker, evidence = item.partition(_EVIDENCE_MARKER)
            normalized_claim = _normalize_evidence(claim)
            normalized_fragment = _normalize_evidence(evidence)
            if (not marker or not normalized_claim or not normalized_fragment
                    or normalized_claim not in normalized_fragment
                    or normalized_fragment not in normalized_digest):
                raise ValueError(
                    f"checkpoint enrichment {field} item lacks digest evidence")

    for slug in cast(list[str], enrichment["rag_slugs"]):
        if not _SLUG.fullmatch(slug) or not _slug_is_referenced(slug, digest):
            raise ValueError(
                "checkpoint enrichment rag_slug lacks an accepted digest reference")


def enrich_checkpoint(
        conn, cfg: Config, job: dict, runner, *,
        on_provider_success=None) -> str | None:
    """Enrich one checkpoint from a bounded transcript delta.

    The checkpoint store remains the only persistence boundary.  The returned
    cursor is deliberately produced after that boundary has committed.
    """
    payload = _payload(job)
    checkpoint_id = payload.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
        raise ValueError("checkpoint enrichment requires checkpoint_id")
    transcript_path = job.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path.strip():
        raise ValueError("checkpoint enrichment requires transcript_path")

    digest = build_digest(
        transcript_path,
        after_uuid=job.get("last_uuid"),
        max_chars=cfg.mine_max_digest_chars,
        per_block=cfg.mine_per_block_chars,
        keep="tail",
    )
    clean_digest, _ = strip_secrets(digest.text)
    if not clean_digest.strip():
        return None

    try:
        data = llm.run_structured(
            _prompt(clean_digest), ENRICHMENT_SCHEMA, cfg,
            system=SYSTEM, runner=runner,
        )
    except llm.LLMJobError as exc:
        # The shared parser includes a bounded raw-output excerpt for ordinary
        # diagnostics.  A checkpoint must not persist that excerpt in its queue
        # error because malformed output could itself contain copied context.
        raise llm.LLMJobError(
            "checkpoint enrichment output was unusable") from exc
    if not isinstance(data, dict) or set(data) != set(FIELD_ORDER):
        raise ValueError("checkpoint enrichment output does not match the schema")
    normalized = validate_enrichment(data)
    # Guard the production schema and persistence allowlist against drifting
    # independently: either mismatch is a content-job failure, never a write.
    if set(normalized) != set(ENRICHMENT_FIELDS):
        raise ValueError("checkpoint enrichment output is incomplete")
    _validate_grounding(normalized, clean_digest)
    store.apply_enrichment(conn, checkpoint_id, normalized)
    if on_provider_success is not None:
        on_provider_success()
    return digest.last_uuid
