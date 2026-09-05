# Tasks: RAG-006 fact validity

All slices execute serially in the isolated worktree; no parallel DB ownership.
Base: f592dd6. Every slice uses meaningful failing tests before implementation.

### Slice S1: Atomic evidence and temporal history

- [x] T001 Add `tests/test_validity.py`, migration011, `validity.py` and
  `store.save_assertion`: immutable assertion documents, evidence, key lock,
  bounded candidate classification, event-order replacement and expiry. Verify
  current/as-of/history, duplicates, same-time conflict, extension and rollback.
  Sources: AC-001/002/003/005/006, IC-001, AF-007. Dependencies: none.
- [x] T002 Extend `mining_window.py` and `mining.py` for consumed event evidence,
  optional atomic assertion extraction, deterministic grounding and accepted batch
  persistence/replay. Tests reject invented source/quote/role/time and partial-window
  overreach. Sources: AC-002/005/006, IC-003, AF-006. Depends: T001.

### Slice S2: Consistent retrieval and lifecycle

- [x] T003 Extend SQL and search/hooks/graph plus CLI/MCP with current/as-of/history
  semantics and bounded review/get output. Test reader privilege, pre-limit eligibility,
  selected graph hops and interfaces. Sources: AC-001/004, IC-002/004, AF-008.
  Depends: T001/T002.
- [x] T004 Protect atomic assertions from ordinary curation and in-place edits;
  resolve legacy refute/reactivation review epoch. Verify pins and unrelated claims
  remain unchanged. Sources: AC-003/007, AF-009. Depends: T001/T003.

### Slice S3: Measured integration and publication

- [x] T005 Add temporal benchmark fixture/selectors and baseline comparison; retain
  results with current/historical recall and stale-result rate. Sources: AC-008.
  Depends: T003/T004.
- [x] T006 Reconcile UML, obtain independent complete-diff review and derived real
  success/recovery tests; fix findings and run full suite/build/migration checks.
  Write verification and user docs, FEATURES/BACKLOG. Sources: all AC/IC/findings.
  Depends: T001–T005.
- [x] T007 Fresh backup, lock worker, deploy additive migration, verify legacy
  invariants and idempotence, integrate/publish, verify CI, synchronize/close issue.
  Sources: FR-006, compatibility boundaries. Depends: T006.
