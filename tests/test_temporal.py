"""RAG-064 T064-001: deterministic EN/DE calendar interpretation without providers."""
from datetime import datetime, timedelta, timezone
import ast
import json
from pathlib import Path

import pytest

from agentic_rag import temporal

FIXTURES = Path(__file__).resolve().parents[1] / 'docs/benchmarks/2026-10-31-temporal-query/fixtures'
DEV = json.loads((FIXTURES / 'parser-cases.json').read_text())['dev']
R1 = '2026-10-30T10:00:00+01:00'


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


@pytest.mark.parametrize('case', DEV, ids=[c['id'] for c in DEV])
def test_frozen_development_cases(case):
    expected = case['expected']
    if 'error' in expected:
        with pytest.raises(ValueError, match=expected['error']):
            temporal.interpret(case['query'], reference=case['reference'], timezone=case['timezone'])
        return
    result = temporal.interpret(case['query'], reference=case['reference'], timezone=case['timezone'])
    assert result.status == expected['status'], result.reasons
    if expected['status'] == 'interval':
        assert (result.start, result.end) == (utc(expected['start']), utc(expected['end']))
    else:
        assert result.start is None and result.end is None


def test_calendar_semantics_dst_week_and_year_boundaries():
    # Spring-forward day has 23 hours; the DST-crossing autumn week has 169.
    day = temporal.interpret('gestern', reference='2026-03-30T09:00:00+02:00', timezone='Europe/Berlin')
    assert day.end - day.start == timedelta(hours=23)
    week = temporal.interpret('last week', reference=R1, timezone='Europe/Berlin')
    assert week.end - week.start == timedelta(hours=169)
    assert week.start.astimezone(temporal.parse_zone('Europe/Berlin')).weekday() == 0
    rollover = temporal.interpret('next month', reference='2026-12-31T23:59:00+00:00', timezone='UTC')
    assert (rollover.start, rollover.end) == (utc('2027-01-01T00:00:00Z'), utc('2027-02-01T00:00:00Z'))
    # The same instant is a different local calendar day in another zone.
    tokyo = temporal.interpret('yesterday', reference='2026-10-30T20:00:00Z', timezone='Asia/Tokyo')
    assert tokyo.start == utc('2026-10-29T15:00:00Z')


def test_half_open_interval_membership():
    result = temporal.interpret('2026-10-14', reference=R1, timezone='UTC')
    assert result.contains(utc('2026-10-14T00:00:00Z'))
    assert result.contains(utc('2026-10-14T23:59:59.999999Z'))
    assert not result.contains(utc('2026-10-15T00:00:00Z'))
    assert not result.contains(None)


def test_reference_is_captured_once_and_never_naive(monkeypatch):
    calls = []
    real = temporal._now
    monkeypatch.setattr(temporal, '_now', lambda: calls.append(1) or real())
    result = temporal.interpret('gestern und yesterday und gestern', timezone='Europe/Berlin')
    assert len(calls) == 1 and result.reference_source == 'clock'
    calls.clear()
    explicit = temporal.interpret('gestern', reference=R1)
    assert calls == [] and explicit.reference == utc('2026-10-30T09:00:00Z')
    assert explicit.reference_source == 'request'
    for bad in ('2026-10-30T10:00:00', 'yesterday', '', 12, datetime(2026, 10, 30)):
        with pytest.raises(ValueError, match='invalid_reference'):
            temporal.interpret('gestern', reference=bad)


@pytest.mark.parametrize('zone', ['Mars/Olympus', '', '../etc/passwd', '/etc/localtime', 'Europe/../UTC',
                                  'x' * 80, None, 5, 'localtime'])
def test_timezone_must_be_bounded_iana_name(zone):
    with pytest.raises(ValueError, match='invalid_timezone'):
        temporal.parse_zone(zone)


def test_modes_are_validated():
    for mode in ('auto', 'off', 'prefer', 'filter'):
        temporal.validate_mode(mode)
    for mode in ('on', 'strict', '', 'PREFER', None, 1):
        with pytest.raises(ValueError, match='invalid_temporal_mode'):
            temporal.validate_mode(mode)


def test_current_intent_supplies_no_invented_interval():
    result = temporal.interpret('aktuell gültiger Port', reference=R1)
    assert result.status == 'current' and result.start is None
    assert 'no_recency_interval' in result.reasons
    assert result.residual is None


def test_residual_keeps_meaningful_terms_symbols_and_date_only_queries():
    stripped = temporal.interpret('nightly backup job failed yesterday', reference=R1)
    assert stripped.residual == 'nightly backup job failed'
    ranged = temporal.interpret('VPN tunnel dropped from 2026-10-01 to 2026-10-03', reference=R1)
    assert ranged.residual == 'VPN tunnel dropped'
    symbol = temporal.interpret('ERR_TLS_HANDSHAKE gestern', reference=R1)
    assert symbol.residual == 'ERR_TLS_HANDSHAKE'
    # Date-only queries keep the original text for retrieval.
    assert temporal.interpret('gestern', reference=R1).residual is None
    assert temporal.interpret('on 2026-10-14', reference=R1).residual is None
    # Unsafe interpretations never rewrite the query.
    assert temporal.interpret('backup gestern und letzte Woche', reference=R1).residual is None
    # A date inside a selector-like token is not an expression.
    slug = temporal.interpret('release-notes-2026-10-14', reference=R1)
    assert slug.status == 'none' and slug.residual is None


def test_bounded_input_and_expression_count():
    long = temporal.interpret('gestern ' + 'x' * temporal.MAX_QUERY_CHARS, reference=R1)
    assert long.status == 'unsupported' and long.reasons == ('query_too_long',)
    many = temporal.interpret(' '.join(['gestern'] * (temporal.MAX_EXPRESSIONS + 1)), reference=R1)
    assert many.status == 'ambiguous' and 'too_many_expressions' in many.reasons


def test_unsupported_relative_forms_are_reported_not_guessed():
    for query in ('backup today', 'Ausfall heute', 'last month', 'letzten Monat', 'vor 3 Tagen',
                  'last 7 days', 'recently changed', 'Termin 14.10.26', 'May 5 audit'):
        result = temporal.interpret(query, reference=R1)
        assert result.status == 'unsupported', query
        assert result.start is None


def test_description_is_bounded_and_carries_no_query_text():
    result = temporal.interpret('secret-project gestern', reference=R1, timezone='Europe/Berlin')
    described = result.describe()
    assert described['status'] == 'interval' and described['timezone'] == 'Europe/Berlin'
    assert described['interval'] == {'start': '2026-10-28T23:00:00+00:00', 'end': '2026-10-29T23:00:00+00:00',
                                     'bounds': '[start, end)'}
    assert described['expressions'] == ['gestern'] and 'secret-project' not in json.dumps(described)


def test_module_uses_only_the_standard_library_and_no_provider():
    tree = ast.parse(Path(temporal.__file__).read_text())
    imported = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or '').split('.')[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert imported <= {'__future__', 'dataclasses', 'datetime', 're', 'zoneinfo'}
    relative = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level}
    assert relative <= {'retrieval'}
