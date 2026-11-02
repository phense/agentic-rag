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


## Convergence 3: maintainer search target, revised to strictly <11seconds

On2026-11-01 the maintainer rejected accepting r3's approximately60-second
search p95 or deferring latency to another issue, initially requiring <=10seconds.
The later explicit revision is end-to-end successful-search p95 strictly
<11seconds at40 active clients with extraction enabled on the existing4-vCPU/8-GiB
reference. Preserve earlier protocol thresholds and failed results as historical
evidence; assess the new boundary separately. Keep68/92 open until measured acceptance.
The stopped full4 on `0ec0ab1` is superseded, not passed (SIGTERM, exit-15,
all1,330 tracked files and HEAD unchanged).

### Slice S06807: bounded compilation and vector work

- [ ] T06819 [FR06/07, AC05, Issue92] Freeze and independently attribute remaining query cost on the owned reference. Retain the failed/no-result older runs and their original10-second protocols. Separate model, query and queue costs; record the revised strictly <11-second target before further changes. No provider calls on copied private data.
- [ ] T06820 [FR04/07/08, AC02/04/05, Issue92] Add verified regression reds for generic vector-plan work. Preserve eligibility before ANN limits and exact full-response parity on the frozen fixtures. Bound retrieval compilation locally without leaking caller settings. Keep signatures, grants, source hashes, RLS and published001..033 unchanged. Rehearse the populated source upgrade, interruption/retry and independent restores with the final034 definition.
- [ ] T06821 [FR06/07/09, AC01/05, Issue92] Repeat the same mixed-tool20/40-client reference phases, distinct queries and background contention with the final runtime. Require successful search total p95 strictly <11seconds in each40-client contended phase, report sample sizes/failures/resources/model identity, and verify lossless eventual drain. No faster error responses, disabled inference or weaker authorization count as acceptance.
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


T06819/T06820 contextual follow-up: the same documents-first truth work exists
in thematic membership, called three times by startup context. Frozen pre-repair
SQL and8 regression cases reproduce62/124 real claim checks even with no lexical
matches. Materialize scoped lexical matches before checking distinct documents;
retain cheap status/domain/project filtering before materialization to avoid
scanning the whole store for a narrow project. Preserve the entire candidate
version/cache packet, current/history rules and eligibility before the25-row pool.
The unscoped first prototype regressed reference context latency and is rejected;
the corrected scoped prototype preserves the response hash while reducing the
context's actual lifecycle calls1974→932. Do not change RLS policies or consumer
count on this evidence. Record fresh whole-context/resource/load acceptance after
independent review; the117-test affected selection is not the full suite.

## Convergence 4: implement the B3 configuration and actual client

The post-B3 independent review accepts the numerical result under the revised
strict<11s target and requires product behavior before acceptance. A2 and
`docs/uml/model-admission-92-a2.md` define the minimum; no further performance
experiment, consumer sweep or own executor is selected. Preserve prior task IDs,
frozen protocols, failed runs and the independently accepted SQL changes.

### Slice S06808: Optional model lane and bounded actual-client delivery

Execute serially after S06807's accepted runtime0a08785. One owner handles
`config.py`, `embed.py`, `service/priority.py`, `service/requests.py`,
`service/client.py`, their cache/profile callers and affected tests/docs. Do not
change migration034 or published001..033. T06821/T06822 remain coordinator gates.

- [ ] T06823 [FR04/05/07/08, AC02/04, AF092-A2-01..05, PB3-02..05] Before runtime edits, commit deterministic meaningful failing tests for the optional lane/configuration, existing default HTTP payload/routing, per-lane admission and pre/post digest checks, attempt-preserving pressure/replay, consumer reserve/ContextVar/shutdown semantics, hint scheduling and pre-ACK same-envelope retry. Cover non-finite hints, deadlines, permanent errors, lost ACK, cancellation, legacy synchronous and queued-server compatibility. Use serial suites and isolated synthetic stores.
- [ ] T06824 [FR04/05/07/08, AC02/04, AF092-A2-01..03, PB3-03/05] After T06823, implement the A2 typed optional URL/timeout/thread settings and1..4 consumers with the half-default-pool reserve. Route only fenced central legacy background inference, use its own lock, verify both model identities before/after, retain primary cache identity and managed-profile routing. Preserve no-setting behavior and pinned graceful shutdown. Reject invalid config before work starts.
- [ ] T06825 [FR05/06, AC01/04/05, PB3-02/04] After T06823, implement bounded finite `retry_after` polling and0.3s jittered pre-ACK contention/timeout retry using the existing durable envelope/key and caller deadline. Preserve offline/replay/cancel/terminal behavior,12/s namespace gates and four control slots. Verify old queued servers already sending hint1 and defensive missing-hint fallback. Never count waiting as completion.
- [ ] T06826 [FR06/08/09, AC04/05, PB3-04/08] After T06824/25, update configuration/central-service guidance, CHANGELOG and PB06801 with exact opt-in daemon resource limits, model identity/parity probe, startup order, all-process restart and mixed-version polling load, key-removal/restart recovery. Keep version0.6.22 consistent; no extra patch increment inside this existing PR branch. Review/rehearse required operations before activation.
- [ ] T06827 [FR04/05/08/09, AC02/04, AF092-A2-05, PB3-08] After T06824..26, rehearse the final runtime on a populated multi-user0.6.21 source: interrupted upgrade/retry, independently restored source/target backups, original/user/domain/ACL/job/receipt/history preservation, optional-config rollback and all A2 runtime success/recovery cases. Use real collaborating queue/client/worker/gateway/DB components with mock inference only for failure tests; report exact scope/limits. Run affected suites serially and commit clean source/evidence.
- [ ] T06828 [FR04..09, AC01..05, PB3-01..08] After T06827, coordinator performs complete bounded independent review plus architecture success/recovery reconciliation. Resolve C/H/M/Important, collect Low in75, then execute T06821 once on the final implemented source and T06822's full-suite/delivery gates. No feature closure from the B3 numerical disposition alone.


### Resource-recovery refinement within S06808 (not an acceptance pass)

T06826/T06828 include the fixed unload/check procedure and independent kit/PB
re-review described in the plan. Keep4GiB pre-BG and2GiB both-resident gates,
API/PG active and worker paused; record recursive cgroups and actual model
residency. Run feasibility before full parity, then a fixed primary reset
before gate B; no reset or retuning during load/drain. The corrected-format
resource diagnostic passed on an owned copy; it is not T06821. Its preceding
reference-encoding failure is retained. The original full-suite r4 passed
2508 tests with1 skip on57b1f51; product/tests/SQL remain unchanged by this
procedure refinement. Full physical acceptance and closure remain open.

### Slice S06809: Deadline-bounded fresh-client discovery

The physical run `488792ab23a2` failed before measured phases: 14 fresh-client
discoveries received transient HTTP429 capacity refusals. Preserve that failed
run and its successful parity/recovery evidence; do not count it as T06821.

- [ ] T06829 [FR03/06, AC01/05, plan A3] Freeze regression tests before runtime changes: parsed discovery HTTP429 capacity refusal followed by success must retain one envelope; persistent refusal must stop at the caller deadline with its original handle. Authentication, malformed/unsupported responses, offline/503 and unrelated429 failures remain immediate.
- [ ] T06830 [FR03/06/08, AC01/04/05, plan A3] Implement only that bounded discovery retry, retaining current server/control/rate gates and direct negotiation consumers. Verify client-first/old-server compatibility, pending-spool retention and the populated0.6.21 upgrade/retry/independent source and target restores; document client restart/code rollback.
- [ ] T06831 [FR03..09, AC01..05, plan A3] Independently review the complete correction, resolve C/H/M, collect Low in75, run affected checks and the final full suite. Only then refreeze and run T06821 once with the unchanged physical criteria. Reconcile T06828; no acceptance from warm-up or partial phases.
