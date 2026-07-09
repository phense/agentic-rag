"""UserPromptSubmit hook (spec §5, mechanism 2): recognize a CONCRETE error
signature in the prompt → deterministic SQL recall (<50 ms, no LLM, no
embedding) → inject pointers to stored signal docs and matching pins.

Conservative by design (the ultra-memory recall-reflex, which demonstrably
worked): fires only on strong error signals, never on plain questions.
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


def _render(rows, pin_rows, stale_days: int) -> str:
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
        lines.append(f"- [[{r['slug']}]] — {r['title']}{marker}")
    for p in pin_rows:
        lines.append(f"- pin: {p['body']}")
    return "\n".join(lines)


def run(payload: dict, stdout) -> None:
    try:
        if not common.is_interactive(payload):
            return
        sig = detect_signature(payload.get("prompt") or "")
        if not sig:
            return
        q = tokens_to_tsquery(sig)
        if not q:
            return
        cfg = load_config()
        conn = db.connect(cfg, role="reader")
        try:
            rows = conn.execute(
                "SELECT * FROM recall_signals(%s, %s)",
                (q, _MAX_HITS)).fetchall()
            pin_rows = conn.execute(
                "SELECT body FROM pins WHERE active"
                " AND to_tsvector('english', body)"
                "     @@ to_tsquery('english', %s)"
                " ORDER BY priority, created_at LIMIT %s",
                (q, _MAX_HITS)).fetchall()
        finally:
            conn.close()
        if not rows and not pin_rows:
            return
        common.emit_context(stdout, "UserPromptSubmit",
                            _render(rows, pin_rows, cfg.stale_days))
    except Exception as e:  # noqa: BLE001 — silent by design (see docstring)
        common.log_hook_error("prompt_recall", repr(e))


def main() -> int:
    run(common.read_payload(sys.stdin), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
