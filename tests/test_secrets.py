import pytest

from agentic_rag.secrets import strip_secrets


@pytest.mark.parametrize(
    "text",
    [
        "key=sk-abc123DEF456ghi789jkl012",
        "token ghp_abcdefghijklmnopqrstuvwxyz123456",
        "aws AKIAIOSFODNN7EXAMPLE",
        "slack xoxb-1234567890-abcdefghij",
        "password = 'Sup3rS3cret!!'",
        "api_key: 9f8e7d6c5b4a3f2e1d0c",
        "client_secret=abcdefgh12345678",
        "refresh_token: abcdefgh12345678",
        "db_password=Sup3rS3cret!!",
        "aws_secret_access_key=abcdefgh12345678",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dQw4w9WgXcQ_signature",
        "db url postgres://admin:S3cretPass99@localhost:5432/app",
        "header Authorization: Bearer abcdef1234567890abcdef",
    ],
)
def test_secrets_are_redacted(text):
    out, n = strip_secrets(text)
    assert n >= 1
    assert "sk-abc" not in out
    assert "ghp_" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "Sup3rS3cret" not in out
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "abcdefgh12345678" not in out
    assert "S3cretPass99" not in out
    assert "abcdef1234567890abcdef" not in out
    assert "[REDACTED]" in out


@pytest.mark.parametrize(
    "text",
    [
        "See [[risk-of-erosion]] for the sediment breakdown.",
        "field notes use an ask-and-answer format, not a summary",
        "the task-based-scheduler-configuration doc explains the cron",
        "disk-usage-monitoring-runbook-for-the-postgres-cluster",
        "[[flood-risk-mapping]] and [[risk-control-guidelines]]",
    ],
)
def test_sk_pattern_does_not_match_midword(text):
    """Regression (2026-07-06 migration find): the sk- API-key pattern lacked a
    left word boundary, so it matched 'sk-' INSIDE ordinary hyphenated words
    (ri[sk-], a[sk-], ta[sk-], di[sk-]) and redacted the tail — corrupting 32
    wiki bodies and their risk-* wikilinks. The word boundary must keep prose
    intact while still catching real keys (below)."""
    out, n = strip_secrets(text)
    assert out == text
    assert n == 0


@pytest.mark.parametrize(
    "text",
    [
        "sk-ant-api03-abcdefghijklmnop1234567890",   # at string start
        "key=sk-abc123DEF456ghi789jkl012",           # after '='
        "leaked: sk-proj-abcdefghijklmnop1234",       # after whitespace
        "prefix_sk-abcdefghijklmnop1234567",          # after '_' (safe direction)
    ],
)
def test_sk_key_still_redacted_at_boundary(text):
    """The lookbehind must not weaken real detection: a real sk- key preceded
    by start-of-string, a delimiter, or '_' is still redacted."""
    out, n = strip_secrets(text)
    assert n == 1
    assert "sk-a" not in out and "sk-p" not in out
    assert "[REDACTED]" in out


def test_clean_text_untouched():
    text = "Photosynthesis converts sunlight into chemical energy in green leaves."
    out, n = strip_secrets(text)
    assert out == text
    assert n == 0


def test_normal_prose_with_word_token_is_kept():
    text = "The session token concept is explained in the auth docs."
    out, n = strip_secrets(text)
    assert out == text
    assert n == 0


from agentic_rag.secrets import strip_secrets_json


def test_json_strip_redacts_values_under_secret_keys():
    obj = {"api_key": "abcdef123456", "note": "fine"}
    out, n = strip_secrets_json(obj)
    assert out == {"api_key": "[REDACTED]", "note": "fine"}
    assert n == 1


def test_json_strip_recurses_into_nested_structures():
    obj = {"prov": {"session": "s1", "token": "supersecretvalue"},
           "list": ["ok", "Bearer abcdefghijklmnopqrstuvwx"]}
    out, n = strip_secrets_json(obj)
    assert out["prov"]["token"] == "[REDACTED]"
    assert out["list"][0] == "ok"
    assert "[REDACTED]" in out["list"][1]
    assert n == 2


def test_json_strip_key_match_is_case_insensitive_and_affixed():
    out, n = strip_secrets_json({"DB_PASSWORD": "hunter22hunter22"})
    assert out == {"DB_PASSWORD": "[REDACTED]"}
    assert n == 1


def test_json_strip_leaves_non_strings_and_clean_data_alone():
    obj = {"count": 3, "ratio": 0.5, "flag": True, "none": None,
           "text": "no secrets here"}
    out, n = strip_secrets_json(obj)
    assert out == obj
    assert n == 0


def test_json_strip_plain_patterns_still_apply_inside_values():
    out, n = strip_secrets_json({"body": "key sk-abcdefghijklmnop1234 leaked"})
    assert "sk-" not in out["body"]
    assert n == 1
