# Tasks: RAG-069 entity-aware bounded research

## Ownership and integration

Coordinator owns all changed paths; serial implementation, no parallel writers.
Base c33e11f. Complete bounded independent review remains mandatory before PR.

### Slice S069-1: Original-backed bounded exploration

- [x] T069-001: Freeze behavior tests in tests/test_research_exploration.py before
  runtime edits; observe meaningful red for multi-hop, alias and diagnostics/caps.
  AC001–005, IC001–003, AF069-001–003. Depends: design complete.
- [x] T069-002: Implement research.py/graph.py and a request-local exploration helper,
  preserving source quorum and hard parent deadlines. Depends: T069-001.
- [x] T069-003: Verify existing research tests plus entity/graph/lifecycle tests;
  malformed, unavailable, timeout, high-degree and cycle behavior. Depends: T069-002.

### Slice S069-2: Integration, evidence and delivery

- [x] T069-004: Real RLS local/central/CLI/MCP success and recovery; populated0.6.23
  backup/restore/adoption/old-reader rollback with unchanged row hashes. AC003/007.
  Depends: T069-003. Architect derives success/recovery checks after as-built.
- [x] T069-005: Frozen held-out baseline/candidate measurement and three inspected
  examples; coverage, supported/unsupported, quorum, calls, p50/p95 and resources.
  AC006, SC001/002. Depends: T069-003.
- [x] T069-006: Update PB-5.6 with playbook-authoring/review; synchronize0.6.24 release
  metadata and supported source label; reconcile architecture. Depends: T069-004/005.
- [x] T069-007: Independent complete bounded review including PB-5.6 and derived
  integration tests; fix confirmed findings, final full suite and package/lock checks.
  SC003. Depends: T069-006.
- [x] T069-008: Converge AC/IC/AF evidence, publish PR linked to69 with measured
  before/after, request specific merge approval. No production change inferred.
  Depends: T069-007.

## Current evidence

154 focused tests passed (exit0); held-out15-run-per-engine comparison and
populated0.6.23 adoption/source-and-target independent restores passed.
Independent architect-derived alias/three-hop/RLS/source-withdrawal/budget-retry
probes pass; pure-read table hashes are unchanged. PB review has0 Important;
both Minor findings are corrected. The sole Medium provenance finding is
resolved by a fresh source-bound measurement on1036e10. Five nonblocking Low
findings are tracked in Issue75 (LOW111..115). Final full suite:2623passed,
1skipped,1knownwarning,exit0,3061.68s; all392 inputs unchanged.7Node tests,
lock,source/wheel build and35SQL/3module wheel parity passed. AC/IC/AF evidence
is reconciled. PR97 is published and ready for the required specific merge
approval; neither merge nor production adoption is claimed.
