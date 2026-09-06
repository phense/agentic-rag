# Tasks: RAG-009 project context

Specification:spec.md; plan:plan.md; base87077ce. Tests use issue9 DB overlay only.

### Slice S1: Rebuildable source-backed profile

- [x] T001 [US-001/003][AF-009A/C] Profile revision, bounded source selection/read,
  additive migration014, audited gateway, queue/worker refresh; meaningful failing then
  passing DB tests. Files:profiles.py,sql014,store.py,jobs.py,worker.py,tests/test_profiles.py.
- [x] T002 Independently review S1 ownership, source/validity/privilege and rollback.

### Slice S2: Selective gate and real-turn receipts

- [x] T003 [P][US-002][AF-009A] EN/DE gate/query and bounded host receipt independent of
  profile implementation; pure tests. Files:context_gate.py,tests/test_context_gate.py.
- [x] T004 Validate S1/S2 contract and baseline before dependent integration.

### Slice S3: Shared context and host integration

- [x] T005 [US-001/002][AF-009B] Shared context API, CLI/MCP and shared hook consumers;
  preserve checkpoint/pin caps, actual-output dedup, post-emission receipts and profile
  enqueue. Files:context.py,cli.py,mcp_server.py,hooks/,tests/test_project_context.py.
  DependsT001–004; tests first.

### Slice S4: Integration and convergence

- [x] T006 Reconcile as-built architecture; independent architect derives and verifies
  collaborating success and failed-refresh recovery fixtures. DependsT005.
- [x] T007 Synthetic baseline/after firing/usefulness/redundancy/latency measurements,
  full regression/package, independent review/fixes and SpecKit convergence. DependsT006.
- [x] T008 Docs/BACKLOG/FEATURES, commit and prepared backup-aware rollout/publication.
  Preserve exact pins/documents, reader privileges; verify CI/issue close when authorized.
