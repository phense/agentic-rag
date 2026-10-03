# Feature Specification: Bounded research retrieval

## Stable work ID

RAG-5.6, feature6/10, [Issue31](https://github.com/phense/agentic-rag/issues/31). Accepted intent: maintainer's end-to-end request. Supported source19ed09c, package0.5.0, populated schema001–016.

## User scenarios

### US-001: Architecture and present constraints (P1)
Decompose a compound question and retain independent, exact source excerpts for each facet.

### US-002: Incident cause and resolution (P1)
Follow grounded graph links and choose relevant chunks, including evidence outside the first chunk.

### US-003: Missing or contradictory evidence (P1)
Separate support, disagreement and missing evidence; stop corrective retrieval within explicit limits and abstain.

## Acceptance criteria

- AC-001: Step, logical-call, wall-time and serialized evidence-context limits are validated, returned and enforced. Repeated failures terminate after two consecutive failed operations. Parent deadline terminates the isolated worker and its process group; cancellation propagates after cleanup.
- AC-002: Support contains exact source quotations and citations, backed per statement by at least two distinct active, complete, reviewed user-source identities by default. Every counted source must contain that exact quoted statement; confirmed stated claims are required. Duplicate chunks or derived documents do not create independent sources. Explicit graph disagreements and provider-assessed contradictions remain separate. Missing evidence causes abstention.
- AC-003: Local research collects evidence without outbound provider calls. Explicit provider mode uses only configured llm.run_structured, redacts its inputs and validates outputs against retained sources. Local mode always abstains from a semantic answer, while exposing source-backed statements. Provider mode may establish facet coverage but cannot invent free-form claims.
- AC-004: Each search, graph endpoint and evidence hydration preserves domain/project/time/active/source boundaries. Research opens rag_reader even in an authorized main session. No persisted research state or application writes.
- AC-005: Normal search, hooks, jobs, settings and old MCP tools remain unchanged; memory_research and rag research are additive. Schema stays016; actual source/candidate clients work on a populated representative store and code rollback loses no rows.
- AC-006: Three matched-input scenarios report attributable raw counts, quality denominators and cold/warm latency; Trading controls remain read-only and provider-free. No synthetic quality gain is represented as measured production answer accuracy.
- AC-007: Full Python/Node tests pass, including malformed input, boundaries, concurrent clients, errors, cancellation and retry. Independent complete-diff reviews resolve all Critical/High/Medium findings; Low findings fixed or linked.

## Functional requirements

FR-001: Decompose at most four facets; initial and corrective rounds share one bounded evidence packet. FR-002: At most three graph seeds/eight adjacent documents per seed and64 candidate chunks per graph document; select by question relevance rather than chunk index. FR-003: No automatic web search, provider switching, knowledge conversion, new dependencies or live service interruption.

## Compatibility boundaries

One shared PostgreSQL/pgvector store, schema001–016. No migration, re-embedding or installation modification. Parent-owned subprocess resources are ephemeral. Caller sessions retain loaded old code until voluntary reconnect. Merge permission is separate from rollout authorization.

## Interface contracts

| ID | Boundary | Inputs | Outputs | Invariants |
| --- | --- | --- | --- | --- |
| IC-001 | CLI/MCP | question, filters, budgets, explicit provider choice | supported/disagreement/missing, evidence/context, usage, termination, abstained | read-only; validated budgets |
| IC-002 | provider | redacted question and bounded retained context | facets, exact quoted claims, disagreements, corrective queries | only configured seam; no arbitrary retrieval/filter instructions |
| IC-003 | worker | private stdin configuration/request | bounded JSON progress/final packets | private empty cwd; reader; deadline/cancel kills process group |

## Edge cases

Empty/oversized question; bool/nonfinite/zero/oversized limits; same source across documents; legacy/unreviewed/refuted/assistant evidence; graph cycles and long documents; foreign/archived/expired endpoints; fabricated model quotes/IDs; repeated provider/SQL errors; empty evidence; exhausted context; lock/network stalls; simultaneous clients; interruption/retry.

## Assumptions and unresolved decisions

Source identity distinguishes provenance, not human independence by itself. Semantic coverage/contradiction detection remains a model assessment, never an oracle. Local mode reports this limit explicitly. Wall-time cleanup has small OS scheduling overhead. No unresolved scope decision.

## Success measures

SC-001: no observed resource limit breach or write. SC-002: all citations reproduce original chunk substrings. SC-003: three honest matched comparisons, full suites and clean independent review.

## Playbook obligations

PB-5.6, operator, AC-001/003/005: opt-in provider privacy, timeout/cancel/retry and code-only deployment/rollback. Document and review procedure; rehearse success/recovery on an isolated populated store before readiness.
