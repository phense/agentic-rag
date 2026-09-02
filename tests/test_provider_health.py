import json
from datetime import datetime, timedelta, timezone

from agentic_rag import provider_health

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def test_absent_health_file_is_none(tmp_path):
    assert provider_health.read_health(tmp_path / "absent.json") is None


def test_failure_preserves_first_failure_and_sanitizes(tmp_path):
    path = tmp_path / "provider-health.json"
    first = provider_health.record_failure(
        "codex", "token=abcdefghijklmnop failed", path=path, now=NOW)
    second = provider_health.record_failure(
        "codex", "still unavailable", path=path,
        now=NOW + timedelta(hours=1))
    assert second.first_failure_at == first.first_failure_at == NOW
    assert second.last_failure_at == NOW + timedelta(hours=1)
    assert "abcdefghijklmnop" not in path.read_text()
    assert second.available is False


def test_success_closes_circuit_atomically(tmp_path):
    path = tmp_path / "provider-health.json"
    provider_health.record_failure(
        "codex", "login required", path=path, now=NOW)
    state = provider_health.record_success(
        "codex", path=path, now=NOW + timedelta(hours=2))
    assert state.available is True
    assert state.last_success_at == NOW + timedelta(hours=2)
    assert not list(tmp_path.glob("*.tmp"))


def test_notification_timestamp_round_trips(tmp_path):
    path = tmp_path / "provider-health.json"
    provider_health.record_failure(
        "codex", "login required", path=path, now=NOW)
    state = provider_health.mark_notified(
        path=path, now=NOW + timedelta(minutes=5))
    loaded = provider_health.read_health(path)
    assert loaded == state
    assert loaded.last_notified_at == NOW + timedelta(minutes=5)


def test_malformed_health_is_visible_not_an_exception(tmp_path):
    path = tmp_path / "provider-health.json"
    path.write_text("not json")
    state = provider_health.read_health(path)
    assert state.available is False
    assert state.provider == "unknown"
    assert "malformed" in state.reason


def test_health_file_contains_only_expected_fields(tmp_path):
    path = tmp_path / "provider-health.json"
    provider_health.record_failure("codex", "down", path=path, now=NOW)
    assert set(json.loads(path.read_text())) == {
        "provider", "available", "first_failure_at", "last_failure_at",
        "last_success_at", "last_notified_at", "reason",
    }
