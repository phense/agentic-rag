# Implementation Plan: Entity-aware bounded research

## Stable work ID

- Feature ID: RAG-069 / Issue69 / backlog6.11.
- Specification: [spec.md](spec.md).

## Summary

Keep `research_async` and the isolated read-only worker. Replace repeated one-hop
seed scans with a request-local visited frontier, and use `entities.read` for existing
source-backed alias/fact resolution. Rehydrate every candidate through the existing
research citation/source proof before exposing IDs or supporting claims. No store cache.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Existing engine | research.py, research_worker.py, entities.py, graph.py | Reuse; no second engine |
| Authority and original evidence | SQL021/031/033/035, add_hits | Must hold at every hop and diagnostic |
| Production compatibility | Source0.6.23, schema035 | Code only; isolated populated restore/revert required |
| Audited writes | No reader mutations | Preserved |
| Independent review and version | AGENTS.md | Complete bounded review; target0.6.24 before PR |

## Technical context

Python3.12+, psycopg3/PostgreSQL17, existing pgvector. `research.py` currently revisits
first three document seeds each round; entities.read provides direct confirmed alias
stars with bounded facts and ambiguity status. Existing graph wrapper lacks a domain
argument: add a research-specific bounded one-hop invoker reader in `graph.py`, based
on the current research edge query, rather than using unfiltered recursive traversal.

## Compatibility boundaries

Preserve existing defaults, signatures, quorum checks, lifecycle/time propagation,
provider opt-in and cancellation process group. Add result fields only. No SQL changes.
Retain baseline source and schema035 for old-reader/code-rollback integration. Package
0.6.24 from0.6.23 with synchronized version metadata and supported-version tests.

## Interface contracts

| Contract ID | Producer | Consumer | Change | Failure behavior |
|---|---|---|---|---|
| IC-001 | research.py | Existing CLI/MCP/service | Add plan/coverage/decisions/exploration | Local abstention and visible partial termination |
| IC-002 | graph.py and entities.read | Research frontier | Fixed bounded candidates, original provenance | Safe optional failure; no raw exception content |
| IC-003 | research_worker.py | Parent deadline owner | Preserve isolation and progress | Parent kills owned process group |

## Dependencies

Existing alias index schema018 (present in035), temporal/source/lifecycle predicates,
read-only transaction and request_scope. No external service or SDK is introduced.

## Tests

- Targeted: tests/test_research.py, new tests/test_research_exploration.py; alias,
  multi-hop, cycle, foreign bridge, source withdrawal, temporal/lifecycle and caps.
- Contract: CLI, both MCP privilege levels and central memory_research with real RLS.
- Integration: isolated subprocess success and cancellation, optional component failure,
  and statement-timeout/settings restoration; architect derives success/recovery cases.
- Upgrade: populated0.6.23 shared store, source backup independently restored, candidate
  reads and old-reader rollback, unchanged canonical row hashes and schema markers.
- Measurement: frozen held-out synthetic cases, archived literal baseline engine,
  exact citation oracle and measured resources/latency without provider or production data.

## Architecture findings

AF069-001: diagnostics must not expose raw identity catalog names or graph IDs before
original eligibility proof. AF069-002: bound underlying SQL and frontier separately from
logical calls. AF069-003: local literal support never implies semantic coverage. See
`docs/uml/research-exploration-69.md` and the canonical findings registry.

## Supporting artifacts

Only the spec/plan/tasks, one trust-boundary sequence diagram and measured verification
record are justified. No new data model, provider protocol or migration artifact.

## Implementation structure

Coordinator owns research.py, graph.py, focused tests, release metadata and PB-5.6.
One cohesive exploration slice precedes transport/upgrade/measurement verification.
No concurrent writers; independent complete-diff review after implementation.

Exploration limits: four entity resolutions, three new graph seeds per round, eight
eligible neighbors per seed (plus one overflow sentinel), at most three graph hops,
at most24 discovered documents, at most64 ranked chunks per candidate and24 new
candidate hydrations. Every logical resolution/seed consumes the existing call budget;
per-request counters report SQL work and fixed caps. SQL statements have a bounded
remaining-time timeout; the parent remains the hard deadline for all provider/SQL work.

## Playbook obligations

PB-5.6 system procedure, coordinator-owned `docs/bounded-research.md`, origin AC001–007.
Update before delivery; independent review and real reader/cancellation/rollback
rehearsal required. Existing installation/backup commands suffice for the isolated
code-only adoption check. No new critical development operation or production change.
