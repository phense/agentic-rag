"""Deterministic secret stripping — the write gateway's first line of defense."""
from __future__ import annotations

import re

_PATTERNS = [
    # (?<![A-Za-z0-9]): a real key starts at a word boundary. Without it the
    # pattern matched 'sk-' INSIDE ordinary words — ta[sk-list…], a[sk-…],
    # di[sk-…] — and redacted the rest (32 wiki bodies corrupted in
    # the 2026-07-06 ultra-memory migration). '_' before 'sk-' is still allowed
    # (safe direction: catches key_sk-…).
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),          # OpenAI/Anthropic-style
    re.compile(r"(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}"),           # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                               # AWS access key id
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),                   # Slack
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@]+@"),       # URL credentials
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),         # bearer tokens
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(                                                     # JWT
        r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{5,}"
    ),
    re.compile(                                                     # assignments
        # optional identifier prefix: client_secret, db_password, refresh_token…
        # (\b alone misses these: '_' is a word char, so \b never fires)
        r"(?i)\b[a-z0-9_.-]*(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b"
        r"\s*[=:]\s*['\"]?[^\s'\"]{8,}['\"]?"
    ),
]


def strip_secrets(text: str) -> tuple[str, int]:
    count = 0
    for pat in _PATTERNS:
        text, n = pat.subn("[REDACTED]", text)
        count += n
    return text, count


# keys whose ENTIRE value is a credential by construction — replaced whole,
# because value-pattern matching cannot recognise an arbitrary password string
_SECRET_KEY = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"authorization|credential)"
)


def strip_secrets_json(obj):
    """Recursively strip secrets from JSON-shaped data (dicts/lists/scalars).

    Returns (new_obj, redaction_count). Dict values under secret-ish keys are
    replaced whole; every other string runs through strip_secrets.
    """
    if isinstance(obj, dict):
        out, total = {}, 0
        for k, v in obj.items():
            if _SECRET_KEY.search(str(k)) and isinstance(v, str) and v:
                out[k] = "[REDACTED]"
                total += 1
            else:
                out[k], n = strip_secrets_json(v)
                total += n
        return out, total
    if isinstance(obj, list):
        items, total = [], 0
        for v in obj:
            item, n = strip_secrets_json(v)
            items.append(item)
            total += n
        return items, total
    if isinstance(obj, str):
        return strip_secrets(obj)
    return obj, 0
