# Tasks: RAG-005 project scope
Source: spec.md, plan.md, docs/uml/findings.md. Executor: coordinator; serial writes.

## Slice S1 — scope storage and normalization
- [x] T001 Add failing path/write/migration tests (AC-004/005; tests/test_scope.py).
- [x] T002 Add scope.py, migration010, store scope gateway and audited legacy repair
  (depends T001; AF-002/003; agentic_rag/scope.py, store.py, pins.py, sql/010_project_scope.sql).

## Slice S2 — retrieval and automatic context
- [x] T003 Add pre-limit search, every-hop graph, CLI/MCP and global/all regressions;
  implement SQL/wrappers (depends T002; AF-001; search.py, graph.py, cli.py, mcp_server.py).
- [x] T004 Test/implement hook pin/document filtering and same-known-scope exact/near
  curation/refutation (depends T002/T003; AF-002/003; hooks, mining.py, curation.py).

## Slice S3 — validation and rollout
- [x] T005 Add versioned scope benchmark fixture and selector parameters/comparison
  guards; deterministic local run (depends T003/T004; benchmark/, tests/benchmark).
- [x] T006 Reconcile architecture, independent review and success/recovery checks,
  full suite; record fixes and verification (depends T001..005).
- [ ] T007 Document migration/recovery and user interfaces; backup, deploy, verify
  live invariants; commit/publish and close #5 (depends T006).

All ACs map above. No slice writes run in parallel. No additional paid model matrix.
