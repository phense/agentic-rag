---
title: PB06801 review and rehearsal evidence
type: reference
audience: administrators
version: 0.6.22
---

# PB06801 review and rehearsal evidence

The historical0.6.11/schema024 rehearsal below was recorded2026-10-30. The
0.6.21/schema033 continuation follows it with separately scoped evidence. These
are owned-copy development rehearsals, not production cutover or a maximum-capacity guarantee.

## Verification and review

- The final isolated Hetzner Python run passed **1,520 tests, 2 skipped**,
  one upstream Starlette warning, 327.19s, exit 0. Skips are macOS launchd and
  absent real Claude transcripts. Applicable OpenCode Node checks: **7 passed**.
- Independent complete-range Sol/high review1 found2High/5Medium/1Low. All were
  reproduced and corrected; the Low diagnostic mismatch is LOW-011 in Issue75.
  Review2 found1High/2Medium around ambiguous Gemini authorship, header-only
  recording and a background dependency cycle. Five red regressions reproduced
  them; 19 focused checks passed. Review 3 examined all 62 files of tree
  `6368f674c5db79bd3ea35697d9734e93e4848bef` against base `07f989f` and found
  no remaining defects; its independent selections passed 78 Python and 7 Node
  checks. This is the third and final independent review, not a native UI proof.
- A subsequent real-cloud repetition found one transient result-publication
  lock collision: 119 of 120 requests completed, one failed with
  `result_capacity_exceeded`; all 20 source windows applied. Three new tests
  reproduced this. The small correction waits at most one second, then keeps
  the same accepted input pending while rolling back uncommitted effects.
  All 22 affected tests passed, followed by the full run above. This correction
  was coordinator-checked after review 3; its corrected cloud repetition is
  reported separately below, without hiding the failed run.
- One later non-blocking status detail is open as
  [LOW-012](https://github.com/phense/agentic-rag/issues/75#issuecomment-6513105016):
  successful completion can retain its former transient deferral code. A real
  HTTP/SQL probe confirmed the successful result and exactly one document/audit;
  the connector follows terminal state and consumes that result correctly.
- Built wheel `agentic_rag-0.6.11-py3-none-any.whl` includes schema024 and plugin
  code. A fresh environment installed it outside the checkout; install and
  doctor passed for all three native packages (6 operations). Offline dependency
  installation initially lacked cached wheels; normal dependency installation
  succeeded. `uv lock --check --offline` passes with 42 packages.
- Synthetic populated023→024 migration, current024 versioned backup/strict
  restore and retry passed. The real populated reference copy began at022;
  its verified upgrade applied023/024 and preserved299256 original rows across
 26tables, including compatible embeddings, history, ACLs and pending jobs.
  Only afterward were copied legacy jobs frozen to prevent original private
  transcripts reaching the rehearsal model. Twenty new synthetic windows were
  extracted using the authorized provider; all20 reached applied.

## Native observations and practical continuity traces

Claude native manifest validation passed; Codex CLI0.165.0 installed the owned
package through an isolated marketplace; Gemini CLI0.66.0 installed the extension
after its explicit trust prompt in a private test home. No credentials were
copied to the isolated Gemini home. Validation/install do not prove interactive
hook delivery or model-authenticated manual/automatic compression. Issues12–14
remain open for those actual native scenarios.

1. Claude/Codex manual and automatic payload fixtures run the real pre-compaction
   adapter, retain source/checkpoint, then remove the host transcript. The private
   spool still contains original source and the matching trigger. Child/fork/
   maintenance callbacks do not enter the capture engine.
2. Gemini fixtures cover a fresh header-only recording, patches, manual/automatic
   PreCompress and next-BeforeAgent handoff restoration. Installed-host source
   replay demonstrates that BeforeAgent also receives hook-generated continuation
   reasons. Both recording-user and hook-input prose therefore remain advisory;
   no synthetic approval acquires original user support. A history parse failure
   retains the separately observed input before reporting the failure.
3. Real HTTP/SQL connector tests cover durable ACK loss/replay, read/write/result
   consumption, owner-only extraction status and foreign denial. A subprocess is
   killed inside queued-save embedding; restart applies exactly one document and
   one save audit record. Cancel, scope/credential change and oversized result
   roll back canonical effects. Accepted source-backlog pressure yields to the
   source worker and then completes the waiting mutation without cancellation.

These are controlled adapter/HTTP/process traces, not authenticated native UI
observations. PB06801 package preview/apply/doctor/update/uninstall/recover was
rehearsed on owned directories; partial update/uninstall recovery preserves the
reviewed generation and refuses foreign edits. Native memories and pending input
remain outside package ownership.

## Reference-host 40-client measurements

CX33, 4 vCPU/7757 MiB, no swap; separate code/database copy and loopback API.
Each phase offered 40 simultaneous mixed requests from 4 uploader identities in
2 teams: 14 metadata, 13 context, 13 populated hybrid searches, reranking disabled.
After the publication correction, all 120 requests received durable handles and
completed. Gateway throttling was retried with the same envelope: 96/91/82
transport retries across the phases. Before the third burst, the sampler observed
an actual active background inference child. These are finite workloads, not a
maximum-throughput ceiling or an agreed response-time guarantee.

| Phase | Metadata p50/p95 | Context p50/p95 | Search p50/p95 | Total |
|---|---:|---:|---:|---:|
| Idle extraction | 22.43/50.44s | 34.02/40.21s | 38.55/65.30s | 71.74s |
| 20 queued source windows | 27.63/53.46s | 40.64/59.54s | 38.14/64.15s | 69.56s |
| Active background inference | 35.05/63.34s | 48.49/51.59s | 35.36/62.45s | 67.98s |

These latencies include queue wait and polling. Fixed foreground consumers limit
concurrency; the mixed queue can delay small metadata/context calls behind search.
Context p95 rose in the growing-backlog sample, while search p95 fell slightly.
The samples do not isolate causation or establish a numerical latency guarantee.
A short hook returns a waiting handle or labeled retained context while accepted
work finishes. Operator acceptance of a latency budget remains a rollout decision.

The corrected 1-second sampler collected 299 points over 336.51s, including the
subsequent background drain. PSS apportions shared pages; summed RSS can count
the same PostgreSQL pages repeatedly.

| Process group | Peak PSS | Peak RSS | CPU-time increase |
|---|---:|---:|---:|
| API | 71.16 MiB | 85.18 MiB | 22.89s |
| One worker and its CLI helpers | 320.64 MiB | 339.36 MiB | 24.50s |
| Shared PostgreSQL instance | 588.74 MiB | 1600.32 MiB | 333.66s |
| Shared Ollama service | 840.14 MiB | 846.10 MiB | 234.05s |

There was one API application process and one serial extraction worker. The
worker's group contained at most 4 processes including transient CLI helpers,
not one inference session per client. Maximum connections to the rehearsal
database: 10. One embedding model remained resident, with at most 695845517
reported model bytes. Shared PostgreSQL/Ollama CPU includes other instance work;
it is not attributed exclusively to the test.

Database size grew 656463539 to 656799411 bytes (335872 bytes). This measures
logical database files, not whole-host WAL, backup or snapshot growth. After the
rehearsal, host SSD usage was 18 percent with about 59 GiB free. All 20 new
synthetic source windows applied after interactive demand subsided; the owned
API/worker were stopped before the separate sustained run. The earlier sampler
with the wrong Ollama unit and the later 119/120 failing run are retained as
private diagnostic evidence, not substituted for this corrected result.

## Sustained workload

Forty concurrent logical clients continued submitting work for 300 seconds through
a bounded shared HTTP pool. Outstanding work finished after 370.65 seconds:
203 offered, 203 durably accepted, 203 completed; 135 transport retries, no failed
or expired accepted requests. Each client completed at least 4 turns. Another
20 synthetic source windows waited behind this foreground demand.

| Tool | Completed | End-to-end p50/p95 |
|---|---:|---:|
| Metadata | 73 | 71.03/83.05s |
| Context | 66 | 70.58/84.03s |
| Populated hybrid search | 64 | 73.37/83.04s |

The active phase supplied 323 resource samples over 371.55 seconds. API peak
PSS/RSS was 69.44/86.68 MiB; median PSS of its first/last 10 samples was
65.55/69.44 MiB. The paused single worker stayed at 53.28/53.29 MiB median PSS,
peak 53.29 MiB. Shared PostgreSQL peaked at PSS 685.15 MiB (RSS 3060.38 MiB);
Ollama peaked at PSS 841.88 MiB (RSS 847.86 MiB), with one resident model.
Maximum rehearsal-database connections: 12. API/worker/PostgreSQL/Ollama CPU time
increased 55.44/1.35/683.23/351.22 seconds. Database files grew 311296 bytes.
The worker did not start a model child during the sustained interactive phase;
its retained sources resumed afterward. Warm-up growth and these finite samples
do not establish zero leakage or an indefinitely sustainable arrival rate.
All 20 reached `applied` after the foreground run; the owned API and worker
stopped successfully. This gives 40 applied synthetic windows across the two
final corrected rehearsals.

The installed-copy smoke also started the actual plugin stdio server and called
it through an MCP client, then through the queued HTTP connector into the copied
store. RW exposed 20 tools, RO exposed 11; save/get returned the synthetic body
and RO rejected mutation. This is an actual process/transport observation, not a
claim of authenticated Claude/Codex/Gemini UI compression.

## Evidence identity and rollout boundaries

The final full Python command ran as the owned PostgreSQL test operator with
`PGPORT=55458`, private test HOME and `PYTHONDONTWRITEBYTECODE=1`:

```sh
/opt/agentic-rag-68/.venv/bin/python -m pytest -q -rs -p no:cacheprovider
node --test tests/test_opencode_plugin.mjs
```

Python log SHA-256:
`5e0febd1233b403dba44b6bc39afa27a73b2a39d9da7b54c6e94c2987c1ccae4`.
Tested code/test snapshot manifest SHA-256:
`1913ab0e9abee36293b5cb99ceef04d266144fe4c275672a61072354a485745d`.
Final documentation/evidence edits follow that snapshot and receive their own
render/link and 15-test documentation check; application code remains identical.

Complete private logs, distribution/source manifests and aggregate JSON remain
outside the repository. Public evidence contains no original private corpus,
prompts or tokens. Native authenticated manual/automatic compression, abrupt
terminal exit and resume scenarios remain open under Issues12–14. Production
writer cutover and independent-store consolidation remain separate operations;
the canonical worker's boot guard stays inactive. A day-long leak test, sustained
40-client model inference and acceptance of a numerical interactive latency
budget remain unproved. Finite storage/retention guards and short workload
measurements are the evidence supplied by this PR.

## RAG-068-A1 source-origin correction: provisional evidence

The source-origin section in PB06801 targets0.6.21/schema033. The correction review below accepts
its bounded source-origin slice; final release and whole-feature gates remain open.
The prior0.6.11 evidence above does not validate this new gate.

Targeted command with owned PG55460 and owned temporary files:

```sh
PGPORT=55460 TMPDIR=/dev/shm/rag68-a1 .venv/bin/python -m pytest -q \
  tests/test_transcript_origin.py tests/test_transcript_origin_upgrade.py \
  tests/test_mining.py tests/test_mining_window.py tests/test_evidence.py \
  tests/test_validity.py tests/service/test_local_capture.py \
  tests/service/test_source_worker.py tests/test_extraction_policy_mining.py \
  --tb=short -p no:cacheprovider
```

Observed result:117 passed, one known Starlette warning, exit0 in47.55s.
Regressions first failed on actual generated native shapes and on staged
generated prose reaching inference. The first staged-window red had a missing
test argument; only its corrected second red is behavior evidence. A later
neighbor run had116 passes and one fixture authentication failure; supplying
the fixture's missing credential revision produced the result above.

Real SQL/gateway checks cover existing misattributed claims, unchanged original
body/provenance rows, idempotent repeat, source tombstones before a pending old
attachment, scoped service-writer attachment, wrong digest/stopped-writer gate,
provider exclusion for old staged windows, and an injected audit failure with
zero surviving source/history rows. Inference is mocked at its provider boundary;
this is not a fresh full suite, independent review or production rollout.


## RAG-068-A1 origin corrections (provisional, 2026-11-01)

The source-origin review at `f8d69a6` found M1 and two Important operational
gaps. The correction adds migration033 without changing published001–032:
only replacements supported solely by proven generated-origin tombstones lose
their suppressive effect. Ordinary refutation/removal/expiry keep the no-revival
rule. Replayed assertions with an inactive source are review-only. The source
lock follows an existing duplicate claim lock; a two-connection regression
reproduced the inverted order before the fix.

The bounded selection passed89 targeted tests in41.45s. This includes the
actual archived0.6.20 code populating schema032, an interrupted033 migration,
retry, preservation checks and real independent pre-/post-migration restores;
remote-window coverage and unchanged SQLite raw export; the literal O2 Python
snippets; current-fact no-revival regressions; and native package update/recovery.
Native manifests now advertise the installed Python distribution version rather
than the old fixed0.6.12. These are targeted proofs, not a full-suite result.

The first attempted SQL correction checked general replacement eligibility;
`test_temporal_source_refutation_does_not_revive_old_value` rejected that broad
behavior. The published correction deliberately keeps normal no-revival and
adds a regression with both generated and independently refuted real evidence.
The first new replacement fixture lacked explicit replacement wording; that
initial failure was a fixture error. The corrected blue/red regression then
failed for the actual current-fact defect in both applied and pending cases.

At this intermediate measurement snapshot, PB O1–O4 still awaited independent
correction review and the package metadata still reported0.6.20. The later
review, native observations, reference diagnosis and0.6.21 upgrade selection are
recorded below. Neither this targeted run nor the later observations establish
a full-suite pass, an agreed latency SLA or a production rollout.
Writing depth: small, one focused correction within this existing evidence page
and its linked playbook; no documentation-set restructure.


The correction review at `93e455d` accepted M1/P1/P2/P3/P4 with0 C/H/M and0
Important. Its59/59 fresh assertions used14 owned databases (all removed).
The source-bound extended root selection finished with124 passed, one known
Starlette warning, exit0; pytest142.81s, supervisor144.11s,389 source files
unchanged, logSHA256 `9691de3d63a0f1dde8558973773bd2e970a4f33d7aafac9a74d998303de0c962`.
This remains a targeted selection. The review's new Low-A (unreserved marker)
and Low-B (current reason can be overwritten) go to Issue75; the three small
playbook/canonical-guide clarifications are incorporated. The observed predicate
cost at600 assertions was0.270s versus0.184s, best of5 on the test host; this is
an observation for the open reference latency gate, not accepted performance.
Editable environments must be reinstalled after the release bump so generated
native manifests read the new installed metadata; restart alone is insufficient.


## Native continuation observations, 2026-11-01

Writing depth: small, one evidence update in this existing record. Claude
Code2.1.314 ran only frozen synthetic prompts in an owned workspace, package,
configuration and spool. Global settings and authentication were retained.
Manual shortening emitted real PreCompact/manual, SessionStart/compact and
PostCompact/manual. A separate native resume recalled all3 identifiers.

The frozen multi-turn automatic protocol at `fd4fe99` crossed its controlled
1% threshold on padding turn4, after4 completed assistant replies. It emitted
PreCompact/auto, a native summary record, SessionStart/compact and
PostCompact/auto. A separate native resume recalled3/3 identifiers; total81.04s.
The reader emitted12 original source events and0 of5 generated records. Raw
source and compacted checkpoint remained durable offline. Earlier two0.1%
attempts emitted PreCompact without PostCompact; they remain failed observations,
not successful compactions. The prefix line was a warning, and the decisive
abort was the empty assistant summary set.

The separate same-partition TCP admission probe at `a6b80fb` started offline,
then brought up its own authenticated loopback service and isolated database.
After committing the first window, the harness replaced its ACK with503; replay
returned the same receipt. A genuine native resume recalled3/3 identifiers.
All4 original event IDs reached2 unique windows/jobs, with0 pending local items;
raw source remained retained. Total23.26s. No compaction occurred in this ACK-only
session, so it created no checkpoint. No extraction worker/provider ran: these
receipts prove durable admission, not applied memories. The first ACK attempt
failed only because the harness expected200 instead of the correct202; its
native initial turn and failed artifacts were preserved.

Machine-readable observations and frozen protocols are in
[the native acceptance directory](../../benchmarks/2026-11-01-native-plugin-acceptance/).
They do not prove other hosts, ordinary automatic thresholds, TLS, cross-host
outages, reference-load latency, a long soak or production rollout.

The final target-release upgrade selection added a real0.6.21-labelled backup
and independent restore to the populated archived0.6.20→033 scenario. It first
failed with `unsupported_source_version`, then passed after the target label was
supported. The release/upgrade/package selection completed38 tests, one known
Starlette warning, exit0 in69.65s. Editable distribution metadata is now0.6.21.
Node contracts completed7/7; these checks do not replace the final full suite.

## Reference-host observations, 2026-11-01

Writing depth: small, a measured-results section in this existing record.
The owned copy retained24,505 documents from the read-only schema024 rehearsal
snapshot and applied025–033 only in its private cluster. This load setup is
separate from the populated0.6.20 upgrade/restore proof. The host has4 CPUs,
8,134,742,016 bytes RAM and no swap. Other production services remained running;
the existing loopback Ollama served real CPU `bge-m3-q8` embeddings. Extraction
used scripted synthetic semantic output, not a real LLM.

The conforming run used1.05s status polling after admission; temporary admission
and status errors retried after0.3s. All140 offered requests completed across
four principals. Both background phases overlapped an observed real embedding
call (1.296s and0.505s respectively); all8 source windows eventually applied.
These are short bursts, not sustained concurrent embedding load.

| Phase | Clients | Metadata p95 total | Context p95 total | Search p95 total |
|---|---:|---:|---:|---:|
| Idle20 | 20 | 34.59s | 34.98s | 48.90s |
| Idle40 | 40 | 55.90s | 61.45s | 87.75s |
| Growing40 | 40 | 75.28s | 72.83s | 86.32s |
| Draining40 | 40 | 62.62s | 80.87s | 87.37s |

Queue waiting dominates these totals. Execution p95 ranged0.15–0.24s for metadata,
0.98–1.87s for context and13.73–14.06s for search. This does not establish an
acceptable interactive SLA; no numerical target was agreed. Avoid promising
low-latency40-client operation from completion alone. A prior250ms-poll stress
run also completed140 requests but lacked the recorded background-start
precondition; it is retained separately, not pooled with these observations.

There were322 resource samples with0 sampler errors: own-process peak PSS
393,250,816 bytes, at most16 DB connections, one resident model
(695,845,517 bytes), own database files at most1,290,008,595 bytes, and host
available RAM at least4,359,868,416 bytes. The bounded supervisor exited0 in
396.931s, reported1G peak cgroup memory,0 swap and732.908 CPU-seconds including
setup/sampling but excluding the shared model process. Both owned children and
PostgreSQL stopped. Production configuration/services were not changed.

The imported product source was `9cc025f`, while installed dependency metadata
still reported0.6.11; this was not a deployed0.6.21 release. Only the supported
upgrade-version labels changed in product/SQL paths between that source and the
target release. Aggregate-only results, limits and protocols are published in
[the acceptance directory](../../benchmarks/2026-11-01-native-plugin-acceptance/reference-conforming-result.json),
with the [earlier stress run](../../benchmarks/2026-11-01-native-plugin-acceptance/reference-stress-result.json)
kept separate. Private copied result bodies and native account/debug data are
excluded. Full-suite and final independent review remain delivery gates.

### Bounded diagnosis after M-ACC1

The six affected legacy test functions were corrected together after five more
stale-version assertions reproduced red. Their full six-file selection passed36
checks in108.52s, one known Starlette warning. The changes retain future-version
rejection at0.6.22 and use the installed0.6.21 backup label. Full3 on `f213ae7`
is running and is not a pass.

The reference-copy diagnosis used the same source, RLS reader and fixed synthetic
search, with no concurrent load. All22 relevant indexes were valid/ready, including
the chunk HNSW and English/German GIN indexes. Automatic statistics already existed;
explicit `ANALYZE` took2.893s, and the wrapper execution stayed10.839s versus10.025s.
The full eligible-document count alone took3.26s/3.06s for6,507 eligible of24,513.
An expanded-body `EXPLAIN ANALYZE` shows the vector branch using HNSW (~0.534s),
while both lexical branches scan24,513 documents and retain6,507 before per-document
chunk probes, returning0 lexical rows (~3.289s and3.214s). Thus repeated validity/RLS
work and a documents-first join plan dominate this synthetic no-lexical-match case;
missing indexes or statistics are not supported as the cause.

The expanded body used a fixed midnight reference time and different plan caching;
its7.130s is structural evidence, not a measured product speedup. No predicate,
authorization, scheduler or production setting was relaxed. Two bounded foreground
consumers serialize heavy searches and cheap metadata alike; this explains the
queue buildup while retaining the existing finite compute budget. This is a
correctable retrieval inefficiency, not an SLA acceptance or a claim that cheap calls are fast
under a40-client burst. M-ACC1 remains pending independent disposition.

The prior `growing40` label denotes8 windows already pending at burst start, not
continuous arrivals. Model overlap was short and p95 samples per tool are small;
no sustained-growth/contention or long-soak result is established. Aggregate
[diagnosis plans and limits](../../benchmarks/2026-11-01-native-plugin-acceptance/reference-diagnosis-result.json)
exclude SQL text, vectors and result bodies. Both owned-cluster diagnosis runs
stopped PostgreSQL in `finally`; production services were untouched. Native child
suppression remains adapter-tested, not natively observed (LOW-064). CPU attribution
is coarse (LOW-063). Both are recorded in Issue75.


The final correction review at `b110d37` accepts H1 and the bounded M-ACC1
diagnosis with0 C/H/M/Important. The confirmed lexical inefficiency and remaining
T06811/AC05 acceptance are tracked in [Issue92](https://github.com/phense/agentic-rag/issues/92);
Issue68 and T06811 stay open. The asserted third unbounded vector count is not
established: `indexes._neighbors` already materializes at most4,097 eligible rows
before counting, on both the base and current source. The whole-corpus count in
the diagnosis was a separate timed probe, not a traced third scan in that search.
Do not add its time to the measured query as though both were one operation.
The033 overhead measured on synthetic replacement-superseded documents is
recorded as LOW-065 in Issue75, with concurrent-host/noise limits. Full3 remains
an independent delivery gate until its actual terminal result is available.


## Source-origin delivery gate, 2026-11-01

The complete Python suite on `f213ae76734c311bc49e10eca532511ded88491a`
finished with **2,187 passed,1 skipped,1 known warning, exit0** in2,032.59s
(supervisor2,034.57s). The skip is the macOS-only launchd install test. All392
product/test/SQL/assets/version source hashes remained unchanged during the run;
later changes are documentation only. Log SHA-256:
`1b27a932dd6fc273c6057d37d78e4c6ec3d30d426790def732aadfa8c4fd40d9`.
The [terminal summary](../../benchmarks/2026-11-01-native-plugin-acceptance/full-suite-result.json)
records the command, source manifest digest and limits. Earlier full1/full2
failures remain recorded; neither is counted as passing. Applicable Node7/7,
offline lock check and0.6.21 wheel/sdist build passed on the same product tree.
Independent source-origin/correction reviews leave0 C/H/M/Important; non-blocking
LOW-059..065 are tracked in Issue75.

This permits delivery of the0.6.21 source-origin correction with its tested
populated upgrade/retry/restore path. It does not close Issue68: T06811/AC05
repair and performance acceptance continue in Issue92, and unobserved native
host criteria remain in Issues12–14. No production migration or cutover is implied.

## 0.6.22/schema034 lexical-search continuation

The populated rehearsal in `tests/service/test_lexical_upgrade.py` uses archived
0.6.21 (`64f2104`) to create a multi-domain/project store with original assertions,
a pin and pending work. The verified0.6.21 backup restores independently before an
injected migration failure; the034 transaction rolls back. A new attempt applies
only034, preserves original-row hashes and function OIDs/owners/grants, and keeps
the old scoped reader response identical. Repeating applies no migrations. A
truthfully labelled0.6.22 backup also restores independently. After the corrections, the upgrade, priority and documentation selection passed
23 tests in14.93s. The inference, priority and full lexical-parity selection passed
134 tests in88.26s; eight new broad multi-chunk cases also bound actual work with
Memoize enabled and disabled. Three worker regressions were observed failing
before the correction, then passed through real model admission and mocked HTTP.

The full suite on `26184b9` passed2,280 tests,1 skipped and1 known upstream
Starlette warning (exit0,2,153.68s);396 source files stayed unchanged. This result
predates the correction of review M1 and the worker-context defect and does not
certify the corrected tree. The first review found contextual eligibility work
repeated per matching chunk. The retained reference r1 and r2 load attempts ended
with `no_actual_background_embedding_observed`; neither is a contention pass.
The bounded replay showed inference running in a thread without worker context,
so it was classified and admitted as foreground. The subsequent correction review and reference r3 are recorded below; a fresh
terminal full-suite result remains required.

See [bounded comparison evidence](../../benchmarks/2026-11-01-lexical-eligibility/verification.json).
No live rollout, production lock-duration guarantee or agreed latency SLA is
established by these owned-copy rehearsals.

The corrected paired SQL comparison completed12 before/after units on the
24,513-document owned reference: every private full response, score and order
matched. Original function definitions were restored and the owned database
stopped before the separate load run. This does not certify that load run.

The model-budget A/B used one owned Ollama instance with identical model/input:
1536MiB `MemoryHigh` produced a10-second timeout and7,392 new high-limit events;
2GiB completed in0.705s with no additional high-limit events. Both arms kept the
2GiB hard cap, and no OOM occurred. This is one bounded trial under shared-host
load, not a universal latency ratio. The reference load now uses that owned model
instance with separate CPU/memory accounting; the old baseline used the shared
instance, so total load latency changes cannot be attributed solely to SQL.


The independent correction acceptance at `656ea27` leaves0 Critical, High,
Medium or playbook Important findings. Its320 extra SQL cases preserve complete
responses, and each broad60-document case makes60 eligibility checks regardless
of chunk count or Memoize. The worker probes pass15/15 with real admission and
HTTP doubles. One earlier stale probe was invalid and replaced by5/5 checks;
the probe-plan timestamp does not establish prospective freezing.

The [corrected r3 load](../../benchmarks/2026-11-01-lexical-eligibility/reference-load-r3-analysis.json)
on runtime `5395f36` completes420/420 foreground requests and13/13 synthetic
source windows. All163 actual model calls match their completions (135
foreground,28 background), with0 errors and no simultaneous HTTP inference.
Foreground demand starts with a background call in flight in both contended
phases; background pages contain one input and take at most7.802s.

Twelve real arrivals increase the growing backlog to13. The recorded
`draining40` phase has no arrivals but holds all13 while foreground demand
continues; it is not evidence of draining under load. After foreground ends,
the backlog reaches0 in116.66s. All723 resource samples are valid, at most17
DB connections are open and available host RAM stays above3.425GB. Sampled
model residency peaks at1.694GB; the2GiB `memory.peak` and624 hard-limit events
were already present before r3 and do not increase during it. No OOM occurs.
Owned model/API/database processes are stopped and their listeners absent.

Search total p95 is31.99s with20clients and60.04/62.47/61.63s in the three
40-client phases. These short bursts establish no agreed response-time target
or soak result. The full-load baseline used a different model instance and soft
budget; use the paired SQL A/B, not total-load differences, to attribute the
query repair. Raw aggregate hashes and an independent recomputation accompany
the public results; private source/result text and vectors are excluded.

The full-suite attempt on `656ea27` stopped near31% without a terminal result
and no pytest process remained. It is not a pass; its cause is unproven. A new
source-bound full suite is required before delivery. The maintainer latency
disposition and T06811/T06818 reconciliation remain open; Issue68/92 closure and
production rollout are separate from these measurements.


## Maintainer10-second target continuation

The maintainer requires successful search total p95 <=10seconds, including
queueing, with40 active clients and background extraction enabled on the same
4-vCPU/8-GiB reference. The existing r3 result fails that target;68/92 remain
open. Full4 at `0ec0ab1` was deliberately stopped before further runtime work:
exit-15 after1,604.03s, all1,330 tracked hashes and HEAD unchanged. It is not a
pass. The final implementation needs a new full-suite terminal result.

The [owned-copy diagnosis](../../benchmarks/2026-11-01-lexical-eligibility/latency-target-diagnosis.json)
uses no new model calls and exports aggregate timings/plans only. Full search
with a retained synthetic vector and inference explicitly stubbed takes about
5.5s; almost all of it is candidate SQL. The expanded reader plan spends
1,460.977ms of1,968.673ms in JIT; it is not the generic wrapper's full runtime.
A one-variable eight-unit JIT A/B reduces generic vector SQL from5.52–5.80s to
4.27–4.30s with complete response equality. A separate four-unit generic-plan
A/B, with JIT off in both arms, reduces eligibility calls from6,520 to166 and
SQL time from4.05–4.20s to0.99–1.07s by correlating the document gate to ordered
chunks. Full fields, score and order remain equal in all four units. These
single-request SQL observations are not the40-client latency acceptance.

The exact pre-target SQL fixture was frozen in `a6747cd` before runtime changes.
Both new real-reader regressions fail with600 checks versus a384-check ceiling;
only inference is substituted. They retain real gateway writes, HNSW, RLS,
truth checks and complete raw/contextual result comparisons. The additional
correction remains unpublished034;001..033 and the0.6.22 version are unchanged.
Fresh targeted tests, populated upgrade/restore, independent review and the
actual latency-target workload remain required.


The frozen generic-plan regression subsequently passed for both raw and contextual
vectors (2 passed, 64.49 s). Complete rows, order and scores match the pre-target
SQL on 600 synthetic documents; each corrected branch stays below the independent
384-check bound. The contextual plan retains HNSW when its source-hash predicate
stays inside the correlated document gate, before the 256-candidate limit. An
expanded-plan probe measured 225.187 ms versus 423.799 ms; this is synthetic SQL
cost, not the 40-client latency result. Forced sequential-scan and COALESCE arms
were diagnostic controls only and are absent from the implementation.

The affected selection then passed all 137 tests in 178.00 s (exit 0): vector
work and exact-response parity, lexical eligibility, contextual indexing and
the genuine populated 0.6.21 upgrade. All four retrieval functions restore the
caller's JIT and HNSW settings after normal return and a real statement
cancellation. The upgrade rehearses interruption, retry, original-row hashes,
pending work, the archived old reader, and independently restored source/target
backups. An initial selection typo named a nonexistent test file and ran zero
tests (exit 4); it is retained in the verification record. The 137-test command
is the corrected run. Full-suite and 40-client target acceptance remain open.

## Filtered-vector recall correction (unpublished034)

Independent review of `665d449` found a recall regression: when the nearest270
vectors fail access or truth gates, the ANN scan can stop before any of55 valid
farther documents. The committed regression `1e79b23` first reproduced0 instead
of the independently specified50 results (2 failures,44 deselected, exit1,
26.65s). The new matrix covers scope, domain, archive, time, stale source hashes
and model identity against an exact-sort control and literal document IDs.
A previous failed setup after the host restart and a timed-out oracle that
disabled every index are retained separately; neither is the regression red.

The correction uses function-local strict iterative scans when supported and
exact sorting if fewer than256 gated candidates are found. Capability absence
skips ANN and uses the exact path, retaining B-tree/GIN access. The simulated
legacy-capability and scan-cap selection passed5 tests (exit0,73.98s); this does
not certify an actual0.7 binary. The dense600-document384-check bound remains a
fixture-specific work regression, not a bound on selective exact fallback.
The final affected selection passed188 tests (exit0,600.51s), including all51
recall cases, dense-work/settings guards, lexical/contextual parity and the
genuine populated0.6.21 upgrade with interruption, retry and independent source/
target restores. All six SQL/test input hashes remained unchanged. Documentation
checks passed17 tests (exit0,0.91s). The independent review accepted recall
and found the non-superuser upgrade defect described below.
The cancellation check characterizes restoration after a real abort; PostgreSQL
rollback itself restores settings, so the successful-return check is the
independent discriminator for leaked function settings.

The [retained r4 result](../../benchmarks/2026-11-01-lexical-eligibility/reference-r4-failed-target.json)
completed1,400 foreground requests and13 source windows with0 model errors,
but its40-client search p95 remains22.08–22.48s. It fails the maintainer's10s
target and runs the rejected `665d449` retrieval code. Its target boolean also
omits the required correctness/drain/model-error conjunction. It cannot certify
Issue68/92, even though its supervisor ended with exit0 and its owned processes
were cleaned up. The next source-bound load must check all those gates together.


The next independent review found that the custom function setting required
superuser privileges during migration and archive restore. The limited-owner
regression was committed in `e4ea872` before the runtime repair: the genuine
0.6.21 source backup and restore succeeded, then034 failed with permission denied
for `rag.iterative_vectors` (1 failure, exit1,4.73s). An earlier setup failure
omitted the documented vector preload prerequisite and is retained as invalid
red evidence.

The repair uses the registered `hnsw.iterative_scan` setting and the installed
extension version. It grants no new privileges. Both populated upgrade tests
passed (exit0,18.95s), including a NOSUPERUSER/NOCREATEROLE/NOBYPASSRLS owner,
verified source/target backups and a separate restored target with preserved
row hashes, pending work and a successful search. The affected selection then
passed59 tests (exit0,504.61s). Its scope fixture now has300 allowed farther
documents and checks actual ANN work, covering continuation as well as exact
fallback. The empty restore template and vector preload are DBA-prepared
installation prerequisites; no production configuration changed. Actual
pgvector0.7, final independent correction review, the10s latency acceptance
and the final full suite remain unverified.


The independent N1 correction review accepted86d855d with0 C/H/M/Important.
It freshly repeated the limited-owner upgrade, source/target independent restores,
restored vector search and caller configuration preservation. Its ANN mutation
probe distinguished256 calls from300 forced-exact calls, and verified the version
guard and capped fallback. All four owned databases and the temporary role were
removed. The remaining playbook template-flag/link/public-schema Minor is corrected.
Coordinator logs predate the commit without captured input hashes; these fresh
independent probes cover the essential paths on the reviewed HEAD.

The [capacity/parser diagnosis](../../benchmarks/2026-11-01-lexical-eligibility/capacity-and-parser-diagnostics.json)
retains both completed diagnostic consumer arms. Their search p95 values remain
approximately24–28s, so no consumer-count change is selected. Both owned database
process trees exited and the model stopped, with no production change. The RLS
membership experiment was rolled back. The next selected repair computes stable
query-parser expressions once rather than per scanned chunk; its rollback-only
SQL probe preserved all response fields while reducing approximately1.07s to0.58s.
This is a single-query diagnostic with two repetitions, not40-client acceptance.


The query-parser regression was committed in74db11c before the runtime repair.
All eight cases failed on the expected128 or256 real parser calls (exit1,3.91s),
while their complete responses still matched the published SQL. Scalar parser
subqueries now compute the stable expression once per statement location. The
110-test affected selection passed (exit0,97.43s): the8 parser work guards,
100 existing lexical eligibility/parity cases and both genuine populated upgrade/
restore rehearsals, including the limited owner. SQL/test hashes were captured
during the run and remained identical at its end; they are not prior-start
snapshot proof. No RLS policies or operators changed. Independent review, the
source-bound load target and final full-suite acceptance remain open.


The parser independent review accepted46ed6f3 with0 findings. Fresh probes checked
100 full-response cases and every individual parser-expression mutation; actual
nested plans retain RLS and use one-loop initplans. The subsequent3-round owned
load still fails10s (search p95 approximately20.5–22.5s); its supervisor exit0
only proves completion/cleanup. The [context diagnosis](../../benchmarks/2026-11-01-lexical-eligibility/context-selection-diagnostics.json)
records this failed target and the remaining thematic cost. Further JIT-off
changes did not help and are not selected.

The frozen thematic SQL regression in f80587b failed8 cases (exit1,3.72s),
observing62/124 claim checks on unrelated originals. The selected reader query
materializes scoped matches before distinct-document truth checks. Its first,
unscoped prototype reduced calls but doubled reference latency, so that prototype
was rejected; the scoped variant preserves the full context hash and reduces
1974 lifecycle checks to932, approximately0.69→0.53s in two repetitions. The
117-test affected selection passed (exit0,68.69s), including current/history
source withdrawal and expiry, context/profile/lifecycle behavior and both actual
populated upgrade/restore rehearsals. Pre-run input hashes remained unchanged.
No authorization policy changed; the separate scope-policy experiment was rolled
back and is not adopted. Independent review, the final40-client target and the
final full suite remain open.

### Restored statistics and remaining model contention

The [controlled diagnosis](../../benchmarks/2026-11-01-lexical-eligibility/restored-statistics-capacity-diagnostics.json)
uses exact runtime5667ee7 on fresh owned copies of the same populated snapshot.
Restored tables initially lacked planner statistics. With autoanalysis disabled
only in the distinguishing experiment, explicit `ANALYZE` reduced the complete
context median from1.357s to0.457s. The profile-fingerprint query stopped compiling
107 JIT functions and fell from838ms to15ms. All six context packets had the same
SHA-256, and original document rows were unchanged. This explains a setup
confound in the newer capacity experiments; it does not invalidate the older
0.6.20 diagnosis or establish a product-wide JIT repair. Future restored-copy
measurements must record populated table statistics before measuring.

After explicit analysis, three-round idle40 experiments completed120 requests
per arm. Search p95 was16.425s with the two-consumer/default-model configuration,
13.501s with two consumers/two model threads, and9.805s with four consumers/two
model threads (39 searches each). These remain harness overrides, not deployed
settings. The separate three-phase repetition completed360/360 requests and
13/13 original-source windows, with117 foreground and28 background embedding
calls and0 model errors. Its search p95 was9.407s idle,12.931s with new arrivals,
and13.584s without new arrivals. Background HTTP calls lasted up to6.276s.
The10s requirement therefore remains unmet. These short bursts also lack actual
client delivery and scoped-result/citation verification under load; they are
not final acceptance.

The authorization-policy experiment was rolled back. It preserved the measured
context packet but reduced median context cost by only about50ms; no policy
change is selected. Individual connection/schema costs do not yet justify
pooling. The next design must address non-preemptible background model occupancy
and client observation delay while preserving full inputs, durable receipts,
truth/access checks, finite resource budgets and eventual source drain.

The [model-only overlap counter-test](../../benchmarks/2026-11-01-lexical-eligibility/native-model-parallel-diagnostic.json)
also rejects native two-slot parallelism as an assumed repair: with two CPU
threads, a short request started150ms after a complete3,215-character synthetic
original still waited5.600s with one configured slot and5.623s with two. Both returned
bit-identical vectors across arms. The owned diagnostic used a3GiB model cap,
had no OOM events, and stopped both sequential service runs; it did not invoke
the product, establish a deployment budget or test40 clients. A separate
foreground/background execution-lane proposal is under design review, not
implemented or accepted.


### E-LANE-1: isolated background model experiment (2026-11-01)

Source archive: `5667ee7eed39a33b49b74cef0cf6b792d67c859a`; planning HEAD
`ba9648d`. This is a harness experiment, not adopted runtime configuration or a
release. The prospective protocols, hashes and aggregate results are in
[model-lane-feasibility.json](../../benchmarks/2026-11-01-lexical-eligibility/model-lane-feasibility.json).

Stage A passed with an actual supervisor exit 0: ten complete-input pairs,
foreground p95 0.603 s, longest background 24.713 s. Default-thread, two-thread and
cross-daemon vectors were bit-identical; all ten model files were unchanged.
Minimum available host memory was 2,107,383,808bytes, with no swap delta, OOM or
memory-limit event. The first attempt failed before inference because PrivateTmp
hid its var/tmp home (226/NAMESPACE); that artifact is retained. The second attempt
changed only the owned diagnostic root, retaining the sandbox and thresholds.
All owned model and burner services stopped after the run.

Stage B completed with supervisor exit 0, but **failed its numerical gate**.
Three rounds per phase, 40 clients, four diagnostic consumers and two model threads
produced search total p95 9.908 s idle, 11.642 s growing and 11.485 s without further
arrivals. Search execution p95 exceeded idle by 0.528 s and 0.723 s in the background
phases, above the prospective 0.5 s margin. The background endpoint used a separate
SQL lock, 100% CPU quota and CPUWeight 1; the primary retained 350%. Each model had a
2 GiB limit and shared read-only pinned blobs. No product configuration changed.

All 360 foreground requests completed. All 13 complete original-source windows
were applied with matching text hashes and complete quote evidence. The 117 search
responses contained 351 hits: no empty response, warning, invalid citation
coordinate or ineligible returned document. All 117 foreground and 28 background
model calls completed without error; cache fallback and skipped-dedup counters
were zero. Minimum available memory was 2,622,685,184bytes; no swap delta, OOM,
limit event or sampler error occurred. The owned API/worker, PostgreSQL and both
model services stopped; production services and data were untouched.

The isolation candidate removes the measured model serialization but is not
sufficient for AC05. Further work must attribute PostgreSQL/API cost before a
repair is selected. This experiment used harness polling, wildcard readers and
a populated 024 diagnostic copy; it does not replace actual-client observation,
a restricted-reader result oracle, a real 0.6.21 upgrade/recovery rehearsal or the
final full suite. Issues 68 and 92 and tasks T06811/T06818 remain open.

### Source-permission plan reuse: source-bound B2 (2026-11-01)

The independent review accepted the bounded source-permission refactor at
`0a08785` with no findings. Its fresh probes included 19,200 original/new call
pairs across automatic, generic and custom plans, with no mismatches. The
populated 0.6.21 upgrade, interruption/retry and limited-owner independent restore
remain separate passing author evidence. This acceptance covers the SQL slice.

The [source-bound B2 result](../../benchmarks/2026-11-01-lexical-eligibility/source-permission-reference-B2.json)
verified all 188 archived source files before execution. It retained the earlier
prospective lane, four-consumer and two-thread harness settings. Supervisor exit
was 0, but search total p95 was 9.213 s idle, 10.646 s growing and 11.111 s without
new arrivals: the 10 s target still failed. All 360 foreground calls completed;
all 13 originals were applied. The 117 search responses had 351 checked hits and
no invalid citations, ineligible hits, empty responses or warnings. The 117
foreground and 27 background model calls had no errors; fallback and skipped-dedup
counters were zero. Resource and cleanup checks passed.

The background model consumed approximately 19.49 and 24.29 CPU seconds within
the sampled background phases. The next model-only experiment compares one and
two background threads under the same CPU quota, using complete synthetic input
and exact vector parity. It must show lower CPU work before another load trial.
No lane or thread setting is adopted by these experiments. Actual-client,
restricted-reader, final full-suite and AC05 acceptance remain open.

The [background-thread experiment E-EFF-1](../../benchmarks/2026-11-01-lexical-eligibility/background-thread-efficiency.json)
completed with supervisor exit 0. Five measured pairs per arm, after warmup,
used the same CPU quota and complete synthetic input. Median background CPU
was 22.084 s with two threads and 10.158 s with one. Measured vectors remained
bit-identical to the primary default-thread reference, and all model/resource
checks passed. The result justifies B3 with only the background thread count
changed. It does not prove final-input parity or the 40-client target.

The [source-bound B3 result and paired timing attribution](../../benchmarks/2026-11-01-lexical-eligibility/background-one-thread-reference-B3.json)
completed with supervisor exit 0 in 437.816 s. Compared with B2, only the
background request thread count changed from two to one. Search total p95 was
9.607 s idle, 10.621 s growing and 10.801 s without new arrivals; the last two
phases still failed the 10 s gate. Execution p95 exceeded idle by only 0.046 s
and 0.170 s. All 360 foreground calls and 13 complete originals finished. The
117 searches contained 351 checked hits, with zero citation, eligibility, source
hash or evidence errors. All 117 foreground and 28 background model calls
completed without error; fallback and skipped-dedup counters were zero. No
resource-limit, OOM, swap or sampler error occurred. All owned services stopped.

A subsequent read-only probe on the stopped diagnostic copy paired all 360
client durations with their stored request timestamps, then stopped its own
PostgreSQL again (exit 0). The search residual outside stored server wait and
execution had medians 2.146/1.668/1.617 s and p95 3.073/3.315/3.086 s. This
combines admission, retries, publication and result observation; it does not
locate their individual costs or measure CPU. The p95 of each request's stored
wait plus execution was 6.605/8.276/8.097 s. These are paired calculations;
separate percentiles must not be added or subtracted to attribute latency.

B3 still uses four wildcard principals, harness polling and the shared HTTP
thread pool. It does not prove the actual durable client's observation time,
restricted-reader result equality or a final-input model-parity matrix. Before
another load trial, review the admission, consumer and polling boundaries against
A2. Neither A2 adoption nor feature acceptance follows from B3; AC05, T06811,
T06818 and Issues 68/92 remain open.

## S06808: optional model lane and client polling

Implementation of the A2 minimum (T06823–T06827) on base `0587aed`, recorded
2026-11-01. Machine-readable summary:
[s06808-a2-implementation-evidence.json](../../benchmarks/2026-11-01-lexical-eligibility/s06808-a2-implementation-evidence.json).
All runs used an owned PostgreSQL17 copy on port55460, serially. Ollama, the
extraction provider and model identity were simulated; no model, provider,
remote host or production system was contacted.

Test-first record. Before any runtime edit, 116 new tests were run: 81 failed on
behavior (ignored settings, default route, shared lock, missing identity checks,
two fixed consumers, ignored `retry_after`, no pre-acknowledgement resend) and 35
characterizations passed (default payload, default background route and lock,
standalone and managed-profile routes, fallback polling, terminal and permanent
failures, negotiation and old synchronous calls, ContextVars, graceful shutdown).
Commit `fa154a8` freezes exactly those inputs. Four test-harness corrections
followed and are listed in commit `8252a3d`; none weakened an assertion.

Real-component rehearsal (`tests/service/test_model_lane_runtime.py`, 14 tests):
lane success through the gateway; digest swap on either daemon and a daemon
outage each keep the job pending with its attempt and accepted batch, write no
document or audit row, then apply without a second provider call; key removal
and restart apply on the primary daemon with the unchanged10s deadline; lane
and default workers share the singleton lock; a revoked key blocks before any
inference; the actual client completes through four consumers after the12/s
window and replays a lost acknowledgement as one queued request; the API refuses
to start above the pool reserve; and the PB06801 parity probe text accepts
identical doubles and rejects differing vectors or digests, and a primary
thread setting whose vectors differ from the unthreaded ones behind stored
chunks and reuse keys (the earlier probe text accepted that case; corrected in
self-review after the final affected run). Two mutations
(removing the post-inference identity check; turning an outage into a
best-effort save) each failed three tests.

Populated upgrade (`tests/service/test_lexical_upgrade.py`): genuine0.6.21 also
creates an accepted source window and a queued request. Interruption rolls
back034, the retry preserves every table hash, and source and target backups
restore independently. On the upgraded store the pending request blocks new
background pages, then completes on the consumer path; genuine0.6.21 worker
code is excluded by the singleton lock; a lane digest swap publishes nothing;
the default lane then applies the retained extraction. Original documents,
pins and the pending legacy job stay unchanged.

The final affected run on `eb0ca10` passed 432 tests (exit0, 306.9s; one
pre-existing Starlette deprecation warning). After the probe correction the
probe and documentation tests were rerun on the committed source. Remaining limits: no physical
model, cross-daemon vector parity for every actual input, resource budget,
actual40-client load, complete independent review or full suite was run here.
The PB06801 section is drafted, not independently reviewed or rehearsed on a
real daemon.

### S06808 review corrections and real-daemon L0/L1 rehearsal

The independent review at `20e2bd4` found no Critical, High or Medium code
findings, four Low findings and two Important playbook findings. Its real
client/queue/worker/SQL probes passed the derived success and recovery flows;
the model endpoints were loopback HTTP doubles. Of59 assertions,58 passed and
one diagnostic-code observation failed; the script exited1. It was not an
all-green probe run.

Corrections `41583cb` and `590400a` add the rendered-unit inputs and template,
pause extraction before testing, require renewed parity after model/runtime
updates, document reachable failure/rollback decisions and clarify daemon
aliases. The client now resets fallback waiting after a valid hint. The real
client regression failed first; all47 client tests then passed. The final
seven-file selection on `590400a` passed152 tests in52.54s, exit0, including
populated0.6.21 upgrade/retry and independently restored source/target backups.
All386 Python/SQL input hashes stayed unchanged during that selection.

The [physical rehearsal record](../../benchmarks/2026-11-01-lexical-eligibility/optional-lane-playbook-rehearsal.json)
binds L0/L1 to `590400a` on the owned4-vCPU/8-GiB Hetzner copy. The printed
discovery and three-input parity snippets ran against two real Ollama0.31.2
daemons using the new unit template: three vectors matched exactly across
unthreaded primary, two-thread primary and one-thread background requests.
The daemon journals confirm the requested thread settings. Fresh model-cgroup
peaks were1,776,336,896 and1,769,013,248 bytes, with no hard-limit or OOM events;
available host memory after the probe was2,864,209,920 bytes. All10 model files
were byte-identical before/after and both owned units stopped with closed ports.
The first probe is retained: parity passed but its observer incorrectly
expected a process flag; the corrected observer uses Ollama's thread journal.

This is a partial rehearsal, not delivery acceptance. L2/L3 with real model
daemons and actual API/worker restarts, the complete acceptance-input parity
matrix,40-client scoped/correct lossless load below11s and final full suite
remain open. Low080–084
are recorded in [Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6563006840).

The correction review on `4828f1a` accepted the client fix and the earlier
playbook findings, with no Critical, High or Medium code finding. Its own
eight client cases passed, including a failing control against the old client.
It found one new Important playbook gap: early setup failures and a stopped
worker after recovery had no explicit restart path. The current correction
adds a shared early-exit path, requires an active worker after recovery or
rollback, and retains an explicit pause when the primary model is unverified.
It also checks resident primary memory, maps listener ports to unit PIDs,
guards installation before writing a unit and renews unit-input discovery
after updates. These are documentation corrections; L2/L3 physical rehearsal
and focused content recheck are still open. The focused documentation check
passed17 tests (exit0,0.45s); no runtime, test or migration file changed.

The focused content review on `f4b1afe` accepted PB-R01–05 and the as-built
update. It found a conflicting update/rollback branch (PB-R06, Important):
rollback could restart extraction on an unverified changed primary. The next
correction makes verified primary identity/runtime a precondition for every
L3 worker-start command. Its safe failure remains a recorded outage until a
verified primary is restored. PB-R07 (Minor) is addressed by a bounded
synthetic primary warm-up, normalized tag lookup and memory reading immediately
before starting the second daemon. The new warm-up has not been physically
rehearsed. Documentation tests alone do not exercise these decisions; focused
content acceptance remains open.


### Resource-workspace correction: diagnostic only

Full-suite r4 on `57b1f51` passed2508 tests with1 skip and the known Starlette
warning (exit0,2717.44s). The observed original managed-ANN query took0.352s.
A separate fresh corpus after explicit `ANALYZE` passed its original regression
without changing the2s timeout; its query took0.226s. The earlier full-r3 ANN
failure remains unreproduced, not evidence of a repaired product defect.

The owned diagnostic `6b63961b9b80` completed with controller/supervisor exit0
and52 controller checks. After a deliberately long synthetic primary input,
the fixed unload/check path preserved the daemon PID and released its runner.
With API and copied PG active, worker paused and BG absent, available memory
was4,466,782,208 bytes; the next pre-BG check measured4,444,504,064 bytes.
With both models resident, including long-input BG workspace, it measured
2,807,529,472 bytes. Both model identities/reference vectors matched; all six
owned units were inactive after cleanup, and model-store/snapshot hashes were
unchanged. Production services were not changed. This is bounded feasibility,
not40-client latency, full parity, L2/L3 or feature acceptance.

The preceding diagnostic `44eb28f98d60` stopped before capacity measurement:
the kit compared JSON-encoded vector hashes with its float64-little-endian
encoding. The actual vectors matched the retained full-parity reference.
Two regression assertions failed before the correction;49 offline kit tests
passed afterward. Both diagnostic reports are retained. After this measurement, the maintainer
authorized deletion of disposable test files while keeping active test DBs.
The old physical runs' stopped PG copies were removed; their compact reports,
protocols and synthetic vector references remain available. The source dump
and live test DBs were preserved.

The new L1/L2/L3 maintenance sections and kit reset points need independent
review and a fresh frozen full physical run. Earlier partial rehearsals do
not establish this revised procedure. The4GiB/2GiB floors and strict search
p95 below11s remain unchanged. The resource claim is bounded to the frozen
foreground queries of at most73 characters; longer production inputs are
not limited by this release and can enlarge the primary workspace.


### Focused resource-kit correction before refreeze

The fixed-unload review accepted the resource mechanism and prior ANN/full-suite
evidence, but withheld a new physical run for two kit defects. Three lane-enabled
rehearsal worker starts lacked their own reset/both-resident check, and the1s
sampler recursively inventoried the host inside the client-measurement process.
The corrected kit declares and tests all three reset points; single-primary
key-removal recovery keeps its separate identity check. Recursive inventories
remain at memory guards and phase boundaries. Periodic samples read resolved
paths, retain idle production model units and nested PostgreSQL, and report
their own elapsed time. Memory floors and sampling interval are unchanged.

The first focused tests reproduced the missing worker guards and expensive
sampler path. The final offline kit run passed53 tests. A local read-only
characterization (10 samples) measured medians of0.107s for the full inventory
and0.0058s for the bounded sample; this is not target-host latency evidence.
The bounded correction still needs independent acceptance before refreeze.
The next physical run must prove parity, L2/L3, both memory gates, all40-client
phases below11s and all13 originals applied. No such pass is claimed here.
