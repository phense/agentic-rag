# Feature Specification: Entity-aware bounded research

## Stable work ID

- Feature ID: RAG-069; stable backlog ID: 6.11.
- Source request: [Issue69](https://github.com/phense/agentic-rag/issues/69).
- Status: Implemented and verified; PR97 awaits specific merge approval.

## User scenarios

### US-001: Follow related evidence (Priority: P1)

A reader asks about a named entity and its dependencies. Research follows existing
confirmed aliases and eligible relations across several bounded hops, retaining
original passages and the path that introduced them. An independent test starts
with one retrievable document and reaches a relevant document two edges away.

### US-002: Inspect uncertainty and limits (Priority: P1)

A reader distinguishes exact source support, provider assessment, missing facets,
ambiguous identities and exhausted budgets without treating missing evidence as
an answer. Independent tests use conflicting aliases, duplicate sources and a cycle.

### US-003: Adopt without changing the store (Priority: P2)

Existing local and central clients can use the enhanced read operation, cancel it,
or revert the executable without changing originals, permissions, jobs or schema.

## Acceptance criteria

- AC-001: A question produces at most four facets and a bounded exploration plan;
  each facet reports retained evidence IDs, literal support and semantic coverage
  separately. Search, alias and graph decisions and termination are inspectable.
- AC-002: A confirmed direct alias can locate eligible original facts; ambiguous,
  unavailable or over-limit identity results never cause speculative expansion.
  Alias links and graph edges retain original provenance when used.
- AC-003: Each hop and every exposed ID/count obeys the caller's domain, project,
  RLS, source, temporal and lifecycle selection. A hidden bridge never reveals a
  downstream document. Cycles, self-edges and repeated sources do not inflate support.
- AC-004: Step, logical-call, wall-time, provider and serialized-context limits remain
  hard. Additional exploration has fixed row/frontier/hop limits and SQL timeouts
  no longer than the remaining request budget or a shorter caller limit. Cancellation
  reaps owned descendants and returns no invented success.
- AC-005: Existing exact-quotation checks, source quorum, disagreement and local
  semantic abstention remain mandatory. Optional assessment is explicit; ordinary
  search, hooks, writes and embedding routing are unchanged.
- AC-006: Held-out synthetic single-hop, multi-hop, alias, ambiguous and contradictory
  cases compare old/new coverage, unsupported statements, independent source counts,
  calls, elapsed p50/p95 and resource cost, with three inspected original citations.
  No claim of general model accuracy or production latency follows from this corpus.
- AC-007: Real reader/CLI/MCP and central authority tests, deadline/cancellation tests,
  and a populated source0.6.23 adoption/rollback plus independently restored backup
  pass. Every returned span equals its original chunk; no persistent row changes.

## Functional requirements

- FR-001: Extend the existing research engine; do not create a second search system.
- FR-002: Explore only bounded, eligible candidates that can add retained evidence;
  preserve visible overflow and distinguish exhausted frontier from full coverage.
- FR-003: Provider/graph/identity failure falls back deterministically to available
  literal evidence with explicit uncertainty. No inferred alias, fabricated citation,
  hidden intermediate identifier or source-count inflation is acceptable.

## Compatibility boundaries

Source0.6.23/schema035 and current CLI/MCP arguments are preserved. Result additions
are optional fields for old consumers. No migration, new dependency, service, cache,
configuration or database writes. Code rollback restores the prior reader. This work
neither closes Issue68/92 nor changes their performance criteria.

## Interface contracts

| Contract ID | Boundary | Inputs | Outputs | Invariants |
|---|---|---|---|---|
| IC-001 | Existing research operation | Existing filters and ResearchBudget | Existing packet plus plan, coverage, decisions, exploration diagnostics | No removed fields or new required arguments |
| IC-002 | Entity/graph readers | Frozen request authority and time | Eligible original chunks and bounded provenance | Invoker RLS and source gates before publication |
| IC-003 | Parent/worker | Existing isolated read-only payload | Progress or explicit partial result | Hard wall-time and descendant cleanup preserved |

## Edge cases

No hits, unavailable index, non-matching entity names, unknown applicability,
foreign scopes, withdrawn sources, expired/future facts, ambiguous alias stars,
contradictory edges, cycles, high degree, tiny context/call budgets and cancellation
must produce bounded, honest partial evidence or abstention.

## Assumptions and unresolved decisions

Only exact names mentioned in the question or retained eligible assertions seed
entity resolution; research does not invent entities. Existing source-backed alias
semantics and source identifiers remain the authority, not a new equivalence model.
No materially unresolved decision remains.

## Success measures

- SC-001: Zero ineligible/fabricated spans and zero unauthorized IDs in the test matrix.
- SC-002: At least one held-out two-hop and one alias case gain relevant original
  evidence over0.6.23, without increasing unsupported answers.
- SC-003: All budget, read-only and compatibility checks pass; full suite and
  independent complete-diff review have no open C/H/M findings before PR approval.

## Playbook obligations

PB-5.6 (`docs/bounded-research.md`), system procedure for CLI/MCP readers, must explain
new diagnostics, bounded exploration, uncertainty and code-only upgrade/rollback.
Acceptance: executable local/central examples and failure/cancellation branches match
actual behavior; no new deployment operation or separate runbook is necessary.
