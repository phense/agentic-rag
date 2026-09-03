"""Atomic, secret-sanitized health state for the configured LLM provider."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .secrets import strip_secrets

HEALTH_PATH = Path.home() / ".agentic-rag" / "state" / "provider-health.json"


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    available: bool
    first_failure_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    last_notified_at: datetime | None = None
    reason: str | None = None


_TIME_FIELDS = {
    "first_failure_at", "last_failure_at", "last_success_at",
    "last_notified_at",
}


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _path(path: Path | None) -> Path:
    return HEALTH_PATH if path is None else path


def _serialize(state: ProviderHealth) -> dict:
    data = asdict(state)
    for key in _TIME_FIELDS:
        value = data[key]
        data[key] = value.isoformat() if value is not None else None
    return data


def _write(state: ProviderHealth, path: Path | None = None) -> ProviderHealth:
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(_serialize(state), fh, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return state


def read_health(path: Path | None = None) -> ProviderHealth | None:
    target = _path(path)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        for key in _TIME_FIELDS:
            value = data.get(key)
            data[key] = datetime.fromisoformat(value) if value else None
        return ProviderHealth(**data)
    except (OSError, ValueError, TypeError, KeyError) as e:
        reason = strip_secrets(f"malformed provider health: {type(e).__name__}: {e}")[0]
        return ProviderHealth("unknown", False, reason=reason)


def record_failure(provider: str, reason: str, *, path: Path | None = None,
                   now: datetime | None = None) -> ProviderHealth:
    at = _now(now)
    previous = read_health(path)
    same_outage = (
        previous is not None and not previous.available
        and previous.provider == provider
    )
    clean = strip_secrets(reason)[0][:500]
    state = ProviderHealth(
        provider=provider,
        available=False,
        first_failure_at=(previous.first_failure_at if same_outage else at),
        last_failure_at=at,
        last_success_at=(previous.last_success_at if previous else None),
        last_notified_at=(previous.last_notified_at if same_outage else None),
        reason=clean,
    )
    return _write(state, path)


def record_success(provider: str, *, path: Path | None = None,
                   now: datetime | None = None) -> ProviderHealth:
    previous = read_health(path)
    state = ProviderHealth(
        provider=provider,
        available=True,
        first_failure_at=(previous.first_failure_at if previous else None),
        last_failure_at=(previous.last_failure_at if previous else None),
        last_success_at=_now(now),
        last_notified_at=(previous.last_notified_at if previous else None),
        reason=(previous.reason if previous else None),
    )
    return _write(state, path)


def mark_notified(*, path: Path | None = None,
                  now: datetime | None = None) -> ProviderHealth:
    previous = read_health(path)
    if previous is None:
        raise ValueError("cannot mark absent provider health as notified")
    state = ProviderHealth(
        provider=previous.provider,
        available=previous.available,
        first_failure_at=previous.first_failure_at,
        last_failure_at=previous.last_failure_at,
        last_success_at=previous.last_success_at,
        last_notified_at=_now(now),
        reason=previous.reason,
    )
    return _write(state, path)
