# Tasks: Filter-aware vector retrieval

RAG-5.5; [spec](spec.md), [plan](plan.md), [findings](../../uml/findings.md). Sequential coordinator ownership; no overlapping parallel writes.

### Slice S1: Exact eligible sets and bounded ANN

- [x] T001 [AC-001–004/AF-5.5-02] Observe a real failing vector-only crowded-document test through audited saves and search; add independent small-project/domain/time/source/context oracle boundaries — tests/test_filter_aware_search.py.
- [x] T002 [AC-001–004/AF-5.5-02] Add migration016 read-only vector helper and planned raw/contextual fusion, retain all old functions — sql/016_filter_aware_search.sql; depends T001.
- [x] T003 [AC-003/005/AF-5.5-01] Implement capability discovery and bounded savepoint-local settings/restoration, wire only auto/context-auto semantic paths — agentic_rag/vector_plan.py, search.py; depends T002.
- [x] T004 [AC-005/006] Verify real caller/autocommit/reader/concurrent-client state, timeout/cancel recovery and missing016 fallback — tests/test_filter_aware_search.py; depends T003.

### Slice S2: Measurements and upgrade acceptance

- [x] T005 [AC-006] Author/review PB-5.5 and rehearse populated015→016 interruption/retry/repeat/old-new readers/code rollback/full fingerprint/strict restore — docs/filter-aware-search.md, scripts/verify_filter_aware_search.py; depends T004.
- [x] T006 [AC-007] Measure3 practical scoped/rare-time/crowded cases against exact eligible-set oracle, raw paired latency and recall; include authorized read-only Trading controls with protected content — docs/benchmarks/2026-10-03-filter-aware-search; depends T005.

### Slice S3: Integration and convergence

- [x] T007 Reconcile as-built transaction sequence and derive/exercise cross-component success and cancellation/rollback integration flows; depends T004/T005.
- [x] T008 [AC-008] Full Python/Node checks and independent complete-bounded-diff review; fix and re-review all Critical/High/Medium findings; depends T006/T007.
- [ ] T009 Converge evidence, sync completed Feature4 index state and current Feature5 readiness, publish linked PR with source/limits/upgrade evidence; keep Issue30 open pending specific merge and rollout gates; depends T008.

## Dependencies and verification

T001→T002→T003→T004→T005→T006; T004/T005→T007; T006/T007→T008→T009. No task is parallel-write safe. Baseline960 Python/7Node passed; candidate assertions must catch dropped predicates, premature global limits, ignored source/model validity, missing setting restoration and caller transaction rollback.

## Playbook obligations

PB-5.5 content review and actual populated isolated upgrade/recovery proof belong to T005 and block PR readiness. No production migration/deployment is authorized for Feature5 by the current request.
