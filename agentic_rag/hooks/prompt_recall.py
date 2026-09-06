"""UserPromptSubmit hook (spec §5, mechanism 2): recognize a CONCRETE error
signature in the prompt → deterministic SQL recall (<50 ms, no LLM, no
embedding) → inject pointers to stored signal docs and matching pins.

Strong error signals retain the existing pointer path. Explicit project/history
questions use the bounded local context service and deterministic lexical recall.
Errors are silent (logged) — SessionStart is the outage-visibility surface;
warning on every prompt would spam the session."""
from __future__ import annotations

import re
import sys

from .. import db
from ..config import load_config
from . import common

_MAX_HITS = 3
_MAX_SIG_LINES = 3
_QUERY_CAP = 300
_MAX_TOKENS = 8

# strong signals only (precision over recall)
_SIG_RES = [re.compile(p) for p in (
    r"Traceback \(most recent call last\)",
    r"\b[A-Za-z_][\w.]*(?:Error|Exception|Warning)\b",
    r"\b(?:Error|Errno|Exception)\s*:",
    r"\bNo such file or directory\b",
    r"\b[\w./\-]+\.[A-Za-z]{1,6}:\d+\b",
    r"\b(?:panic|segmentation fault|fatal error|core dumped)\b",
)]
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_STOP = {"the", "and", "for", "with", "this", "that", "line", "file",
         "most", "recent", "call", "last", "error", "exception"}


def detect_signature(text: str) -> str | None:
    if not text:
        return None
    hits = []
    for line in text.splitlines():
        s = line.strip()
        if s and any(rx.search(s) for rx in _SIG_RES):
            hits.append(s)
            if len(hits) >= _MAX_SIG_LINES:
                break
    return " ".join(hits)[:_QUERY_CAP] if hits else None


def tokens_to_tsquery(sig: str) -> str | None:
    """Sanitized OR-tsquery: to_tsquery-safe tokens joined with ' | '.
    OR, not AND — a signature line rarely reappears verbatim; any
    distinctive token (class name, module, message word) should recall."""
    seen: list[str] = []
    for t in _TOKEN.findall(sig):
        if t.lower() in _STOP or t in seen:
            continue
        seen.append(t)
        if len(seen) >= _MAX_TOKENS:
            break
    return " | ".join(seen) if seen else None


def _render(rows, pin_rows, stale_days: int, max_chars: int | None = None) -> str:
    from datetime import datetime, timezone
    lines = [
        "## agentic-rag recall — stored knowledge matches this error",
        "(auto-recalled by error signature; advisory context — verify "
        "before acting)",
    ]
    now = datetime.now(timezone.utc)
    for r in rows:
        anchor = r["verified_at"] or r["created_at"]
        marker = ""
        if (now - anchor).days > stale_days:
            marker = f" (unverified since {anchor:%Y-%m-%d})"
        detail=r.get('claim_evidence',{'kind':'legacy','review_state':'unreviewed','provenance_status':'incomplete','independent_source_count':0})
        label=f"{detail['kind']}; {detail['review_state']}; provenance {detail['provenance_status']}; user sources {detail['independent_source_count']}"
        lines.append(f"- [[{r['slug']}]] — {r['title']}{marker} ({label})")
    for p in pin_rows:
        lines.append(f"- pin: {p['body']}")
    if max_chars is not None:
        warning="⚠️ Recall entries omitted by the context budget."
        if len("\n".join(lines))>max_chars:
            while len(lines)>2 and len("\n".join(lines+[warning]))>max_chars:
                lines.pop()
            lines.append(warning)
    return "\n".join(lines)


def error_context(conn,cfg,project,sig,*,max_chars=None):
    q=tokens_to_tsquery(sig)
    if not q:return ""
    from ..scope import selection
    from ..pins import matching_pins
    scopes = selection(project, "project" if project else "global")
    rows = conn.execute(
        "SELECT * FROM recall_signals_scoped(%s, %s, %s)",
        (q, _MAX_HITS, scopes)).fetchall()
    from ..evidence import summary
    for row in rows:
        doc=conn.execute('SELECT id FROM documents WHERE slug=%s',(row['slug'],)).fetchone()
        row['claim_evidence']=summary(conn,str(doc['id']))
    pin_ids = [p.id for p in matching_pins(conn, project)]
    pin_rows = conn.execute(
        "SELECT body FROM pins WHERE active AND id = ANY(%s::uuid[])"
        " AND to_tsvector('english', body)"
        "     @@ to_tsquery('english', %s)"
        " ORDER BY priority, created_at LIMIT %s",
        (pin_ids, q, _MAX_HITS)).fetchall()
    return _render(rows,pin_rows,cfg.stale_days,max_chars) if rows or pin_rows else ""


def recall_context(prompt: str, project: str | None) -> str | None:
    """Prompt-mode context for one prompt, or None when nothing fires.

    Shared by the Antigravity ``PreInvocation`` dispatcher, which has no
    ``UserPromptSubmit`` event: the same error-signature and project/history
    gates as ``run`` decide, and the bounded local context service renders.
    Raises on database failure; callers decide how visible that is.
    """
    from .. import context, context_gate
    prompt = prompt or ""
    if not detect_signature(prompt) and not context_gate.detect(prompt, project):
        return None
    cfg = load_config()
    with db.connect(cfg, role="reader") as conn:
        result = context.build(conn, cfg, project=project, mode="prompt", prompt=prompt)
    return result["text"] or None


def run(payload: dict, stdout) -> None:
    try:
        if not common.is_interactive(payload):
            return
        from .. import context, context_gate
        prompt=payload.get('prompt') or ''
        if not detect_signature(prompt) and not context_gate.detect(prompt,payload.get('cwd')):
            return
        cfg=load_config()
        with db.connect(cfg,role='reader') as conn:
            result=context.build(conn,cfg,project=payload.get('cwd'),mode='prompt',prompt=prompt)
        text=result['text']
        if not text:
            return
        from ..scope import project_id
        key=context_gate.receipt_key(payload,project=project_id(payload['cwd']) if payload.get('cwd') else 'global',
            revision=result['revision'],config=result['config_key'],text=text,host=common.client_kind(payload)) if result['revision'] else None
        if context_gate.delivered(key):
            return
        common.emit_context(stdout,'UserPromptSubmit',text)
        context_gate.record(key)
    except Exception as e:
        common.log_hook_error('prompt_recall',repr(e))


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
