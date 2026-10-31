# Tasks: Explainable EN/DE temporal search

## Stable work ID

Feature6.6 / RAG-064 / Issue64; [spec](spec.md), [plan](plan.md). Artifact docs/specs/6-6-temporal-query/tasks.md. Accepted under existing implementation authority.

## Architecture findings

AF-064-001→T064-001/002; AF-064-002→T064-002/003; AF-064-003→T064-002..005. One implementation owner handles the shared parser/retrieval/client interface serially. Coordinator owns reconciliation, review and publication. Canonical model/findings under docs/uml/.

## Tests

Observe meaningful red then green for new behavior, mock provider boundaries only. Record exact commands, source boundary, exit and logs. PG55460/agentic_rag_test only, no concurrent pytest because project fixtures reset shared test schema. Public fixtures synthetic. Full suite belongs to final S3 gate.

## Implementation slices

### Slice S1: Reproducible temporal search across existing clients

- [x] T064-001 [AC-001/002/006/008] [AF-064-001] Freeze deterministic parser and source-ranking development/held-out cases and labels before product implementation; hash them. Add meaningful failing tests for calendar/DST/year/mixed-language/ambiguous dates, reference/zone validation, bounds and current intent; implement focused temporal.py with no provider calls. Files temporal.py, new temporal tests, docs/benchmarks/2026-10-31-temporal-query/ fixtures. Base8772fbd; no dependency.
- [x] T064-002 [AC-003..006] [AF-064-001..003] Test-first integrate opt-in interpretation, canonical eligible event metadata, stable preference and fail-closed filtering around search rerank/diverse and graph stages. Preserve exact selectors/symbols, original snippets/scores, unknown timestamps and existing eligibility; no document ingestion-time fallback. Test late imports, future plans/assertions, expiry/supersession/refutation/withdrawal, private scope, unavailable metadata and finite caps. Files temporal.py/search.py/config.py and real DB tests. Depends T064-001.
- [x] T064-003 [AC-004/006/007] [IC-001..003] [AF-064-002/003] Test-first wire additive temporal/reference/zone options through local CLI/MCP and existing central REST/remote CLI/MCP. Old invocations/configs/envelopes and RO/RW distinction remain compatible. Default auto honors config disabled; explicit prefer/filter opt in. New default flags are not sent to old servers when caller did not request temporal behavior. Files mcp_server.py/cli.py/config.py/existing remote seam and tests. Depends T064-002.
- [x] T064-004 [AC-007] [AF-064-003] Run populated schema029 compatibility with actual archived0.6.16 old-client/code rollback, preserving original-row hashes and timestamps/users/domains/scopes/audits. No schema migration or production action. Retain executable fixture/evidence and exact commands. Depends T064-003.
- [x] T064-005 [AC-008] [AF-064-003] Measure same frozen corpus feature-off/on held-out source quality and parser quality with explicit denominators/failures/unknowns, repeated latency and no-temporal controls; publish2–3 measured examples, reproducible harness/results and honest provider/candidate limits. Author temporal user/config/upgrade docs using required writing skills (medium), update related docs, exact0.6.17 patch files. Report named report path with test red/green evidence and current commits/files. Depends T064-004.

## Dependencies

S1 tasks serial1→2→3→4→5; no parallel-safe writers because query/config/signature contracts and shared DB fixtures overlap. Implementer owns product/tests/temporal user/benchmark docs and pyproject/lock/README/CHANGELOG. Coordinator owns spec/plan/tasks/UML/findings, durable state, GitHub and final evidence. No agent reverts others' edits or starts agents without explicit brief authority.

## Final integration

### Slice S2: Reconcile authority and obtain independent gates

- [x] T064-006 Reconcile as-built model/findings from actual code; independently derive and execute real collaborating-component success and fail-closed/recovery probes. Verify no persistent writes and feature-off recovery on populated029. Owner coordinator plus separate strong independent architect; depends T064-005.
- [x] T064-007 Complete independent bounded base8772fbd→final diff review, including canonical time/source authorization, parser ambiguity, graph, transport compatibility and benchmark evidence. Verify/fix every C/H/M and re-review changed ranges; put nonblocking Low in Issue75. Owner coordinator plus independent reviewer; depends T064-006.

### Slice S3: Convergence and PR handoff

- [ ] T064-008 Invoke speckit-converge, resolve all actionable gaps through the same executor, obtain fresh full-suite actual exit, package/version/docs/source consistency. Publish one PR with numerical examples and limits, immediately link it, sync Issue64, report step6of15 and wait NEWweiter for this specific PR. No merge/deploy in this slice. Owner coordinator; depends T064-007.

## Playbook obligations

System/development none per spec/plan: no persistent changes, coordinated live operation or nontrivial recovery; ordinary reversible opt-in configuration/code handling is documented and automatically exercised. Reassess on scope changes. Missing independent review, full-suite exit or populated compatibility blocks publication.

S1 implementation returned at e6cd548; coordinator integration additionally
covers public0.6.16 upgrade-source acceptance, the graph k boundary and fresh
source-withdrawal rejection. Targeted test evidence is being collected before
independent S2 gates. The transport tests observed red retrospectively against
the stashed transport change, rather than before its first implementation;
this process deviation is recorded, not represented as original test-first.

S2 independent review at517263c covers32/32files with0C/H/M. Independent
architecture success29/29 and recovery12/12 pass; originals and failed probe
are preserved in docs/verification/issue64/. Low031..035 are explicitly deferred
toIssue75; documentation/evidence Low036 is corrected in delivery. S3 remains
open until an actual whole-suite exit and remaining evidence checks pass.
