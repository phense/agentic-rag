#6.10 implementation tasks

### Slice S06801: Durable foreground execution
- [x] T06801 Red tests for durable handles, replay, fair quotas, expiry/cancel,
  foreign/RO/revoked result denial and atomic mutation rollback; FR03–06/AF01–03.
- [x] T06802 Implement024,requests.py,queued_transaction.py,API/client/spool
  negotiation and fixed executor; depends01; real DB/HTTP correction tests.
- [x] T06803 Add foreground/model priority and bounded background deferral;
  FR07/AF04; depends02; prove foreground progress and resumed extraction.

### Slice S06802: Native packaging and compression
- [x] T06804 Red package preservation/rollback and host event/compaction tests;
  FR01–02/AF05; depends02 shared connector.
- [x] T06805 Native manifests, package operator, shared MCP/lifecycle bridge and
  separate Gemini adapter; depends04; preserve existing local adapters.

### Slice S06803: Compatibility, operations and complete acceptance
- [x] T06806 Populated023→024 strict restore, version/dependency/docs update and
  PB06801 rehearsal; FR08–09; depends03/05.
- [x] T06807 Real40-client/p50/p95/resource and2–3continuity traces, full Python/
  Node checks and independent full-range review; fix C/H/M, append Lows75.
- [x] T06808 Publish tested stacked PR, immediate T3link, canonical68evidence;
  no merge/cutover without specific authorization; depends06/07.

## Convergence 1: remaining native and resource acceptance

Continuation after PR77/78, from merged `29a2f44` (0.6.20/schema032). Prior
T06801..08 remain complete; their package/adapter evidence does not prove native
authenticated compression or an agreed interactive latency budget. Canonical
Issue68 keeps these acceptance gates open. Run: RAG-068-A1.

### Slice S06804: Native continuity and interactive priority acceptance

- [ ] T06809 [FR01/02/09, AC03] Reconcile installed Claude/Codex/Gemini/agy/OpenCode versions and official capabilities with the matrix. Freeze small synthetic goals, original source markers and expected lifecycle/continuation outcomes before probing. Use isolated host configuration, owned databases/spool and finite deadlines; preserve global settings/auth and the old implementation/evidence.
- [ ] T06810 [FR02/03/04, AC02/03] Exercise genuine authenticated available-host manual/automatic compaction, termination/restart/resume, offline/ACK replay and final-tail fallback. Verify actual emitted events, original evidence, retained handles and useful continuation. Reuse unchanged adapter/queue race tests proportionally; disclose unavailable hosts and leave their gates open. Fix confirmed C/H/M with observed regressions.
- [ ] T06811 [FR06/07/09, AC01/05] On an owned 4-vCPU/8-GiB reference copy measure idle, growing and draining extraction backlog with20–40clients and shared-model contention. Separate queue/execution/total p50/p95, errors, CPU/PSS/RAM/model/disk/connection limits and eventual extraction progress. Check the maintainer's numerical latency target; do not label an unagreed budget accepted. Diagnose and correct priority/resource defects with bounded evidence.

### Slice S06805: Existing-installation compatibility and delivery

- [ ] T06812 [FR01/08, AC03/04] Deliver0.6.20→0.6.21 populated upgrade/retry/backup/independent restore and plugin update/recovery with preserved originals, scoped users/grants, pending handles/buffers and foreign host configuration. State whether migration is required; no reset or silent loss. Update PB06801 for changed steps and review/rehearse affected recovery paths.
- [ ] T06813 [FR09, AC04] Independently review the complete new bounded diff and changed native/priority/upgrade boundaries; inherit prior unchanged reviews explicitly. Derive real collaborating-component success/recovery probes, fix all C/H/M and Important findings, collect Lows in Issue75.
- [ ] T06814 [FR09, AC01..05] Reconcile exact as-built and every open canonical criterion. Run final source-bound full suite/Node/build/lock/docs checks, record actual exits and limits, publish measured before/after traces and tested upgrade path, create/link PR and merge autonomously after clean gates. Close Issue68 only for actually evidenced native/performance acceptance; no production cutover implied.
