# Tasks: RAG-5.8 evidence-backed entity identities

All implementation writes are sequential in the isolated feature worktree.
Independent reviewers are read-only and cannot perform test/database mutations.

### Slice 1: Stable identity and reversible scoped relation

- [x] T001: Add behavioral red tests in tests/test_entities.py for alternate-name
  status, historical rename, scope separation and revocation (AC-001–005).
- [x] T002: Add018 tables and entities.py identity/backfill gateway; preserve existing assertion/mining writers; verify original rows, unknowns and transactions
  (AF-5.8-001/003, AC-001/006/007). Depends T001.
- [x] T003: Implement immutable alias evidence, explicit confirmation/review and
  reversible revoke under exact scope/domain lock; test ambiguity/trust/concurrency
  (AF-5.8-002/004, AC-002–004/007). Depends T002.
- [x] T004: Implement one-snapshot bounded entity reads, cross-name replacement,
  conflicts, original citations, missing-schema fallback (AC-003–005). Depends T003.

### Slice 2: CLI/MCP and populated upgrade/recovery evidence

- [x] T005: Add CLI read/alias/review/backfill and additive MCP tools, reader gating
  and malformed-input/privilege tests (AC-007). Depends T004.
- [x] T006: Execute scripts/verify_entity_identities.py on populated source017:
  strict backup/restore, DDL/batch interruption, resume/no-op, old/new/rollback clients,
  queued work/config invariants and Trading read-only controls (AC-006/008). Depends T005.
- [x] T007: Record three paired examples with literal denominators, first/warm,
  p50/p95/raw samples and source revisions (AC-008). Depends T006.

### Slice 3: Reviewed handoff

- [x] T008: Author reference and PB-5.8; independently review and rehearse actual
  procedure; reconcile Feature7 with canonical Issue32 adoption (AC-006). Depends T006.
- [x] T009: Independent complete diff review, fix findings and repeat review; derive
  cross-component success/recovery checks from as-built model, run full Python/Node
  verification (AC-001–008). Depends T007/T008.
- [ ] T010: Update Issue33, backlog/features/verification; push feature branch and
  create linked PR. Keep Issue33 open for applicable rollout; request specific merge
  approval only after all gates pass. Depends T009.

Executed evidence: [verification](../../verification/entity-identities.md), [measurements](../../benchmarks/2026-10-04-entity-identities/README.md). T010 remains until exact PR publication/linking; merge and production adoption are separate authority gates, not implementation tasks.
