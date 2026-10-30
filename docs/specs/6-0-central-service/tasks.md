# Implementation Tasks: Central service

Issue58 / roadmap6.0. Coordinator owns every slice; shared interfaces execute serially. Existing local integrations remain available throughout. Independent Sol medium/high reviewers inspect bounded diffs; tests and reviews are bundled into at most three major rounds per slice. Low findings accumulate in Issue75.

### Slice S058-01: Authenticated scoped service

- [x] T058-01 — Write red contract tests for protocol negotiation, static users/machines, password login, revocation, invalid/RO access and four-client isolation (`tests/service/`); FR-002..005, AC-002; no dependency.
- [x] T058-02 — Implement `service/{auth,context,engine,api}.py`, additive SQL enforcement, `db.py` and MCP transport/routing; AF-058-001, IC-001/002; depends T058-01. Validate graph/get/search/count/context and definer-write boundaries before integration.
- [x] T058-03 — Run targeted real-DB transport tests and independent full-slice review; fix C/H/M, record Lows; depends T058-02.

### Slice S058-02: Durable input and continuity

- [x] T058-04 — Write red spool/ACK/replay/out-of-order/session-ownership and compaction/offline tests (`tests/service/`); FR-006/007, AF-058-003; depends S058-01.
- [x] T058-05 — Implement `service/{client,spool,ingest}.py`, bounded window input to existing mining, owned checkpoint routes and configured hook/stdio client integration; IC-003/004; depends T058-04.
- [x] T058-06 — Implement/test database worker singleton, central source processing, provider backoff, cancellation and crash replay (`worker.py`, `service/worker.py`); AF-058-002; depends T058-05.
- [x] T058-07 — Run four-client success and network/worker/provider failure integration tests and independent full-slice review; depends T058-06.

- [x] T058-07A — Verify40 persistent connections, bounded resources/central admission/log retention, and pressure/recovery without evicting input; FR-012, AC-008; depends T058-06. Include in S2 full-slice review. Deployment/model/backup limits also belong to T058-09/12.

- [x] T058-07B — Characterize24 independent AI sessions for two authenticated users on one logical VM, overlapping raw session IDs, distinct prompts/checkpoints, department denial and bounded429/backoff; FR-003A, AC-002A. Static per-user enrollment documented; automatic Herdr binding and OS/tool isolation remain explicit deployment prerequisites.

- [x] T058-07C — Publish immutable session-team attribution transactionally with first input/checkpoint; expose bounded discover/read REST routes, retain shared IT knowledge, enforce current team/project reading and owner-only mutation, preserve history after author departure. FR-003A/AC-002B; includes updated complete-feature review and fresh full suite after maintainer clarification.

### Slice S058-03: Safe upgrades and operations

- [x] T058-08 — Implement/test non-mutating version/schema/store/queue inventory, collision/path report, strict restore comparison and explicit local/remote upgrade preflight (`service/upgrade.py`, CLI); FR-009/010, AF-058-004, AC-001/005; depends S058-02.
- [x] T058-09 — Deliver and review/rehearse PB-058-01..03 (`docs/13-central-service.md`) plus static/deployment examples; FR-011, AC-007; depends T058-08. DB-058-01 isolated test-cluster procedure must precede migration operations.
- [x] T058-10 — Reconcile as-built architecture; independent reviewer derives at least one success and one recovery integration test, implement/run both; depends T058-08/09.
- [x] T058-11 — Run final full tests, populated legacy018/019 upgrade and strict restore/integrity/grant comparisons; record exact commands/exit states and any unsupported source/hardware limits (`docs/verification/issue58-service.md`); depends T058-10.
- [x] T058-12 — Measure2–3 practical scenarios, cold/warm latency, queue/backlog, CPU/PSS and bounded inference contention with explicit environment/model/sample details; AC-006/007; depends S058-01/02.
- [ ] T058-13 — Independent complete-range final review (max three major rounds), fix all C/H/M, append Low findings to Issue75, update release four-file patch metadata, FEATURES/BACKLOG index and create implementation PR linked to58; depends all above. Keep rollout-only acceptance open and ask separately for this PR's merge approval when reviewable.
