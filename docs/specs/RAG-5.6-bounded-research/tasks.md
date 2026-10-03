# Tasks: Bounded research retrieval

## Stable work ID

RAG-5.6; [spec](spec.md), [plan](plan.md), [architecture](../../uml/bounded-research.md). Sequential coordinator writes, independent read-only reviews.

## Architecture findings

AF-5.6-01 parent deadline; AF-5.6-02 source identities; AF-5.6-03 graph relevance/boundaries.

## Tests

Meaningful regression mutations: promote duplicate/unreviewed sources, invent citations, drop endpoint filters, pick only first graph chunk, exceed resource limits, send provider data by default, lose caller cancellation or leak descendants.

## Implementation slices

### Slice S1: Bounded evidence engine

- [x] T001 [US-001/003,AF-5.6-02] Observe red consumer evidence/budget tests — tests/test_research.py.
- [x] T002 [AC-001–004,AF-5.6-02/03] Implement decomposition, relevant graph chunks, source-grounded statements, contradictions, corrective rounds and context/call/failure caps — research.py; depends T001.
- [x] T003 [AC-001/003,AF-5.6-01] Add isolated worker and deadline/cancel/group cleanup with real process tests — research_worker.py, test_research.py; depends T002.
- [x] T004 [AC-004/005] Add CLI/MCP read tools and verify privacy/privilege/old contracts — cli.py, mcp_server.py, tests; depends T003.

### Slice S2: Compatibility and practical evidence

- [x] T005 [AC-005/006] Rehearse populated source/candidate/rollback/full-row/privilege/config checks and three paired scenarios; Trading read-only/provider-free — scripts/verify_bounded_research.py, docs/benchmarks; depends T004.
- [x] T006 [PB-5.6] Author/review procedure and rehearse timeout/cancel/retry — docs/bounded-research.md; depends T005.

### Slice S3: Integration and convergence

- [x] T007 Reconcile as-built success/recovery model; full Python/Node tests and independent complete diff reviews; fix/re-review all findings; depends T005/T006.
- [ ] T008 Update Feature5 adopted status, Feature6 evidence and linked PR; Issue31 stays open pending merge/rollout, ask specific merge approval; depends T007.

## Dependencies

T001→T002→T003→T004→T005→T006→T007→T008. No parallel-write tasks.

## Final integration

AC-001–007 and PB-5.6 require fresh command/output evidence and complete-range review.
Recorded completion: [verification](../../verification/bounded-research.md),
1039 Python/7 Node passed; implementation and content reviews Ready, measured
source hashes match. T008 is the external PR/approval handoff; live rollout
remains a separate authorized operation and Issue31 remains open until met.

## Playbook obligations

PB-5.6 authoring, content review and populated isolated success/recovery rehearsal are T006 readiness gates.
