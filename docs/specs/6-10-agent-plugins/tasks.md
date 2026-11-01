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

## Convergence 2: confirmed retrieval inefficiency and remaining performance acceptance

The source-origin continuation review at `b110d37` has0 C/H/M/Important. Its
bounded diagnosis resolves M-ACC1 against that delta; it does not complete T06811
or AC05. [Issue92](https://github.com/phense/agentic-rag/issues/92) tracks the
remaining repair, before declaring6.10 complete. T06811 stays unchecked.
The proposed unbounded vector threshold count is rejected: the existing
materialized pool already has LIMIT4097. Preserve that bound and verify the
actual executed path instead of introducing a redundant fix.

### Slice S06806: Selective lexical work with unchanged authorized results

- [ ] T06815 [FR06/07, AC05, Issue92] Continue the confirmed-defect diagnosis on an owned populated copy; freeze selective/no-match/broad cases and source/result expectations before repair. Inspect the actual legacy/managed paths and nested query plans. Reproduce documents-first eligibility work with valid GIN indexes; no production or provider access to copied private excerpts.
- [ ] T06816 [FR04/07/08, AC02/04/05, Issue92] Repair matching/eligibility ordering without changing retrieval semantics or removing any authorization/truth/temporal/lifecycle predicate before ranking/LIMIT. Prove old/new result-set and order parity, reader RLS isolation, cancellation and finite SQL work. Deliver the next patch release, additive migration if needed, populated upgrade/retry/verified backup/independent restore and old-client parity; depends15 and the merged0.6.21 source-origin PR.
- [ ] T06817 [FR06/07/09, AC01/05, Issue92] Repeat bounded20–40-client reference measurements with actual growing arrivals and draining backlog, recorded foreground/background model overlap, honest sample sizes, queue/execution/total p50/p95 and per-phase resource accounting. Compare against the retained baseline without inventing an SLA or sustained-load proof; depends16.
- [ ] T06818 [FR08/09, AC01..05, Issue92] Complete independent bounded repair review, real-component success/recovery and current full-suite/Node/build/docs/lock gates; reconcile as-built and T06811 before Issue68 closure. Keep unobserved native host criteria in12–14, non-blocking Lows in75 and production cutover separate; depends16/17.

Correction scope for T06816 (review M1 and reference r2): materialize eligible
documents over distinct lexical-match IDs, independent of planner Memoize or
matching chunks per document; retain source-hash validation before ranking.
Keep service embedding preparation in its caller's context: the inference
executor previously lost worker authority/priority/timeout context. Do not copy
live database connections into concurrent thread contexts. Existing queued jobs
and accepted extraction batches must replay without data rewriting. These are
repairs to the existing ordering/admission contract, not new public options.


## Convergence 3: maintainer10-second search target

On2026-11-01 the maintainer rejected accepting r3's approximately60-second
search p95 or deferring latency to another issue. The target is end-to-end
successful-search p95 <=10seconds at40 active clients with extraction enabled
on the existing4-vCPU/8-GiB reference. Keep68/92 open until measured acceptance.
The stopped full4 on `0ec0ab1` is superseded, not passed (SIGTERM, exit-15,
all1,330 tracked files and HEAD unchanged).

### Slice S06807: bounded compilation and vector work

- [ ] T06819 [FR06/07, AC05, Issue92] Freeze and independently attribute remaining query cost on the owned reference. Retain the failed/no-result older runs. Separate model, query and queue costs; record the10-second target before changing code. No provider calls on copied private data.
- [ ] T06820 [FR04/07/08, AC02/04/05, Issue92] Add verified regression reds for generic vector-plan work. Preserve eligibility before ANN limits and exact full-response parity on the frozen fixtures. Bound retrieval compilation locally without leaking caller settings. Keep signatures, grants, source hashes, RLS and published001..033 unchanged. Rehearse the populated source upgrade, interruption/retry and independent restores with the final034 definition.
- [ ] T06821 [FR06/07/09, AC01/05, Issue92] Repeat the same mixed-tool20/40-client reference phases, distinct queries and background contention with the final runtime. Require successful search total p95 <=10seconds in each40-client contended phase, report sample sizes/failures/resources/model identity, and verify lossless eventual drain. No faster error responses, disabled inference or weaker authorization count as acceptance.
- [ ] T06822 [FR08/09, AC01..05, Issue92] Reconcile the complete final bounded diff, architecture/upgrade evidence and independent0 C/H/M/Important review; run the final source-bound full suite and affected Node/build/lock/docs gates. Update T06811/T06818 only after actual acceptance; retain native12–14 and production cutover separately. Merge only after clean delivery gates under standing authorization.


T06819/T06820 follow-up diagnosis after accepted N1 correction86d855d: two versus
four foreground consumers both miss10s (approximately24–28s search p95); no
consumer change is selected. Correlated-parent RLS membership rewriting gave
only a small SQL reduction and is not selected. Generic retrieval functions
instead parse the unchanged query for each scanned/ranked chunk: the8-case red
selection observed128 or256 parser calls per query. A rollback-only reference
probe computes each parser expression once and returns identical full responses
in approximately0.58s versus1.07s. Repair only that repeated work with scalar
initplans, preserve every operator/RLS/truth gate and score, and verify the real
parser-call bound, complete EN/DE parity, populated upgrade/restore and actual
reference load. This does not satisfy T06821 until the full acceptance run passes.
