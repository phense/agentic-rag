# Feature Specification: Explainable EN/DE temporal search

## Stable work ID

- Feature ID: `6.6`; work ID: `RAG-064`; [Issue64](https://github.com/phense/agentic-rag/issues/64), roadmap step6/15.
- Artifact: `docs/specs/6-6-temporal-query/spec.md`.
- Status: Accepted under the maintainer's end-to-end implementation request, 2026-10-31.
- Outcome: time expressions improve expected-source ordering while explicit validity and current authority remain authoritative.

## User scenarios

### US-001: Find events in a named period (Priority: P1)

A German or English query containing yesterday/gestern, last week/letzte Woche, next month/nächsten Monat or explicit dates/ranges exposes its interpreted interval and prefers matching source events. An explicit reference instant makes the same query reproducible. Independent test: matching original events precede equally relevant events outside the requested interval, even when imports happened later.

### US-002: Inspect and constrain time interpretation (Priority: P1)

Callers can distinguish a soft preference, explicitly requested hard filtering and existing as_of/history. They see interval, zone, reference, confidence or ambiguity, event-time basis and actual ranking effect. Unknown or ambiguous dates never become invented timestamps. Independent test: hard filtering returns only known matching events; ambiguous hard requests fail closed.

### US-003: Retain safe existing behavior (Priority: P1)

Operators can disable interpretation, and old clients continue searching populated installations. Queries without temporal intent follow the existing path. Temporal matching cannot restore withdrawn, refuted, unauthorized, expired or superseded evidence beyond existing explicit history semantics. Independent test: off/no-intent results match baseline; current-fact and scope gates still reject excluded fixtures.

## Acceptance criteria

- AC-001 — Define deterministic EN/DE calendar semantics: yesterday is the previous local calendar day; last week is the previous Monday-to-Monday calendar week; next month is the next complete local calendar month. Intervals are half-open, converted from a named IANA zone to UTC; default zone UTC. Explicit ISO dates, unambiguous German full dates and inclusive date ranges are supported. Slash dates, missing years, conflicting expressions and unsupported forms are reported conservatively, never guessed.
- AC-002 — An optional aware reference timestamp controls interpretation only, independently of as_of/history. DST, week/year/month/leap boundaries and mixed-language queries are tested. Currently/aktuell retains existing current-validity semantics and reports that it supplies no invented recency interval; hard filtering requires a concrete interval.
- AC-003 — Use immutable assertion event time first, otherwise active qualifying original source times. Never use document creation/update/import time as a substitute. Missing event times remain unknown; a known source date is not proof that the claim is independently verified.
- AC-004 — Responses explain interpretation, confidence/ambiguity, actual ranking/filter effect and known/unknown per-hit basis without exposing private source locators. Soft preference preserves unmatched/unknown candidates behind matching candidates. Hard filter excludes unknown/out-of-interval candidates and fails closed on absent, ambiguous or unsupported intervals.
- AC-005 — Eligibility, source trust, scope/domain/RLS, current-fact replacement, expiry and explicit as_of/history stay authoritative, including after graph expansion. A future interval alone does not make an otherwise ineligible future assertion current. Explicitly stored future-plan source events can match when existing eligibility permits them.
- AC-006 — Feature off and no temporal intent preserve baseline ordering, fields and provider behavior. Parsing adds no model calls, is bounded, and has a deterministic unsupported-input path. Soft mode degrades safely on unavailable temporal metadata; hard mode never silently degrades to an unfiltered result.
- AC-007 — Local CLI/MCP and central REST/remote CLI/MCP expose the same additive options/meaning while legacy required arguments and old response fields remain available. Old configurations continue loading. Source0.6.16/schema029 upgrades need no data rewrite, re-embedding or migration; tested populated compatibility and code/config rollback are delivered.
- AC-008 — Publish same-corpus feature-off/on measurements with frozen development/held-out separation, explicit quality denominators, failures/unknowns, latency overhead and no-temporal controls. Include 2–3 measured before/after examples and exact commands/revisions. Provider mocks are disclosed; no fabricated native model gains.

## Functional requirements

- FR-001: Recognize supported time intent and expose bounded, reproducible interpretation.
- FR-002: Apply explainable preference or explicit filtering only within existing retrieval authority.
- FR-003: Preserve all stored knowledge and compatible old-client use; deliver measured limits.

## Compatibility boundaries

Source0.6.16/schema029, target0.6.17/schema029. Default interpretation is off through configuration; additive request modes can explicitly opt in. Existing as_of/history meanings do not change. Existing bounded candidate retrieval remains bounded; hard filtering guarantees the time predicate on returned hits, not exhaustive recall across the whole database. Any candidate/graph limit is reported explicitly. No automatic forgetting, date fabrication, new extraction, migrations or production changes. Keep Issue6 and Issue48 separate and open according to their own acceptance.

## Interface contracts

| ID | Boundary | Inputs | Outputs | Invariant |
|---|---|---|---|---|
| IC-001 | Search | Existing arguments plus temporal mode, reference and timezone | Existing hits/warnings plus additive interpretation when applicable | Off/no-intent retains baseline envelope |
| IC-002 | Calendar interpretation | Query, aware reference, IANA zone | Half-open UTC interval or explicit non-interval/ambiguity | No provider, no clock read per expression |
| IC-003 | Temporal ranking | Already eligible candidates and canonical source metadata | Stable matching-first order or strict matching subset; explanations | Cannot expand authority or fabricate event time |

## Edge cases

Date-only queries, more than one period, leap days, nonexistent/ambiguous local wall times, long input, malformed zones/reference, empty candidates, many sources, graph-only candidates, future plans, late imports, unknown dates, exact IDs/symbols, concurrent trust changes and unavailable temporal metadata all need explicit bounded behavior. Preserve the original query where interpretation is unsafe; never erase symbols or silently broaden exact selection.

## Assumptions and unresolved decisions

No material product ambiguity remains. Initial support is deterministic, not unrestricted natural-language date understanding. Confidence denotes syntactic recognition, not factual truth. Calendar interpretation does not reconstruct a historical snapshot. The Mem0 temporal-reasoning page is a product reference only; existing engine semantics govern this implementation.

## Success measures

- SC-001: All supported calendar, authority and no-resurrection acceptance fixtures pass.
- SC-002: Frozen held-out top1/MRR/recall@k denominators and off/on controls are published, including non-improvements and latency distributions.
- SC-003: Populated old-client reads, unchanged original-row hashes, feature-off rollback and fresh complete-suite exit pass before PR handoff.

## Playbook obligations

None: the feature performs no migration or durable write. Opt-in configuration and code rollback are ordinary reversible actions, documented and automatically exercised. Reassess if implementation introduces persistent changes or deployment coordination.
