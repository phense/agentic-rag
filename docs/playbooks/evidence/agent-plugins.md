---
title: PB06801 review and rehearsal evidence
type: reference
audience: administrators
version: 0.6.21
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
