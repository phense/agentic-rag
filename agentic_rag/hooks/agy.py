"""Antigravity CLI (``agy``) hook dispatcher: ``python -m agentic_rag.hooks.agy <event>``.

Antigravity has no PreCompact/PostCompact/SessionEnd/UserPromptSubmit
events and its payloads are camelCase (``conversationId``,
``workspacePaths``, ``transcriptPath``).  This module translates each of the
three installed events into the shared provider-neutral machinery:

``session-start``
    Inject pins, the domain map, project knowledge, and the continuation
    checkpoint as one ephemeral message (fail-closed-VISIBLE, like Claude's
    ``SessionStart``); trigger the daily maintenance guarantee.

``pre-invocation``
    Runs before every model call; only the first invocation of a turn
    (``invocationNum == 0``) does work.  It reads the transcript tail and
    (a) treats a trailing ``/compact`` request as PreCompact: persists the
    checkpoint, queues enrichment, and injects the versioned compact prompt
    plus the checkpoint id; (b) treats a new automatic-compaction marker as
    PreCompact+PostCompact in one step and re-injects the checkpoint, because
    no SessionStart follows an automatic compaction; (c) injects error-
    signature recall for the new prompt.

``stop``
    Attaches the model's ``/compact`` summary as the checkpoint handoff
    (PostCompact) and queues the transcript delta for mining.

Contract: never block the agent.  Every failure is logged to the hook log and
the process prints a valid JSON object and exits 0.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from . import common

EVENTS = ("session-start", "pre-invocation", "stop")
CLIENT = "agy"
_SOURCE_PRE_COMPACT = "PreCompact"


def _session_id(payload: dict) -> str | None:
    value = payload.get("conversationId")
    return value if isinstance(value, str) and value.strip() else None


def _cwd(payload: dict) -> str | None:
    paths = payload.get("workspacePaths")
    if isinstance(paths, list):
        for item in paths:
            if isinstance(item, str) and item.strip():
                return item
    return None


def _transcript(payload: dict) -> str | None:
    value = payload.get("transcriptPath")
    if isinstance(value, str) and value.strip() and Path(value).is_file():
        return value
    return None


def internal_payload(payload: dict, **extra) -> dict:
    """The snake_case payload shape the shared hook modules understand."""
    data = {
        "session_id": _session_id(payload),
        "cwd": _cwd(payload),
        "transcript_path": payload.get("transcriptPath")
        if isinstance(payload.get("transcriptPath"), str) else None,
        "client": CLIENT,
    }
    data.update(extra)
    return data


def inject(*messages: str) -> dict:
    steps = [{"ephemeralMessage": text} for text in messages if text and text.strip()]
    return {"injectSteps": steps} if steps else {}


# --------------------------------------------------------------------- events

def session_start(payload: dict) -> dict:
    from .. import db
    from ..config import load_config
    from . import session_start as shared

    session_id = _session_id(payload)
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            text = shared.build_context(
                conn, cfg, _cwd(payload), session_id=session_id, source="startup")
            shared._trigger_maintenance(conn)
        finally:
            conn.close()
        return inject(text)
    except Exception as exc:  # noqa: BLE001 — fail closed, VISIBLY
        common.log_hook_error("agy.session_start", repr(exc))
        safe = common.sanitize_error(f"{type(exc).__name__}: {exc}")
        return inject(f"⚠️ agentic-rag unavailable: {safe}")


def _persist_pre_compact(conn, cfg, payload: dict, *, cursor: str,
                         trigger: str, transcript: str):
    """PreCompact for agy: seed, repository state, enrichment queue."""
    from .. import jobs
    from ..continuity import capture, store

    seed = capture.capture_snapshot_seed(internal_payload(
        payload, hook_event_name=_SOURCE_PRE_COMPACT, trigger=trigger,
        transcript_path=transcript))
    seed = replace(seed, cursor=cursor, source=_SOURCE_PRE_COMPACT)
    checkpoint = store.upsert_snapshot(conn, seed, update_existing=False)
    if checkpoint.compacted_at is not None:
        return checkpoint, False
    try:
        enriched = capture.capture_repository_state(seed, cwd=_cwd(payload))
        checkpoint = store.upsert_snapshot(conn, enriched)
    except Exception as exc:  # noqa: BLE001 — seed is already durable
        common.log_hook_error("agy.pre_compact", repr(exc))
    jobs.enqueue_checkpoint_enrichment(
        conn, checkpoint_id=checkpoint.id, session_id=checkpoint.session_id,
        transcript_path=transcript, after_cursor=checkpoint.predecessor_cursor)
    common.spawn_worker()
    return checkpoint, True


def _manual_compaction(conn, cfg, payload: dict, request, transcript: str) -> str:
    from ..integrations.agy.prompt import CHECKPOINT_LINE_PREFIX, compact_prompt_text

    checkpoint_id = None
    try:
        checkpoint, _ = _persist_pre_compact(
            conn, cfg, payload, cursor=request.identity, trigger="manual",
            transcript=transcript)
        checkpoint_id = checkpoint.id
    except Exception as exc:  # noqa: BLE001 — the prompt still improves the summary
        common.log_hook_error("agy.pre_compact", repr(exc))
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
    text = compact_prompt_text().rstrip("\n")
    if checkpoint_id:
        text += f"\n{CHECKPOINT_LINE_PREFIX}{checkpoint_id}\n"
    return text


def _auto_compaction(conn, cfg, payload: dict, marker, transcript: str) -> str | None:
    """A marker that is new to the store: record boundary + handoff, restore."""
    from ..continuity import store
    from ..transcript_agy import auto_compaction_summary
    from . import session_start as shared

    checkpoint, fresh = _persist_pre_compact(
        conn, cfg, payload, cursor=marker.identity, trigger="auto",
        transcript=transcript)
    if not fresh:
        return None
    store.mark_compacted(conn, checkpoint.session_id, checkpoint.cursor)
    summary = auto_compaction_summary(marker)
    if summary:
        try:
            store.attach_handoff(
                conn, checkpoint.id, summary,
                max_chars=cfg.checkpoint_handoff_max_chars)
        except Exception as exc:  # noqa: BLE001 — the boundary is already marked
            common.log_hook_error("agy.auto_compaction.handoff", repr(exc))
    common.log_hook_error(
        "agy.auto_compaction",
        f"observed marker step {marker.index} type={marker.type!r}; "
        f"checkpoint {checkpoint.id} restored")
    return shared.build_context(
        conn, cfg, _cwd(payload), session_id=checkpoint.session_id, source="compact")


def pre_invocation(payload: dict) -> dict:
    from .. import db
    from ..config import load_config
    from .. import transcript_agy as ta
    from . import prompt_recall

    if payload.get("invocationNum", 0) not in (0, None):
        return {}
    session_id = _session_id(payload)
    transcript = _transcript(payload)
    if session_id is None or transcript is None:
        return {}
    steps = ta.read_tail_steps(transcript)
    if not steps:
        return {}
    messages: list[str] = []
    request = ta.manual_compaction(steps)
    marker = None if request is not None else ta.latest_auto_compaction(steps)
    try:
        cfg = load_config()
        conn = db.connect(cfg, role="writer")
        try:
            if request is not None:
                messages.append(_manual_compaction(conn, cfg, payload, request, transcript))
            elif marker is not None:
                restored = _auto_compaction(conn, cfg, payload, marker, transcript)
                if restored:
                    messages.append(restored)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — fail open; SessionStart is the visible surface
        common.log_hook_error("agy.pre_invocation", repr(exc))
    if request is None:
        last = ta.last_user_input(steps)
        if last is not None:
            try:
                recalled = prompt_recall.recall_context(
                    ta.user_request_text(last.content), _cwd(payload))
                if recalled:
                    messages.append(recalled)
            except Exception as exc:  # noqa: BLE001 — silent by design
                common.log_hook_error("agy.prompt_recall", repr(exc))
    return inject(*messages)


def _attach_manual_handoff(payload: dict, session_id: str, transcript: str) -> None:
    from .. import db
    from ..config import load_config
    from ..continuity import store
    from .. import transcript_agy as ta

    steps = ta.read_tail_steps(transcript)
    request = None
    for step in reversed(steps):
        if step.is_user_input:
            request = step if ta.is_compact_request(step.content) else None
            break
    if request is None:
        return
    summary = ta.compaction_summary(steps, request.index)
    cfg = load_config()
    conn = db.connect(cfg, role="writer")
    try:
        checkpoint = store.latest_pre_compact(conn, session_id, "manual")
        if checkpoint is None or checkpoint.cursor != request.identity:
            return
        store.mark_compacted(conn, session_id, checkpoint.cursor)
        if summary:
            store.attach_handoff(
                conn, checkpoint.id, summary,
                max_chars=cfg.checkpoint_handoff_max_chars)
    finally:
        conn.close()


def stop(payload: dict) -> dict:
    from . import transcript_delta

    session_id = _session_id(payload)
    transcript = _transcript(payload)
    if session_id and transcript:
        try:
            _attach_manual_handoff(payload, session_id, transcript)
        except Exception as exc:  # noqa: BLE001 — mining enqueue still runs
            common.log_hook_error("agy.post_compact", repr(exc))
    transcript_delta.enqueue_transcript_delta(
        internal_payload(payload), hook="agy.stop")
    return {}


_HANDLERS = {
    "session-start": session_start,
    "pre-invocation": pre_invocation,
    "stop": stop,
}


def run(event: str, payload: dict) -> dict:
    handler = _HANDLERS.get(event)
    if handler is None or not common.is_interactive(payload):
        return {}
    try:
        return handler(payload)
    except Exception as exc:  # noqa: BLE001 — never block the agent
        common.log_hook_error(f"agy.{event}", repr(exc))
        return {}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    event = args[0] if args else ""
    result = run(event, common.read_payload(sys.stdin))
    try:
        json.dump(result, sys.stdout)
    except (TypeError, ValueError):
        sys.stdout.write("{}")
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
