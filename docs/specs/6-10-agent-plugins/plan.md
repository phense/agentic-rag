#6.10 technical plan

Owner: coordinator, sequential cohesive slices. Base07f989f. Same already-isolated
checkout, new feat/agent-plugins-68 branch; PR stacks on76, never merges it implicitly.

1. Add024 queue/control tables and scoped guards. Owner-side admission/claim/status
   helpers never return stored credentials or foreign rows. Finite TTL and timestamped
   idempotency envelopes prevent replay after bounded tombstone deletion. Dispatch
   in the API lifespan with two fixed consumers, not a process per session.
2. Queue canonical mutations in one deferred-commit connection group. Existing
   gateway commit calls still revalidate authority, but final physical commit
   includes the result/terminal receipt. Context managers cannot prematurely close
   or commit that transaction. Read requests use existing RLS connections. Per-job
   database execution pins fence orphan recovery and completion after lease loss.
3. Add negotiated client requests and persisted local handles/outbox to existing
   private SQLite spool; a wait timeout returns a useful handle, never cancellation.
   Preserve opt-in/legacy synchronous transport. Plugin MCP adds bounded status/
   cancel tools with the original read-only/main distinction.
4. Record foreground activity with leases and gate new background work/model pages.
   Shared embedding admission serializes calls with foreground preference;
   background pages are single-input with a finite request deadline. Active source
   extraction can retain accepted output and retry application without new inference.
5. Package actual host manifests plus common Python lifecycle/MCP bridge. Keep
   existing host-specific parsers/installers; Gemini CLI gets its own documented
   JSON transcript/event adapter, not agy's camelCase schema. Native package
   files use ownership hashes and conflict-safe update/uninstall records.

Compatibility:0.6.11/schema024; known sources018–024, explicit023→024 rehearsal.
Old source jobs, queue vocabulary and embeddings remain. Do not downgrade DDL;
code rollback can leave additive024 in place and use legacy synchronous access.
Stop only owned test services for crash probes. Public artifacts contain aggregates.

System playbook PB06801 docs/playbooks/agent-plugins.md: package/config/enroll/disable,
queue full/offline/accepted wait/cancel/expiry, source retention and staged update.
Coordinator authors/reviews/rehearses during slice3. Development tests use isolated
PG55458 and owned databases, as in DB05801. No production migration required.

Testing: meaningful red behavior tests before each slice, real SQL/HTTP/transactions;
mock inference only at provider boundaries. Bundle1–3 major full-range reviews/test
rounds; independent Sol high, sparse use. Upgrade original-row/ACL comparisons,
40-client queue benchmark, compaction traces and full Python/Node before PR.

## RAG-068-A1: native origin correction and remaining acceptance

Continue the merged implementation from29a2f44 (0.6.20/schema032) on the
existing isolated acceptance branch; preserve the old RAG-068 run and evidence.
The actual Claude2.1.314 manual probe revealed `isCompactSummary:true` inside a
`user` message. Treat outer conversation type and generated-origin flags as
authoritative before prose can become source evidence. Generated summaries,
metadata and API request mirrors do not enter extraction or continuity digests.
Raw recordings and historical normalized lengths remain available to advance
old partial `mw1` cursors without rewinding or shifting subsequent originals.

Use existing source trust rather than rewriting historical roles or documents:
an operator previews a bounded complete recording and explicit local/service
namespace, then applies its exact SHA-256 with writers stopped. The audited
source gateway atomically marks proven generated source identities removed,
including orphan tombstones for pending old batches. New inference filters
those fragments out of old staged windows. Immutable accepted batches keep
their existing replay identity and cannot restore removed source trust. This
is per-recording evidence, never a claim to have censused unavailable histories.
Review M1 requires additive migration033: only a replacement supported solely
by proven generated-origin tombstones loses its suppressive effect. Ordinary
refutation/removal/expiry and genuinely supported replacement keep the existing
no-revival rule. Inactive-source replay is review-only, with no new edge. The
DB-backed preview must cover retained windows, accepted batches and known sources;
remote export must separately cover pending SQLite outbox windows. The target
release0.6.21 still needs the populated upgrade,
backup/restore, independent review and final suite gates in T06812..14.

Native observations remain separate from adapter tests. Manual Claude compact
and native restart/resume retained all three frozen identifiers. After two
failed artificial-threshold attempts, the frozen multi-turn probe emitted a
native automatic summary plus Pre/PostCompact and SessionStart compact, then
recalled3/3 identifiers. The separate same-partition offline/reconnect probe
retained4/4 originals in2 windows after a lost ACK, with0 pending. Other native
hosts remain explicitly unobserved; Issues12–14 stay open.

The reference VM was read-only verified as4 CPUs and8,134,742,016 bytes RAM.
The owned copy completed140/140 foreground calls and8/8 background windows.
High search execution time and head-of-line queue waiting need a bounded SQL
and restored-index/statistics diagnosis (M-ACC1); the8-window phase is a fixed
initial backlog, not continuous growth. No numerical SLA has been agreed.
Keep performance acceptance open until diagnosis and independent disposition.
Use no production service, credentials or data changes to manufacture acceptance.
All production cutover gates remain.


## A2: isolate admitted background inference (Issue92, design gate)

Status: implementation plan after the post-B3 independent design review. Runtime
0a08785 is unchanged; B3 meets the revised numerical target as a diagnostic shim.
This
amendment supersedes the fixed-consumer/shared-runner decisions above only when
its optional configuration is selected. The revised strictly <11s AC05 target and4-vCPU/8-GiB
reference remain binding; no consumer, thread or model-lane setting is adopted
by a diagnostic result alone. Owner: coordinator, one cohesive implementation
slice after the experiment and architecture gate. Model and originals stay intact.

The post-B3 review accepts implementation of the minimum below. No further
performance experiment or optimization is required solely to reach the former
10s target. B3's original protocol and failed 10s gate remain historical evidence.

### Evidence and decision

The independent model-admission review on6ffeb3d traces the two serial boundaries
to `service/priority.py:model_slot` and the Ollama runner. The controlled reports
are [restored statistics and capacity](../../benchmarks/2026-11-01-lexical-eligibility/restored-statistics-capacity-diagnostics.json)
and [native parallelism](../../benchmarks/2026-11-01-lexical-eligibility/native-model-parallel-diagnostic.json).
With analyzed copies, four diagnostic consumers and two model threads give
idle search p959.407/9.805s but12.931/13.584s in background phases. Native
parallelism2 does not let the short request bypass a full input. One optional
background daemon is the minimum candidate addressing that observation. The
existing configured endpoint remains the default and foreground endpoint.

The stated headroom is an observed risk, not proof of a latency floor or of
insufficiency. MAD-01..03 are conditional High design obligations for the new
lane, not newly observed defects in an installation without that lane. They
must be resolved in code and tests before PR readiness. MAD-04..08 require client,
resource and runtime evidence. MAD-09/10 are acceptance counters and recovery
limits; do not create a duplicate Low issue merely for unimplemented-design risks.

### Contracts and ownership

- `config.py`, `embed.py`, `service/priority.py`: optional background URL and a
  finite10..60s timeout, optional bounded model thread count. Without lane/thread
  settings, keep existing request JSON, endpoint, admission lock, ten-second
  background deadline and response semantics. Only fenced central legacy-Ollama
  background work uses the new lane. Standalone, foreground and managed embedding
  profiles retain their old routing; managed calls explicitly retain shared
  admission. A separate legacy-background lock permits at most one background
  inference alongside one foreground inference. Keep foreground preference for
  starting every new background page/job, finite waits and existing worker pins.
  Configuration keys: `[ollama] background_url`, `background_timeout_seconds`
  (10..60, default60 for an enabled lane), `num_thread` and
  `background_num_thread` (optional integers1..8), and `[service] request_consumers`
  (integer1..4, default2). Thread keys are omitted from HTTP JSON when unset.
  Background-only settings require the lane; reject malformed or credentialed
  URLs. The reference uses primary threads2, background threads1 and timeout60,
  matching B3. Managed profiles keep their own provider/thread configuration.
- `query_cache.py`, `embedding_reuse.py`, `embed.py`: verify both endpoint tags and
  immutable digests before and after routed inference, validate dimension and
  vector shape, and refuse unknown/mismatched identity before persistence. Reuse
  keys keep the primary endpoint/model identity only after bitwise parity is
  proven. Never silently relabel another daemon's vectors. Foreground query-cache
  semantics remain unchanged. A background-lane timeout/unavailability/identity
  failure raises attempt-preserving ResourcePressure, never a best-effort save
  with missing vectors. Accepted extraction output remains replayable without a
  new provider call. Count timeouts, fallback and dedup skips in the acceptance
  harness without disclosing inputs.
- `service/requests.py`: configurable bounded consumer count, default2, reference4.
  Keep `asyncio.to_thread` and its ContextVar propagation. Reject an explicit
  count above half the default CPython executor capacity at API startup (capacity
  `min(32, effective_cpu_count+4)`, using `os.process_cpu_count` when available).
  This reserves at least half its workers for HTTP/control/trace work; four are
  allowed on the reference's eight-worker pool. The supported API uses that
  default pool; document the reserve requirement for a custom ASGI executor.
  No own executor, pool resizing, authorization change or concurrency sweep is
  selected. Never share live connections. Preserve shutdown's execution-pin
  guarantee: wait for finite calls; do not abandon a live gateway and start a
  replacement execution. More consumers do not establish more CPU capacity.
- `service/client.py`: honor finite, bounded existing `retry_after` hints with
  jitter and the caller's remaining deadline. After ACK, use a finite numeric
  hint clamped to at most8s and at least `service_poll_seconds`, plus0..25% jitter;
  an explicitly larger configured poll interval remains the lower bound. Invalid,
  missing, boolean or non-finite hints retain bounded exponential fallback.
  Before ACK, retry only transient contention/timeouts within the caller's
  deadline, using0.3s plus0..25% jitter and the SAME durable envelope/idempotency
  key. This includes capacity/write-capacity/rate contention429,408 and ambiguous
  transport timeout/unavailability after discovery. Do not retry permanent4xx,
  invalid receipts/responses, legacy synchronous calls or negotiation failure.
  Preserve offline handles, lost-ACK reconciliation, cancellation and terminal
  errors. At deadline return the same pending handle, never success. Clamp every
  sleep and HTTP timeout to the remaining deadline.
  All deployed queued-tools servers already send `retry_after:1`; client-first
  rollout therefore changes polling to approximately1Hz on old servers too.
  Retain the12/s per-namespace window, four control slots, auth and budgets.
  Missing-hint fallback remains defensive compatibility, not evidence that
  deployed old servers keep the old schedule. No new wire field or long-poll.
- Configuration reference, central-service guide and PB06801: describe the
  opt-in daemon, read-only pinned blobs, finite per-lane/global CPU and memory,
  old/new coexistence, verified startup and a key-removal/restart recovery path.
  Deliver these before lane activation; no production activation in this work.

### E-LANE-1: falsify before implementation

The original experiment below froze the then-current <=10s boundary. Preserve
that protocol and its failed numerical gates. The maintainer subsequently
changed AC05 to strictly <11s; future acceptance uses the new boundary, with a
separate reassessment of existing observations. B3 meets the revised numerical
boundary but remains a diagnostic shim, not final-runtime or actual-client
acceptance. See [the target disposition](../../benchmarks/2026-11-01-lexical-eligibility/latency-target-11s-disposition.json).

Freeze controller/protocol hashes before execution. All processes are owned
copies on the same reference. Never send copied private inputs to any model.
A: use the complete3215/49-character synthetic model inputs with150ms offset,
10 repetitions, both runners at2 threads, plus three bounded default-weight CPU
burners approximating2.5 cores of non-model work. Compare default-thread versus
2-thread vectors, then require cross-daemon bit identity. Foreground uses the
unchanged owned350%/2GiB envelope; background uses CPUWeight1, CPUQuota100%,
parallel1/one model,2GiB and shared read-only blobs. Require foreground p95<=1s,
every background call<=60s, no model/OOM/memory-limit event, host MemAvailable
>=1.5GiB and unchanged blob hashes. Abort B on failure; retain the failed evidence.
B: only after A passes, use the fresh populated owned024->034 copy, explicit
ANALYZE, unchanged40-client three-phase mixed workload and13 originals. A hashed
harness shim changes only fenced legacy routing/lock/deadline; consumers4 and
threads2 remain declared diagnostic overrides. Require each search total p95<=10s
and background-phase execution p95<=idle+0.5s, complete scoped results/citations,
zero model failures/fallbacks/dedup skips/timeouts,13/13 original-source hashes
applied, eventual drain, no swap/OOM and the recorded CPU/PSS/memory envelope.
An experiment pass proves feasibility only; final acceptance needs implemented
source, the actual client, enough samples and all original correctness gates.

### Upgrade and recovery gates before delivery

No new DDL is planned;034 and its existing source0.6.21/schema033 verified upgrade
remain mandatory. Rehearse the exact final runtime on populated0.6.21, not only
the024 diagnostic snapshot: interruption/retry, source and target independently
restored backups, original/user/domain/ACL/job/receipt history unchanged.
Prepare the optional daemon before enabling a key, verify identity/parity and
resources, deploy code with lane unset, pause extraction and drain the old call,
then configure/restart and verify the actual route. Mixed old/new workers must
still obey OWNER_LOCK and execution pins. Removing lane/thread/consumer settings
and restarting restores single-lane operation without deleting jobs or caches.
Do not rewrite the migration ledger or claim a schema downgrade.

Derived success/recovery cases, required before final review: default routing/
request/lock compatibility; real-client completed result within AC05; old-server
poll fallback; rate-limited durable handle retained; kill background daemon;
digest swap during inference; API/worker restart; config rollback; old/new
worker exclusion; lost ACK/offline replay; authority revocation before commit.
Use existing FR04/05 audit and result-publication checks in every applicable case.

### Fixed model-workspace maintenance before acceptance

The measured resource failure came from retained anonymous model workspace
created by setup/parity/seed and rollback inputs. The selected correction is
model unload through `/api/embed` with empty input and `keep_alive:0`, not a
daemon restart or a smaller memory floor. Keep the API and database resident
and pause the worker. Prove the model is absent, its old runner exited and
anonymous memory returned within128MiB of the cold-daemon baseline; preserve
the daemon PID. Warm twice with FG2/BG1, the pinned synthetic reference hash,
a future `/api/ps` expiry and stable runner PID.

Freeze unconditional primary reset points: early `feasibility`, each
`before-background-preflight`/`after-daemon-stop`/`final` pre-BG guard, and
`before-load`. Run all three primary parity arms before the first BG start;
keep all454 inputs/four arms. The actual-state feasibility gate runs before
that expensive preflight with PG/API active, worker paused and BG absent.
Require4GiB available immediately before each BG start. Gate A after parity
and gate B immediately before load require both models resident and2GiB
available. Keep the BG long-input history. No reset during load or drain.
A failed guard terminates the run; no adaptive retry, threshold reduction,
production stop or removal of PG/API to manufacture capacity.

Record recursive cgroup service/scope/slice inventories, anon/file/shmem,
expanded host meminfo, raw model residency and runner PIDs. Record unrelated
on-demand model loads at every guard rather than excluding them. Do not run
this physical gate concurrently with the full test suite. Rename a parity-end
sample `after_parity`; only an observed resident check establishes residency.

The bounded diagnostic on the new path is not acceptance and skips full
parity/extraction/load. After it passes, independently review the kit and
procedure delta, refreeze and execute one fresh full acceptance run. Claims
cover the frozen foreground queries (maximum73 characters), not unrestricted
production input lengths or uninterrupted maintenance. No product query limit
is introduced. T06821/T06828 stay open until the full final run passes.

### Final-runtime acceptance after B3

PB3-01..05 are implementation/acceptance obligations, not new defects in the
accepted single-lane runtime. B3's9.607/10.621/10.801s satisfies the revised
strict<11s numerical boundary only. The measured background-thread reduction
justifies background threads1; preserve complete inputs and require exact
vector parity for every actual synthetic inference input before final acceptance.

T06821 uses the product `RemoteClient.invoke`,40 instances with separate spool
directories, normal30s tool deadlines, four principals with ten clients each,
the same metadata/context/search mix, distinct queries and13 original windows.
Freeze phase sizes, principal/scope mapping and expected result/citation checks
before execution. Include real restricted readers and an independent result
oracle; record this mapping change from the wildcard-only B3 rather than calling
the workloads identical. No successful `waiting` outcome or fallback is allowed.

Passive instrumentation records per-attempt time/method/path class/status/error
code and pre/post-ACK state, request ACK/publication-commit/terminal-observation
times, round index, phase rejection counters, trace drops and default-executor
queue delay by work type. No raw credentials or private excerpts are exported.
Measure each contended40-client phase independently with strict `<11`, preserve
resource/model identity checks and full eventual drain. Stop on the first failed
or invalid gate, retain evidence and diagnose it; do not tune between phases or
repeat a near miss until it passes. No additional pre-implementation attribution
experiment or dedicated executor is selected.


### T06820 refinement: source-permission plan work

E-LANE-1 A passed; B preserved all originals and returned citations but remained
above 10 s. The fresh analyzed cost attribution records PostgreSQL 75.50 CPU s
and API 7.25 CPU s for 120 requests. The existing SQL SECURITY DEFINER helper
`rag_service_source_write(text,text)` repeatedly plans its unchanged predicate.
The rolled-back counterfactual reduced 1,071 plans to 6 and retained all 18 full
result packet hashes. These are bounded diagnostics, not target acceptance.
Evidence: [non-model-cost-attribution.json](../../benchmarks/2026-11-01-lexical-eligibility/non-model-cost-attribution.json).

Within T06820, characterize the original helper before and after wrapping its
entire SELECT in a static PLpgSQL RETURN. Keep signature, three-valued NULL
semantics, STABLE, SECURITY DEFINER, fixed search_path, owner and grants. Reuse
execution plans only; reevaluate namespace/domain/project/write conditions on
every call. Recheck the same connection after authorization settings and source
dependents change. Keep published 001..033 unchanged; append the replacement to
unpublished 034. Require the populated source upgrade and limited-owner independent
restore again. This localized refactor adds no configuration or new admission
lane and does not adopt A2's conditional consumer/thread/endpoint settings.
