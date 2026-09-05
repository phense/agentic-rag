# Implementation Plan: Evidence-backed fact validity

## Stable work ID

- Feature ID: `RAG-006`
- Specification: `specs/RAG-006-fact-validity/spec.md`
- Artifact path: `specs/RAG-006-fact-validity/plan.md`

## Summary

Add immutable atomic assertion documents via `store.save_assertion`, with a
`fact_assertions` evidence/validity table. Ordinary documents remain untouched.
An advisory transaction lock serializes the canonical scope/entity/attribute key.
Inspect at most 51 existing assertions; overflow is review-only. Exact event/value
replay deduplicates; explicit replacement relates newer to older by event time,
including late import. Extensions coexist; unresolved conflicts remain reviewable.
No vector-similarity decision can close a temporal assertion.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| One shared PostgreSQL store | AGENTS.md, db.py | preserved |
| Audited secret-stripping gateway | store.py | extend gateway, retain outer batch transaction |
| Reader/writer roles | sql/002_roles.sql | explicit grants on new table; reader cannot mutate |
| Additive adapters and pins | hooks, mcp_server.py | no configuration rewrite or pin mutation |
| Evidence prerequisite | mining_window.py currently loses event metadata | retain only consumed sanitized event slices with role/time/identity |

## Technical context

Python >=3.13, psycopg, PostgreSQL/pgvector. Existing migration010 applies scope
before all retrieval limits. Existing mining accepts normalized output durably
before applying it; that transaction boundary also owns assertion effects.
`curation.py` currently reviews whole-document contradictions and must exclude
atomic assertions. Legacy reactivation establishes a fresh review epoch.

## Compatibility boundaries

Migration011 is additive, with no inferred temporal backfill. Current search is
the default; as-of selects known valid-time assertions; history explicitly includes
all temporal dispositions. Get/timeline remain deliberate browsing. Graph browsing
keeps its existing unselected history behavior unless temporal selection is explicit;
automatic/scoped graph expansion uses current eligibility. Restart MCP processes.
Deploy under worker lock after fresh verified backup; verify legacy rows/pins unchanged.
Old workers are unsafe after activation; rollback by forward repair or backup restore.

## Interface contracts

| Contract ID | Producer | Consumer | Change | Failure |
|---|---|---|---|---|
| IC-001 | store.save_assertion | CLI/MCP/mining | structured evidence and temporal assertion | reject invalid types, retain uncertain items as review |
| IC-002 | SQL assertion_eligible | search/hooks/graph | current/as-of/history before limits | timezone validation before DB/provider work |
| IC-003 | mining_window | mining acceptance | consumed record fragments with stable reference, role and timestamp | cannot ground against text outside consumed slice |
| IC-004 | fact_assertions | review/get | evidence and disposition | no silent promotion |

## Dependencies

Scope #5 is deployed. #7's minimal role/event/quote subset is implemented here for
atomic assertions only. Existing benchmark runner supplies controlled retrieval;
add temporal selectors and immutable fixture result artifacts. No extra LLM call.

## Tests

- Targeted `tests/test_validity.py`: current/as-of/history, expiry, late arrival,
  extension, foreign scope, equal time conflict, duplicate, evidence and immutable edits.
- Mining evidence tests: partial source windows, fabricated quote/role/time,
  accepted-batch replay and failure after first effect.
- Integration: real writer -> assertion gateway -> reader search -> hooks/graph.
- Migration: 010-to-011, unchanged legacy content, role grants, replay and rollback.
- Baseline: same temporal fixture/search budget with previous eligibility and new
  selection; record stale-result rate and current/historical recall, not model quality.

## Architecture findings

See `docs/uml/findings.md`: AF-006 through AF-009 map to tasks below.

## Implementation structure

Coordinator owns serialized changes in `store.py`, new `validity.py`, migration011,
`mining_window.py`, `mining.py`, retrieval wrappers/hooks, CLI/MCP, curation and benchmark.
Independent reviewer checks the complete change and derives integration tests after
as-built reconciliation. No concurrent database test runs.
