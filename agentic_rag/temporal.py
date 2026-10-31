"""Deterministic EN/DE calendar interpretation for opt-in temporal search.

Bounded regular grammar, standard library only: no provider, model or network
call, and at most one clock read per interpretation. Unsupported, conflicting
or ambiguous forms are reported, never guessed. Intervals are half-open
``[start, end)`` in UTC, computed from local midnights of a named IANA zone.
The reference instant controls interpretation only; it never replaces the
valid-time selection (``as_of``/``history``) of the search itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as _tz
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MODES = ('auto', 'off', 'prefer', 'filter')
MAX_QUERY_CHARS = 1000
MAX_EXPRESSIONS = 8
_ZONE = re.compile(r'[A-Za-z][A-Za-z0-9_+-]{0,29}(?:/[A-Za-z0-9][A-Za-z0-9_+-]{0,29}){0,2}')

_MONTHS = {
    'januar': 1, 'january': 1, 'jänner': 1, 'februar': 2, 'february': 2, 'märz': 3, 'maerz': 3, 'march': 3,
    'april': 4, 'mai': 5, 'may': 5, 'juni': 6, 'june': 6, 'juli': 7, 'july': 7, 'august': 8,
    'september': 9, 'oktober': 10, 'october': 10, 'november': 11, 'dezember': 12, 'december': 12,
}
_MONTH = '(?:' + '|'.join(sorted(map(re.escape, _MONTHS), key=len, reverse=True)) + ')'
# A date is a standalone token: never part of a slug, version, path or decimal.
_L = r'(?<![\w.:/-])'
_R = r'(?![\w:/-]|\.\d)'
_ISO = r'\d{4}-\d{2}-\d{2}'
_DE = r'\d{1,2}\.\d{1,2}\.\d{4}'
_DE_NAME = r'\d{1,2}\.?\s+' + _MONTH + r'\s+\d{4}'
_EN_NAME = _MONTH + r'\s+\d{1,2},?\s+\d{4}'
_DATE = f'(?:{_ISO}|{_DE}|{_DE_NAME}|{_EN_NAME})'
_FLAGS = re.IGNORECASE

# (kind, pattern). Supported kinds yield an interval or current intent;
# 'unsupported' marks temporal-looking forms that are deliberately not guessed.
_PATTERNS = [
    ('range', re.compile(_L + rf'(?:(?:from|vom|von)\s+)?({_DATE})\s*(?:to|until|through|till|bis(?:\s+zum)?|–|—|\s-\s)\s*({_DATE})' + _R, _FLAGS)),
    ('range', re.compile(_L + rf'(?:between|zwischen)\s+({_DATE})\s+(?:and|und)\s+({_DATE})' + _R, _FLAGS)),
    ('unsupported', re.compile(_L + _ISO + r'(?:T|\s+)\d{1,2}:\d{2}', _FLAGS)),
    ('date', re.compile(_L + f'({_ISO}|{_DE}|{_DE_NAME}|{_EN_NAME})' + _R, _FLAGS)),
    ('unsupported', re.compile(_L + r'\d{1,4}/\d{1,2}(?:/\d{2,4})?(?![\w/])', _FLAGS)),
    ('unsupported', re.compile(_L + r'\d{1,2}\.\d{1,2}\.\d{2}(?!\d)' + _R, _FLAGS)),
    ('unsupported', re.compile(_L + r'\d{1,2}\.\d{1,2}\.(?![\d])', _FLAGS)),
    ('unsupported', re.compile(_L + r'\d{1,2}\.?\s+' + _MONTH + r'\b(?!\s+\d{4})', _FLAGS)),
    ('unsupported', re.compile(r'\b' + _MONTH + r'\s+\d{1,2}(?:st|nd|rd|th)?\b(?!,?\s+\d{4})', _FLAGS)),
    ('yesterday', re.compile(r'\b(?:yesterday|gestern)\b', _FLAGS)),
    ('last_week', re.compile(r'\b(?:last\s+week|letzte[nrs]?\s+woche)\b', _FLAGS)),
    ('next_month', re.compile(r'\b(?:next\s+month|n(?:ä|ae)chste[nrs]?\s+monats?)\b', _FLAGS)),
    ('current', re.compile(r'\b(?:currently|aktuell(?:e[nmrs]?)?)\b', _FLAGS)),
    ('unsupported', re.compile(
        r'\b(?:today|heute|tomorrow|übermorgen|uebermorgen|vorgestern|recently|lately|kürzlich|kuerzlich|neulich'
        r'|(?:this|next|coming)\s+week|(?:diese|nächste|naechste)[nrs]?\s+woche'
        r'|(?:last|this|previous|past)\s+(?:month|year)|(?:letzte|diese|vorige|vergangene)[nmrs]?\s+(?:monat|jahr)e?s?'
        r'|(?:next|coming)\s+year|(?:nächste|naechste)[nmrs]?\s+jahre?s?'
        r'|(?:last|past|previous|next)\s+\d+\s+(?:days?|weeks?|months?|years?)'
        r'|(?:letzte|vergangene|nächste|naechste)[nmrs]?\s+\d+\s+(?:tage?n?|wochen|monate?n?|jahre?n?)'
        r'|\d+\s+(?:days?|weeks?|months?|years?)\s+ago|vor\s+\d+\s+(?:tag(?:en)?|wochen?|monat(?:en)?|jahr(?:en)?))\b',
        _FLAGS)),
]
_PREPOSITIONS = {'on', 'at', 'in', 'from', 'to', 'since', 'during', 'for', 'of', 'between', 'and', 'or', 'the',
                 'am', 'im', 'vom', 'von', 'bis', 'seit', 'für', 'zwischen', 'und', 'oder', 'der', 'die', 'das', 'des'}


def _now() -> datetime:
    return datetime.now(_tz.utc)


def validate_mode(mode) -> None:
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError('invalid_temporal_mode: temporal must be auto, off, prefer or filter')


def parse_zone(name) -> ZoneInfo:
    if not isinstance(name, str) or not _ZONE.fullmatch(name) or name.casefold() in {'localtime', 'posixrules'}:
        raise ValueError('invalid_timezone: use a named IANA time zone such as Europe/Berlin')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError('invalid_timezone: use a named IANA time zone such as Europe/Berlin') from None


def parse_reference(value) -> datetime:
    if isinstance(value, str) and 0 < len(value) <= 64:
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            value = None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('invalid_reference: reference must be an ISO-8601 timestamp with an explicit offset')
    return value.astimezone(_tz.utc)


@dataclass(frozen=True)
class Interpretation:
    status: str                      # none | interval | current | ambiguous | unsupported
    start: datetime | None
    end: datetime | None
    timezone: str
    reference: datetime
    reference_source: str            # request | clock
    expressions: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    residual: str | None = None      # retrieval text without the interval expression, or None

    def contains(self, instant) -> bool:
        return (self.status == 'interval' and instant is not None
                and self.start <= instant < self.end)

    def describe(self) -> dict:
        return {
            'status': self.status,
            'interval': None if self.start is None else {
                'start': self.start.isoformat(), 'end': self.end.isoformat(), 'bounds': '[start, end)'},
            'timezone': self.timezone,
            'reference': self.reference.isoformat(),
            'reference_source': self.reference_source,
            'expressions': list(self.expressions),
            'kinds': list(self.kinds),
            'reasons': list(self.reasons),
            'confidence': 'syntactic' if self.status in ('interval', 'current') else 'none',
        }


def _midnight(day: date, zone: ZoneInfo) -> datetime:
    # fold=0: a nonexistent local midnight maps to the first instant of the day,
    # a repeated midnight to its first occurrence.
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(_tz.utc)


def _days(first: date, after: date, zone: ZoneInfo):
    return _midnight(first, zone), _midnight(after, zone)


def _month_start(year: int, month: int) -> date:
    year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    return date(year, month, 1)


def _date(text: str) -> date:
    """One full date in a supported unambiguous form; ValueError otherwise."""
    text = text.strip()
    if m := re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', text):
        return date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r'(\d{1,2})\.?\s+(\S+)\s+(\d{4})', text):
        return date(int(m[3]), _MONTHS[m[2].casefold()], int(m[1]))
    if m := re.fullmatch(r'(\S+)\s+(\d{1,2}),?\s+(\d{4})', text):
        return date(int(m[3]), _MONTHS[m[1].casefold()], int(m[2]))
    raise ValueError('unsupported date')


def _matches(query: str):
    """Longest non-overlapping matches, scanning left to right."""
    found = []
    for priority, (kind, pattern) in enumerate(_PATTERNS):
        for m in pattern.finditer(query):
            found.append((m.start(), -(m.end() - m.start()), priority, kind, m))
    selected, end = [], -1
    for start, negative, _, kind, m in sorted(found):
        if start >= end:
            selected.append((kind, m))
            end = start - negative
    return selected


def _residual(query: str, spans) -> str | None:
    from .retrieval import strong_symbols
    parts, last = [], 0
    for start, end in spans:
        parts.append(query[last:start])
        last = end
    parts.append(query[last:])
    text = ' '.join(' '.join(parts).split())
    words = re.findall(r'[\w]+(?:(?:::|[_.:-])[\w]+)*', text)
    if not any(len(w) > 1 and w.casefold() not in _PREPOSITIONS for w in words):
        return None
    if strong_symbols(text) != strong_symbols(query):
        return None
    return text


def interpret(query: str, *, reference=None, timezone: str = 'UTC') -> Interpretation:
    zone = parse_zone(timezone)
    if reference is None:
        instant, source = _now(), 'clock'
    else:
        instant, source = parse_reference(reference), 'request'
    base = dict(timezone=timezone, reference=instant, reference_source=source)
    if not isinstance(query, str):
        raise ValueError('query must be text')
    if len(query) > MAX_QUERY_CHARS:
        return Interpretation('unsupported', None, None, reasons=('query_too_long',), **base)
    selected = _matches(query)
    if not selected:
        return Interpretation('none', None, None, **base)
    expressions = tuple(m.group(0) for _, m in selected)
    kinds = tuple(kind for kind, _ in selected)
    base.update(expressions=expressions[:MAX_EXPRESSIONS], kinds=kinds[:MAX_EXPRESSIONS])
    if len(selected) > MAX_EXPRESSIONS:
        return Interpretation('ambiguous', None, None, reasons=('too_many_expressions',), **base)
    local = instant.astimezone(zone).date()
    intervals, reasons, spans = [], [], []
    for kind, m in selected:
        try:
            if kind == 'yesterday':
                interval = _days(local - timedelta(days=1), local, zone)
            elif kind == 'last_week':
                monday = local - timedelta(days=local.weekday())
                interval = _days(monday - timedelta(days=7), monday, zone)
            elif kind == 'next_month':
                interval = _days(_month_start(local.year, local.month + 1),
                                 _month_start(local.year, local.month + 2), zone)
            elif kind == 'date':
                day = _date(m.group(1))
                interval = _days(day, day + timedelta(days=1), zone)
            elif kind == 'range':
                first, last = _date(m.group(1)), _date(m.group(2))
                if last < first:
                    reasons.append('invalid_range')
                    continue
                interval = _days(first, last + timedelta(days=1), zone)
            else:
                if kind == 'unsupported':
                    reasons.append('unsupported_expression')
                continue
        except (ValueError, KeyError, OverflowError):
            reasons.append('invalid_date')
            continue
        intervals.append(interval)
        spans.append(m.span())
    current = 'current' in kinds
    distinct = sorted(set(intervals))
    if reasons:
        status = 'ambiguous' if distinct or current else 'unsupported'
    elif current and distinct:
        status, reasons = 'ambiguous', ['conflicting_expressions']
    elif current:
        status, reasons = 'current', ['no_recency_interval']
    elif len(distinct) > 1:
        status, reasons = 'ambiguous', ['multiple_periods']
    else:
        start, end = distinct[0]
        return Interpretation('interval', start, end, residual=_residual(query, spans), **base)
    return Interpretation(status, None, None, reasons=tuple(dict.fromkeys(reasons)), **base)
