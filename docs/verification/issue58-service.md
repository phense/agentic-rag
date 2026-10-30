# Issue58 service verification

Status: implementation verification passed on the reference-host copy; production cutover and complete Issue58 rollout remain open. Roadmap6.0 uses one implementation PR, patch0.6.10. The user authorized merges74/56/57; those are complete. A future implementation merge and any production move remain separate approvals.

## Dependency baseline

- Base after all three merges: `979c334d9ed7b93e7ba2e015e8ed281998ba1288` (0.6.9).
- MCP update56:82 compatibility tests passed in4.98s and independent review found no defects; actual stdio handshake/18RW/10RO registration verified.
- certifi update57:82 compatibility tests passed in10.10s, SSL loaded120 CA certificates, independent dependency review found no defects.
- Full pre-feature suite on MCP update:1330 passed,1 skipped in948.26s; isolated PostgreSQL17 cluster, no private source corpus/provider input. The slow4096-chunk fixture is included. Earlier runs aborted for test-cluster connection/setup errors are not counted as passing.
- GitHub reported zero open Dependabot alerts after the merges on2026-10-29.

## S058-01: authorization and transport

New tests exercise actual SQL/engine calls, HTTP and stateless remote MCP with four machine identities, two knowledge users and a separate human administrator. They cover protocol mismatch, RO registration/mutation denial, domain/project counts, graph/guessed-ID isolation, credential reload, password login/logout, transport/body limits, scoped research subprocess and authenticated audit actor.

The SQL scope test commits between reads to prove authorization survives gateways that commit internally. Direct calls to security-definer chunk/context writers cannot modify a foreign document. The source-revocation regression first failed against a deliberately restored namespace-only policy (`DID NOT RAISE`), then passed with the current-project evidence check; earlier source ownership cannot bypass revoked project access.

Targeted command (2026-10-29, isolated cluster on port55458):

```sh
PGPORT=55458 .venv/bin/python -m pytest -q tests/service \
  tests/test_scope.py::test_additive_legacy_migration_and_reader_privileges \
  tests/test_entities.py::test_candidate_on_populated017_retains_legacy_reads_writes_and_fallback \
  tests/test_domain_upgrade.py tests/test_docs_continuity.py
```

Result:32 passed in19.33s, one upstream Starlette TestClient/httpx deprecation warning. These tests include populated legacy schema upgrade/strict-restore checks. The broader selected regression initially passed259 tests and failed two literal expected-migration lists; those lists were updated to include021/022 and both cases passed in the command above. The subsequent broader acceptance run passed264 tests in122.80s (same warning).

The first complete staged-diff review found two High and three Medium defects, plus LOW-001. All six were independently reproduced by new tests: the uncorrected implementation failed all6 in4.20s. Corrections require old-row write authority as well as new-row authority for every service policy with a write check, qualify privileged relations and place `pg_temp` last, restrict definer execution, preserve the authenticated audit actor while mapping edge origin to `manual`, permit unresolved references only while no inaccessible target exists, bound request-body reception to5s, and bind window/stream owner and project through a composite FK. The six regression tests then passed in2.91s. LOW-001 is retained in [Issue75](https://github.com/phense/agentic-rag/issues/75).

Round2 repeats the selected acceptance command below and an independent review of the complete updated staged diff. The selected acceptance passed270 tests in127.63s (one upstream warning); independent review round2 has completed, as recorded below.

```sh
PGPORT=55458 .venv/bin/python -m pytest -q tests/service \
  tests/test_mcp_server.py tests/test_roles.py tests/test_scope.py \
  tests/test_pins.py tests/test_validity.py tests/test_entities.py \
  tests/test_query_cache.py tests/test_research.py tests/test_context_gate.py \
  tests/test_project_context.py tests/test_domain_upgrade.py tests/test_docs_continuity.py
```

## S058-01 review round2 corrections

Independent review round2 confirmed all six initial findings resolved, then found
H3 (service accepted schema020 without authorization RLS), M6 (checkpoint fallback
and rendering could probe service-host paths), M7 (operator backup diagnostics
entered knowledge context) and LOW-002 (ambiguous human/machine audit actor).

The new schema gate runs at startup and on every scoped connection. It checks the
required migration set, enabled RLS/policies on all22 scoped tables, restrictive
old-row write guards and non-superuser/non-bypass/non-owner reader/writer roles.
A service start never applies migrations automatically. Missing protection raises
`incompatible_service_schema`; engine calls report503 without business queries.

Remote checkpoint lookup/rendering now uses logical project identity and retains
scoped SQL lookup. Backup/provider warnings expose stable codes rather than local
operator text. Human and machine actors now have distinct type components;
LOW-002 is retained in Issue75 and LOW-001 was independently confirmed resolved.

The schema/diagnostic/actor regressions first failed on the uncorrected code. The
path regression was rerun with the valid public tool signature against the indexed
old hook implementation and failed with an observed foreign-path capture in2.20s;
the earlier attempt used an invalid argument and is not evidence for M6. The
corrected service suite passed23 tests in12.21s. A broader round3 command also adds
`tests/test_hook_session_start.py` to the preceding acceptance selection; its result
was308 passed in135.94s (one upstream warning); the final independent S1 review is pending. An initial invocation misspelled
that filename and collected no tests; it is not counted as a passing run.

## Current completion boundary

S1/S2 source, transport, hooks and worker behavior and S3 operator interfaces are implemented. Final complete-range review, derived integration scenarios and full-suite acceptance remain outstanding. Follow `docs/specs/6-0-central-service/tasks.md`. Hardware-class performance and production migration remain unperformed. Independent-store consolidation is inventoried and safely refused without reviewed mappings; no automatic merge is claimed.

### Round3 final targeted checks

The checkpoint exception branch also echoed operator text; its new regression
failed before the status-code fix (1failed in8.36s). The final combined command
`PGPORT=55458 .venv/bin/python -m pytest -q tests/service tests/test_hook_session_start.py`
passed58 tests in27.44s, one upstream warning. It includes both missing-checkpoint
fallback and existing-checkpoint rendering without filesystem capture, plus
operator backup/provider/exception diagnostics and typed actor identity.

An earlier invocation of that final targeted selection hit a pre-existing test
isolation race: two SessionStart tests mocked maintenance but not the independent
profile-refresh worker launch. A detached test-database worker raced the next
fixture's TRUNCATE (DeadlockDetected), then stale profile state affected an
assertion. Both tests now stub the launch; the explicit launch/failure tests
still exercise the real helper with mocked Popen. LOW-003 is retained in Issue75.
The child inherited the isolated database port; production backup files were
unchanged, and incidental output went to the existing worker log. No production
schema, corpus, deployment or runtime version was changed.

## S058-02 input, client and worker verification

The client/worker slice adds a protected durable SQLite spool, strict source-window
acceptance and owned receipts, checkpoint upload/fallback, an HTTP connector,
client-mode lifecycle/stdio adapters and a supervised serial database worker.
The existing mining batch and audited gateway remain the application path.
Deferred embeddings carry their originating credential reference and revalidate
before inference/application. Source windows retain exact line/hash identities;
the server never opens a client transcript path.

Targeted red/green probes cover lost ACK after commit, source removal after durable
capture, restart/replay, private session/project caches, offline manual/automatic
compaction, RO/foreign receipt access, cursor conflict, revoked and mid-extraction
revoked jobs, provider outage, uppercase receipt cancellation against an active
worker lock and a crash after the knowledge commit. The latter replays the accepted
batch without a second provider call. Snapshot compaction initially returned the
boolean from `mark_compacted` instead of the checkpoint; the existing API test
caught this and now passes. A separate regression rejects service startup when
the authenticated audit trigger is disabled.

The S1 M8 reproduction failed before the fix (one failure in1.28s). Stateless MCP
now rejects non-POST requests before semaphore acquisition;25 service tests passed
in14.48s. Its independent confirmation belongs to this S2 review, avoiding a fourth
S1 major review round. S2 review base is the reviewed S1 Git tree
`c1c2472612e5c089c9fc6c84bb9d574ebbdd9483`.

S2 major acceptance round1:211 passed,6 failed in62.05s. Two internal scope tests
needed the credential-policy fixture required for deferred jobs. Four existing
worker tests failed only in the combined run. Round2:216 passed,4 failed in70.54s;
the same worker assertions passed independently (29 worker tests in13.52s).
An Antigravity SessionStart test still launched a real detached worker against the
isolated port; its cross-host fence suppressed the later test workers. Its launch
is now mocked, extending LOW-003. Incidental child log output recorded a missing
test checkpoint at18:07/18:10UTC, never a production data or backup change.

S2 major round3 passed **229 tests in68.91s**, Exit0, with only the existing
Starlette/httpx deprecation warning:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55458 \
  .venv/bin/python -m pytest -q tests/service tests/test_hooks_common.py \
  tests/test_hook_stop.py tests/test_hook_session_end.py \
  tests/test_hook_prompt_recall.py tests/test_hook_pre_compact.py \
  tests/test_hook_post_compact.py tests/test_hook_session_start.py \
  tests/test_hook_agy.py tests/test_agy_hooks.py tests/test_opencode_hooks.py \
  tests/test_mcp_server.py tests/test_worker.py tests/test_mining.py \
  tests/test_mining_resume.py tests/test_mining_window.py
```

Full command output: local scratch `service-s2-major-round3.log`; no production
provider calls or rollout. Independent S2 review, S3 upgrade/restore/cutover
rehearsal, operator tooling, measurements and final full-suite convergence remain
pending. These checks do not establish Issue58 completion.


## S058-02 review1 corrections and resource rehearsal

Independent review1 checked all37 S2 files against the S1 review tree, confirmed
M8 and the extra LOW-003 AGY mock, then reported two High and one Medium findings.
Fresh probes failed4 tests: failure cleanup resurrected cancellation, keeper
connection loss allowed simultaneous old/replacement inference, and cancellation
after the mining commit falsely claimed rollback. Terminal-state guards, an
applied-batch check under the window lock, and shared execution pins plus checked
keeper authority correct these paths. Source/runner/legacy-worker tests passed40
in28.94s. Additional parent-connection loss, storage-admission and finite logging
regressions passed21 in32.42s; accepted-batch replay after keeper loss separately
passed1 in2.33s without a second provider call. Provider functions were mocked.
The corrected full slice still requires independent review2.

The real-uvicorn rehearsal used one API process, no model calls, synthetic owned
PostgreSQL17 storage on55458,40 keep-alive sockets,16,000 authenticated REST/MCP
requests and100 subsequent connection turnovers. The finite eight-request gate
returned3,200 successes and12,800 explicit429 responses; every client succeeded.
Measured request/turnover duration was91.826s. API PSS was48,102KiB baseline,
49,062KiB with40 idle sockets and51,552KiB peak (RSS peak72,608KiB). File descriptors
went8→48→8 and remained8 after turnover; threads peaked at9. PostgreSQL retained
only the measuring connection after requests, with no additional streams/windows/
queued jobs; database allocation increased8,192bytes. This proves bounded behavior
for this short synthetic workload, not day-long stability, provider throughput or
capacity on an untested Hetzner machine.

The local spool completed1,200 enqueue/ACK cycles while rotating bounded caches;
its SQLite file was221,184bytes after400 and after1,200 cycles. Eight deliberately
blocked entries survived overflow and cache pressure unchanged. Five admission
regressions first failed before implementation; after finite backlog/database/
free-space checks,15 admission/fencing/source tests passed in24.97s. Read/status,
exact receipt replay and cancellation remain available while fresh input is
rejected. Diagnostic retention is bounded separately; no knowledge/source/input
retention policy deletes accepted or pending information.

Reproduction (root-DB fixtures must not run concurrently):

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55458 \
 RAG_RESOURCE_WAVES=400 RAG_RESOURCE_REPORT=/owned/scratch/resources.json \
 .venv/bin/python -m pytest -q tests/service/test_resource_limits.py
```

The recorded400-wave run passed2 tests in100.03s before the separate log-retention
case was added. Raw artifacts are in the operator scratch directory as
`resource-40-connections-long.json`, `resource-spool-plateau.log`,
`service-s2-fence-green.log` and `resource-fencing-regression.log`.

After these corrections, the complete selected S2 command (all `tests/service`
plus lifecycle adapters, MCP, worker and mining suites listed in the previous S2
section) passed243 tests in136.12s, exit0, with one upstream Starlette/httpx
warning. The resource rehearsal in this combined run used its default100 waves;
the separately recorded400-wave result remains the longer workload above.
Independent review2 covers the complete corrected S2 slice, not only its fixes.

## S058-02 review2 corrections

Independent review2 repeated the selected243-test acceptance successfully in
145.05s and confirmed all review1 corrections. It found one High (an embedding
fallback reloaded the rotated verifier, accidentally adopting a credential that
never authenticated the original request) and two Medium defects (deferred
embeddings missed storage checks; transient admission contention exhausted the
job attempt budget). No new Low findings were reported.

The initial local regression run failed6 cases in6.58s. One mislabeled
"database-before-commit" case actually duplicated the disk-before-commit probe
and was removed; the five distinct cases remain. Immutable principal credential
revisions now reach every deferred reference without reopening policy. Storage
checks run before embedding inference and commit. `ResourcePressure` keeps source
and embedding jobs pending with backoff and unchanged attempt budget; it neither
discards accepted input nor repeats an accepted extraction. Authentication plus
the rotation regression passed5 tests in3.50s. All five correction regressions
plus source/fencing tests passed17 in27.23s. A new integrated acceptance and the
third independent S2 review follow; S2 is not accepted solely from these results.

The complete corrected S2 selected acceptance passed248 tests in140.50s, exit0,
with the known Starlette warning. Two older graph regressions now create their
write context through real policy authentication, so queued embeddings carry a
verified original credential revision. The third S2 review receives the complete
current slice, including every correction and the resource workload/limits.


## S058-02 review3 corrections and S058-03 operations

Independent S2 review3 passed248 tests in151.44s, confirmed the previous six
findings resolved, then found H human-session logout/expiry not reaching jobs,
M repeated cancellation adding audit rows outside admission, and LOW004/005
(missing stable status code; log character/byte accounting). Six meaningful
regressions failed before correction; the22-test correction selection passed
in24.53s. Exact authenticated human session hashes now reach jobs and are checked
before inference and commits. Already-cancelled receipts return without mutation.
Status codes are allowlisted and log limits count complete UTF-8 encoded records.
LOW004/005 are recorded in Issue75; independent final confirmation remains due.

S3 owned schema018/019 inventory/strict restore/local upgrade/cutover/resume,
interrupted-DDL rollback, model-digest refusal and CLI tests passed15 cases in
30.43s (`service-s3-upgrade-extended.log`). The new local upgrade verifies hashes,
counts, original grants/ownership/sequences and history before committing DDL.
Remote import refuses a changed populated target and mismatching embedding digest.
No production store or real model/provider was used.

Operational regressions first failed9 cases, then55 worker/backup/CLI cases
passed in22.48s (`service-s3-operations.log`). Legacy central embedding jobs now
check storage before provider work and commit. SIGTERM stops between jobs and
restores signal handlers on return. Scheduled backup uses the configured DSN,
private exclusive files, finite retention and server free-space preflight.
A pressured backup preserves the previous copy. Two recovery regressions failed
before explicit owned job reauthorization and role-default fence checks;
13 recovery/upgrade tests then passed in32.37s (`service-s3-recovery-green.log`).

A1MiB legacy document regression failed before remote read preflight. SQL byte
checks, finite graph/domain materialization and server cursors then passed19
read/graph/domain/auth tests in24.22s (`service-s3-read-limit-green.log`). Local
large-document access remains available. Deployment examples separately bound
API/worker memory, process/FD counts, provider parallelism and journal retention;
they are examples for operator review, not installed services or measured model
capacity. `systemd-analyze verify` initially rejected only absent deployment
executable paths, with unrelated installed xfs unit warnings; no live start was
performed. The central operator guide is medium standalone documentation using
PB05801..03; independent review/rehearsal evidence is still pending.

Full diagnostic round1 on isolated port55458 finished with15 failed,1415 passed,
1 skipped and1 known upstream warning in1230.58s, exit1. The15 failures were the
12 correction-export allowlists and3 planner timing assumptions described below;
this run is not counted as passing. After correction, the complete affected
benchmark and planner selection passed54 tests in15.40s, exit0. Log
`service-full-r1-corrections.log` SHA-256:
`40a417aee334fdce3ec9fb69dd927b1257eca19565f86175d8b8b8ffc2299a80`.


PB05801..03 content self-review (coordinator,2026-10-29) checked scenario,
parameters, actor/target, approval, interruption, retention and recovery decisions
against `service/operator.py` and `upgrade.py`. Terminology and reader checks
resolved undefined receipt/applied/fence/manifest terms in the guide. No public
production paths or credentials were added. Content independence and whole-path
CLI rehearsal remain final-review obligations. Known unperformed branches:
actual systemd startup/tailnet proxy, production cutover, permanent revoked-spool
partition replay, independent-store import and real-model/hardware sizing. These
are explicit boundaries, not passing rehearsals. Changes to those interfaces
invalidate the applicable playbook evidence.

The first full-suite run exposed two existing correction-export schema allowlists
still restricted to018/019/020. A direct reproduction on a separate owned022
database first failed export, then validation; both exact known-prefix checks
were extended through022. Unknown/reordered schemas still refuse. Fresh full
round2 remains required after the final-review corrections.


### Planner timing diagnosis (LOW006)

Three full-suite legacy planner failures involve40ms success expectations. A
separate owned schema020 reproduction also failed40ms before the service schema.
Fresh-backend same-host calls measured75–85ms even with all service RLS disabled.
Two exploratory SQL optimizations did not meet40ms and were discarded completely;
no eligibility semantics or service policies changed from the reviewed S2 source.
The tests retain40ms controlled cancellation and setting restoration, use250ms
for a successful millisecond-formatted budget, and explicitly select1s for the
post-cancellation availability probe. Production budgets remain unchanged. LOW006
is recorded in Issue75; the54-test selection above passes and final independent
review1 accepted the test changes. Fresh full verification remains outstanding.
Earlier commentary attributing this to RLS was superseded by
the schema020 control experiment.

### Practical synthetic examples

The owned `measure-service-examples.py` run on this8-logical-CPU,15GiB shared VM
completed without model/provider calls. The full pytest suite was running, so
these are workload observations, not an isolated performance claim. Local domain
lookup:40 samples, first17.41ms, warm median18.04ms, process CPU0.129s. Scoped HTTP
lookup:80 samples, first25.23ms, warm median22.91ms/p9551.01ms; API PSS51,533→52,413KiB
and9 file descriptors throughout. Local/remote scope differs; no retrieval quality
or speed improvement is inferred from transport measurements.

Four durable source windows were admitted in79.12–108.66ms, then drained to four
applied receipts/zero pending in1.217s (coordinator CPU0.366s). Two real runners
contended for the database: primary exit0, contender exit1; four mocked50ms
extractions, peak simultaneous inference1. This tests serialization/backlog,
not actual provider throughput. Raw artifacts: `service-examples.json`,
`service-examples.log`, `measure-service-examples.py` in the owned task scratch.
An initial measurement included an unrelated synthetic deferred-embedding job
and failed its empty-queue assertion; the corrected empty-domain workload avoids
that model-boundary job. The separate40-connection and spool plateau observations
above remain the retained connection/disk examples. Actual ML residency, embedding
contention and Hetzner4-vCPU/8-GiB measurements are unperformed rollout checks.

The systemd examples passed `systemd-analyze verify` after substituting only the
intentional executable path with this worktree's actual executable (exit0);
installed unrelated xfs unit deprecation warnings remain. All10 relative guide
links resolve, the example configuration and substituted-verifier policy parse,
and `uv lock --check --offline` passes. These checks do not install/start services.

### Final whole-feature review1 and corrections

Independent Sol/high review inspected all99 files (+6,130/−120), base
`979c334d9ed7b93e7ba2e015e8ed281998ba1288` to staged tree
`d589ad924ff43b3f67c66d853eedd816b0067fbe`. It confirmed the prior S2 fixes and
LOW004–006 dispositions, and reproduced H058-01, M058-02 and M058-03.

Synchronous save regressions reproduced commits after logout, session expiry
and key rotation. Canonical service connections now bind their original scope
and reload the exact credential/session and permissions before committing,
including transaction-context commits. Scope removal is also covered. Failure
rolls back canonical writes. Mining retains its separate immutable accepted
extraction and audit, while application remains independently authorized/fenced.

The supplied60s PostgreSQL idle-transaction deadline killed a supported300s
extraction. Its finite limit is now30min, covering the example extraction and
the default256-input embedding page's eight120s HTTP rounds. A real PostgreSQL
rehearsal scales these supplied settings by1/1000, with mocked300ms extraction
and120ms embedding waits. It failed with the old settings and saves successfully
with the corrected settings. No production/database timeout was changed.

A source-backed small document returned1,201,267 bytes despite the512KiB read
budget. The SQL preflight now accounts for joined knowledge sources, repeated
spans, both edge directions and assertion records, with conservative row and
container overhead. Remote `memory_get` uses one repeatable-read snapshot for
preflight and materialization; oversized reads return413 before Python loads
the records. The local large-document contract remains available.

Regression and affected API/worker/fencing tests:30 passed,1 known upstream
Starlette warning in56.04s, exit0 (`service-final-r1-fixes.log`). The command used
`env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55458
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`
with `tests/service/{test_final_review,test_source_worker,test_read_limits,
test_review_round3,test_worker_fencing,test_api}.py`.

### Independently derived integration and operator rehearsals

Reviewer-derived IT058-S01 and IT058-R01 are implemented in
`tests/service/test_integration.py`. Both passed in17.07s, exit0, with the same
isolated PostgreSQL environment and one upstream warning. Source fixtures are
owned schema019 stores with two domains, evidence, assertions, a pin and history.
Real client capture/spool, HTTP, strict dump/restore, canonical gateways and the
actual database-fenced runner are used; model boundaries use synthetic output.

IT058-S01 verifies local upgrade and original row/ACL/history preservation,
non-regressing sequences, separately visible window/head/job commit before ACK,
local pending retirement, exact replay without another source/job, one applied
batch, exact authenticated evidence namespace/audit actor, REST/MCP access,
foreign receipt/checkpoint/document denial and RO mutation denial.

IT058-R01 drops an ACK after server commit and restarts/replays the spool, pauses
after durable batch acceptance, then logs the human out before application. It
observes retained extraction and zero applied knowledge. A new login explicitly
retries the owned receipt, preserves original provenance and applies once without
another inference. An old pre-acceptance manifest refuses resume after new
writes. A current-target verified backup and an independently restored target
match source, batch, checkpoint, knowledge, ACL, pin, sequence and audit state.
Initial scenario setup was corrected to use the actual202 upload contract and
the captured event ID; the final assertions require an original evidence span.

The separate actual-CLI rehearsal (`rehearse-service-playbooks.py`,
`service-playbook-rehearsal.json` in task scratch) ran inventory, local upgrade,
status, remote preflight, source fencing, target restore/resume, refusal after
new target writes and a current-target verified backup on an owned populated019
store. PostgreSQL/dump/restore and CLI dispatch were real; model digest metadata
was synthetic. Node OpenCode tests passed7/7 in431.09ms, exit0.

Guide updates are focused corrections within the existing medium operator
document; terms, prerequisites, reader actions and evidence boundaries were
checked against the supplied examples. Actual systemd/peer-auth/TLS startup,
cross-host transfer, process-killed retained-fence recovery, real-model load and
4-vCPU/8-GiB capacity remain unperformed rollout checks. A fresh full suite and
independent complete-range review2 remain required before code readiness.

### Final whole-feature review2 and corrections

Independent Sol/high review inspected the complete101-file staged tree
`2905fddda5d477ef80d75f2efd699a16d9f4e9f5` (+6,641/−121). It confirmed all three
review1 corrections and the independently derived integration assertions. It
found no new Critical/High defects and reported M058-04/M058-05 and LOW-007.

M058-04: a server cursor fetched an8MiB legacy graph value into Python before
rejecting it. New graph and domain regressions reproduced this transfer on both
paths (2 failed in7.71s). Their shared helper now describes columns without
values, then uses one materialized SQL statement for bounded row selection,
aggregate size/count and guarded projection. Oversized values become NULL
inside PostgreSQL before transfer, followed by413. Row-count boundaries,
UUID/timestamp/null types and descending caller order have explicit checks.
Standalone reads retain their existing contract. Database statement/temp and
process/storage budgets remain separate from API result transfer limits.
Repeating the reviewer's original8MiB probe after the correction transferred
zero string bytes in the rejected cursor batch; measured Python peak was
1,085,879 bytes, compared with16,895,939 bytes in the reviewer's original run.
Both measurements include HTTP/test overhead and are single synthetic probes,
not an API process RSS limit. The corrected probe passed in7.40s, exit0
(`service-final-r2-graph-memory.log`).

M058-05: the earlier S2 key-rotation regression expected a deferred job to commit
after rotation during a synchronous save. Review1's canonical commit protection
correctly refuses that commit. The test now distinguishes rotation during save
(rollback, no document/job) from rotation after a successful save (original job
revision retained, revoked job cannot infer/apply). The commit guard is unchanged.

LOW-007 is recorded in Issue75: manual `spool --flush` stopped at fresh source
staging pressure before uploading existing pending entries. A real HTTP/spool
regression first failed with `SpoolFull` (3.03s). The CLI now records a bounded
staging error and drains durable input, matching the uploader. The test checks a
checkpoint ACK frees capacity, then a second invocation uploads the retained
source. No pending source is removed to make room.

Initial correction selection:21 passed, one known upstream warning in34.81s,
exit0 (`service-final-r2-fixes.log`). The complete service selection then passed
115 tests in233.99s, exit0, with the same warning
(`service-final-r2-acceptance.log`, SHA-256
`ab3bb5d9dcd40519c84b9afacca4547b2592be426a0f9ae50a20992d9031627b`).
One attempted selection also included root SessionStart fixtures; it was
interrupted during service tests before those shared-database fixtures ran, to
preserve the single-root-suite rule. It is not counted as passing.

Full-suite round2 finished with1 failed,1437 passed,1 skipped and1 upstream
warning in1192.99s, exit1 (`service-final-full-r2.log`, SHA-256
`72b747e4a94375ce58acf2c4608a90d0cbdde1fda3668d06fc978f8dc2711d04`).
Its sole failure was the superseded M058-05 rotation expectation. A fresh full
round3 and complete-feature independent review3 remain required for readiness.

### Multiple users and24 agent sessions on one VM

The maintainer clarified that one VM can run20+ AI sessions for different Herdr
users. `tests/service/test_multisession.py` characterizes24 concurrent sessions,
12 per independently authenticated user, on one logical host. Raw agent session
IDs deliberately overlap across users. Each session has a distinct synthetic
prompt and continuation. No real provider/model is called.

All24 windows and24 checkpoints were accepted; receipts, stored payloads,
source jobs and checkpoint handoffs remain distinct. Foreign receipts return404.
Accounting cannot retrieve an IT credential-location document by known ID,
lexical search or context. Positive own-department context assertions prevent a
vacuous empty-response success. The two profiles share a host label; that label
grants no authority. Static per-user profiles are supported; automatic Herdr
account-to-client configuration binding is not installed or verified.

The final run passed in17.89s, exit0, with one upstream warning
(`service-multisession.log`, SHA-256
`698fb6b003618cf86ac1466208d7917aaa56a9101c5349d902d04d0ed58b4386`).
The measured workload took15.728s and observed26 global-capacity and147
write-capacity429 responses before bounded backoff/retry succeeded. An initial
fixed50ms retry probe caused contention; exponential/staggered backoff resolved
it. A diagnostic assertion was corrected to expect the context's title overview,
rather than a full document body. This proves accepted-state isolation and burst
backpressure, not24 simultaneous model calls or target-hardware throughput.

The example policy was loaded from an owner-only file after replacing all four
verifier placeholders with distinct synthetic values. Both users authenticate;
the accounting profile can write accounting, cannot read IT or `general/global`,
and is not an administrator. Old general/global knowledge still requires reviewed
classification before stores are combined. RAG scope does not restrict command
execution or OS file permissions; department secrets/tool privileges require
separate local protection. No production configuration or Herdr launch was changed.

### Clarification: IT team sharing, not private user silos

The maintainer clarified that all IT members must share IT knowledge and session
logs. The pending final review3 was cancelled and its complete pytest run was
interrupted deliberately after240 passes in257.01s, exit2; neither is recorded
as a passing final gate. No production runtime was interrupted.

New team tests first failed2/2 in4.70s (missing team routes/membership). Static
`session_teams` now grants current team/project SELECT visibility through a
separate immutable publication record, committed with input/checkpoint. Uploader
IDs/cursors and job authority remain distinct; Herdr names never authorize access.
The new bounded REST session list/window/checkpoint routes omit internal job
credential references. Publication-team history survives author departure.

The initial2 tests passed in5.36s. Extended checks cover shared IT knowledge,
RO team reading, paginated discovery, accounting denial, member revocation,
unchanged source identity, owner-only cancellation/retry, direct SQL old-row
mutation denial and forbidden foreign-team publication. Two diagnostic assertions
were corrected to the actual search `results` contract and matching isolated
authentication policy; commit protection was unchanged. The affected selection
(team, checkpoint, reviewer-derived integration and upgrade tests) then passed
18 tests in51.11s, exit0, one upstream warning (`service-team-affected.log`).
Complete service acceptance then passed119 tests in220.16s, exit0, one upstream
warning (`service-team-acceptance.log`, SHA-256
`e32fdfbe43e215951e1b5e4241744925fddddfd698b0df5a4e1f2a427080bdfe`). Resumed final whole-feature review and full
project verification remain pending. Existing local raw transcripts are not automatically uploaded, and
no unclassified legacy department history is silently published.

### Final whole-feature review3 and final authority corrections

Independent Sol/high review inspected all104 files, +7,360/−121, base979c334
to tree37af772cb9217db28eef8e6dc37fe18021762156. It confirmed all earlier
H058-01/M058-02..05 and LOW-001..007 corrections. Its selected tests passed19
in63.11s, exit0. Extra probes confirmed same-project cross-department denial,
project revocation and history retention after author disable. No new Critical,
High or Low defects were reported. M058-06 and M058-07 required corrections.

M058-06: cancellation checked ownership but could change the queue after a
project-revoked window UPDATE affected zero rows; full write revocation produced
500. M058-07: two human VM profiles without a machine ID shared their user's
namespace, so equal raw sessions collided or overwrote a handoff. The reviewer's
three original reproductions were added as regression tests and first failed
3/3 in7.09s (`service-final-authority-red.log`).

Cancellation now explicitly requires current project write authority and a
confirmed window UPDATE before queue and audit mutation. A restrictive SQL-policy
probe additionally verifies zero-row UPDATE leaves both window and queue unchanged.
Human login now binds a stable uploader UUID to its authenticated session. An
independent first login receives a distinct profile; renewal sends the retained
UUID. The CLI creates/reads an owner-only, fsynced uploader file and verifies the
server returns the same ID. Source/checkpoint namespace includes the uploader;
machine-key namespaces and team read grants are unchanged. Worker/commit checks
include the exact session/uploader reference. Renewed tokens still require
explicit owned retry; unbound legacy HTTP sessions fail closed. Tests cover
independent profiles, handoff separation, renewal/replay, retained accepted output,
logout/expiry/revision revalidation, tampered reference rejection, CLI persistence
and owner-only identity files.

Initial authority selection passed18 in36.05s. The final expanded selection
passed28 in61.37s, exit0, one upstream warning
(`service-final-corrected-acceptance.log`, SHA-256
`58928d149da7f1646da29ebaf4979fb01d929148dd1d00bcc756953626e98694`).
Command: the isolated PostgreSQL environment above with `pytest -q -p
no:cacheprovider tests/service/{test_final_authority,test_job_retry,
test_review_round3,test_final_review,test_operator_cli,test_integration}.py`.

The then-running pre-correction full suite was deliberately interrupted after
758 passes in699.84s, exit2; this is not a passing full gate. Fresh full-project
verification now runs from the corrected tree (`service-final-full-verified.log`
and `.exit`). The three completed independent review rounds are retained; no
fourth reviewer was started. Final correction verification is coordinator-owned.

### Canonical Issue58 audit and authorized target-copy rehearsal

On2026-10-29 the maintainer authorized deployment and testing on an existing
4-vCPU/8-GiB Hetzner VM with a copy of the local production RAG. Local production
remains active and unchanged; this is an isolated copy, not a canonical cutover.
The issue's explicit reference-hardware acceptance remains mandatory. AC-006
has been corrected to retain that requirement; earlier local measurements alone
do not satisfy it.

The audit found missing client/server support and deprecation text, now included
in the operator guide. OpenAPI now exposes the actual strict source/checkpoint
request models, human-login fields, protocol header, path/query parameters,
202 durable-acceptance response and bounded job/session responses. The public
health/login operations no longer incorrectly advertise bearer authentication.
The new consumer contract test failed before the change, then the contract/API
selection passed6tests in16.45s. The previously corrected whole-project state
passed1455tests,1skip,1known upstream warning in1205.45s, exit0;
log SHA256`0e47c42196d2f8ce72809d150f075dfd7db78a424b7657804ccdd669bed242c7`.
That full result predates the OpenAPI addition; fresh cloud verification follows.
The explicit support matrix was completed during this audit, not retroactively
claimed as published before implementation.

A consistent populated schema019 snapshot was strictly restored and compared
locally, then transferred privately and restored on the target. All22original
tables retain their row counts/hashes, grants and history; migrations020–022
were applied only to the copy. The source contains24428documents,29999chunks,
12385edges,3613sources,65checkpoints,4pins and129205audit rows. An additional
read-only target reference database retains the verified pre-test state.

The target uses the exact original bge-m3-q8 digest and pgvector0.8.4. The first
real embedding returned1024dimensions in2.211s including2.082s model loading;
the model service peaked at833503232cgroup bytes. A real OAuth-backed synthetic
Haiku request succeeded in5.613s. Its credential is root-owned0600, persistent
across boots, loaded by the enabled worker unit; no credential is published.

Bootstrap rehearsals exposed missing extension ownership, pgvector GUC preload
and original default-ACL owner requirements. Failed strict restores rolled back
fully to an empty target. The successful restore preserved the original database
owner through explicit peer/PGUSER configuration, without granting scoped roles
superuser or bypass-RLS. Restore took64.933s; operator process peak51.9MiB.
The guide now states those bootstrap requirements. Operator restore disabled its
statement deadline and used512MiB maintenance memory; normal request limits remain.

The cloud test harness initially lacked UTF8 database initialization and a Git
source snapshot required by existing native benchmarks. These are harness faults,
not successful suite results. The corrected harness uses a separate loopback-only
PG17 cluster on55458, an independent home and a clean source snapshot. LOW008 in
Issue75 records an additional non-hermetic contextual-index fixture: on a host
without the default model tag, its second digest lookup was not mocked. The
corrected embedding-reuse/benchmark selection passed30tests in2.49s on target.

The first populated scoped hybrid-search test reached the15s SQL deadline.
The correction and fresh measurements below supersede that initial result;
those bootstrap observations alone established no hardware capacity.


### Populated cloud search correction and reference-host acceptance

Migration023 replaces the SQL `claim_eligible` expression with keyed PL/pgSQL
lookups under the caller's existing privileges and RLS. It changes no trust,
evidence, temporal or department rules and adds no security-definer authority.
On an owned24428-document/29999-chunk target clone the original lexical and
hybrid calls each cancelled at15s. The corrected calls took2.556s/3.798s;
hybrid returned5hits. No deadline was raised. The change remains additive for
local installations. Independent parity probes exercised216trust combinations
plus legacy/empty cases under owner, local/scoped reader and writer roles:
zero deviations. The bounded review also validated15real HTTP responses
against OpenAPI and found the original022 uploader upgrade gap, M058-08.

M058-08 is corrected through023, leaving022's original table definition intact.
A populated original022 upgrade first failed at the missing uploader UUID.
Its regression now checks strict backup/restore, original session fields,
nullable uploader addition, fresh login and rejection of original-field or
new-profile drift. Existing sessions require fresh login; rows remain retained.
The affected upgrade/claim selection passed26tests in37.71s. The previous
broader correction selection passed33tests in63.53s.

Actual cross-host TLS on the4-vCPU/7757-MiB target verified four machine
identities,24durable windows/checkpoints,20IT sessions with team sharing,
accounting denial, read-only tools, duplicate ACK, out-of-order409 and eight
idle SSE rejections. Twenty-four windows/checkpoints completed in5.875s with
bounded429/backoff. Twelve populated hybrid searches took3.636–3.881s;
warm median3.739s. These calls used the configured real quantized embedding
model and returned no private content to the published evidence.

Forty persistent TLS clients issued8000mixed capability/domain REST/MCP
requests in66.134s:1810HTTP200 and6190HTTP429. Every client succeeded at least
once;100subsequent new connections also succeeded. This is an intentional
8-active-request admission test, not a maximum search/model throughput claim.
Over240samples/255.16s, API PSS was72040→75210KiB, peak78069KiB; FD peak51,
ending10. Canonical database size grew253952bytes while24durable inputs were
added; free disk fell593920bytes. No day-long stability claim follows from
this finite workload. An exact key-based comparison with the read-only
reference verified299254original rows across26tables, including all24428
original documents and129205original audit rows, remained unchanged after
target migration and appended test inputs.

The first full UTF8/Git target run completed1463passed/5failed/2skipped in
310.88s. Three failures used a legacy-only cancellation fixture that no longer
accessed the locked evidence table after023; it now seeds a real claim while
retaining40ms cancellation and settings assertions. LOW009 fixes an unused
embedding mock; LOW010 refreshes PostgreSQL's teardown statistics snapshot
with a finite2s grace while still requiring exactly one measuring backend.
The targeted five-test correction selection passed5tests in37.36s. The rolling
findings remain in Issue75. The corrected target full round2 passed1469tests,
with2skips and one upstream warning, in312.61s, exit0; log SHA256
`f0ea4bd289960e3c07a2ff2dc3e202004df8b9b95e4540731ad5d1769ba2770f`.
That run precedes the final uploader-schema guard below.

The maintainer prioritizes current-work retrieval/context over background
session-log extraction. API CPU weight200 and the serial worker's weight20,
nice10 and one-CPU quota implement the process-level preference; PG/shared
Ollama work has separate budgets. Roadmap6.10 / Issue68 now explicitly owns
bounded queued tool requests, visible waiting, compaction capture and shared
model scheduling. Those later capabilities are not claimed by Issue58.

The second bounded correction review found that the original022 preservation
exception checked all-NULL values without validating the new column's structure.
An integer column could therefore pass preservation and fail at login. The
coordinator's small correction requires a nullable plain UUID with no default,
generated value or identity, both before service access and during verification.
Three independent type/nullability/default mutations failed the regression
before the correction; the affected upgrade/auth/schema/OpenAPI selection now
passes37tests in60.78s. No further full-feature review round was added.

### Real extraction, recovery and foreground contention

Only synthetic inputs were submitted to the actual OAuth-backed extraction
provider. A separate empty owned database kept the original copied IT corpus
out of this inference rehearsal. Thirty windows produced30applied batches and
30completed jobs. Twenty-four ephemeral test windows intentionally yielded no
retained knowledge; six durable configuration examples produced8documents,
6sources and8claim-evidence records. During one active model invocation the
owned worker was killed; systemd restarted it once, and all jobs eventually
completed without a duplicate applied batch. All8documents and8source relations were read back through authenticated TLS
by IT; accounting received8not-found results. The synthetic worker and temporary
API/TLS route were then stopped. The canonical copied store's worker remains inactive behind a boot
condition pending an explicit source cutover.

Three waves of eight simultaneous TLS requests each combined four populated
searches with four context calls. With extraction idle, search median/max were
5.176s/6.643s and context1.547s/1.909s. With six real extraction jobs initially
pending, all24foreground requests also returned200: search median/max
5.039s/6.473s, context1.700s/1.963s. One job applied during that finite workload;
the remaining queue drained afterward. This demonstrates concurrent progress,
not a causal speedup,20-agent inference capacity or a latency SLA. The connector
context deadline is1s, so a hook can still fall back to stale/offline context
under this burst; queued foreground waiting and shared-model scheduling remain68.

Across226samples/242.331s covering idle and active extraction comparisons, API
peak PSS was73791KiB and worker peak PSS316080KiB; worker cgroup peak was
257445888bytes, with at most two processes. Ollama peak PSS892994KiB and main
PostgreSQL peak PSS643251KiB were separate shared budgets. Their respective
cgroup peaks were914825216 and1612963840bytes, including charged cache.
CPU accounting during this interval was7.505s worker,12.660s Ollama and111.219s
PostgreSQL; none is a full-day or maximum-throughput measurement.

Fresh OpenCode adapter verification: `node --test tests/test_opencode_plugin.mjs`,
7passed/0failed,474.18ms, exit0. Its compaction reconciliation remains intact.

### Final target verification and convergence — 2026-10-30

The final command ran after the uploader structure correction on the same
reference host, with a clean source snapshot and isolated PostgreSQL17 cluster:

```sh
PGPORT=55458 HOME=/owned/test-home TMPDIR=/owned/test-tmp \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rs -p no:cacheprovider
```

Result: **1472passed,2skipped,1upstream warning,318.66s, exit0**. Log SHA256
`5766ce2e9ebfd257cede0322e7fbe5463eb43d2cb0a3edc299d0ca62230187a7`. Skips are the
macOS-only launchd test and a test requiring local Claude transcripts; synthetic
transcript and adapter tests do run. The warning is Starlette's deprecated
httpx TestClient integration. Source parity checks matched all267engine, SQL,
test, deployment and dependency files between the local branch and tested host;
manifest SHA256`f06bf03774feeef43723ab8814d09f3c9cdf98c807d563b2c8c335ca1246e424`.
Only evidence/documentation edits follow that run. `uv lock --check --offline`
and100local documentation links also pass.

| Requirement | Current evidence |
|---|---|
| FR001–002 / AC001 | Shared CLI/MCP engine, local default, REST/OpenAPI/protocol refusal; full suite and populated018/019/original022 upgrade regressions |
| FR003/003A–005 / AC002/002A/002B | Four TLS identities,24sessions, shared IT logs, accounting/RO denial; human renewal/revocation/uploader and fail-closed schema regressions |
| FR006–008 / AC003–004 | Durable ACK/spool/replay/checkpoints, reviewer-derived success/recovery integrations, real30-job worker kill/restart; existing compaction adapter regressions |
| FR009–010 / AC005 | Strict local/cross-host restore and299254unchanged original rows; collision inventory and refusal of unmapped independent imports |
| FR011 / PB05801–03 | Reviewed CLI procedures, isolated upgrade/forward-recovery rehearsals, actual peer/systemd/private-TLS deployment on a copy |
| FR012 / AC006/008 | Real4-vCPU/7757-MiB host, populated retrieval,40persistent TLS clients, churn, finite memory/disk and real-model contention measurements |
| AC007 | Three complete-feature review rounds, bounded subsequent SQL/upgrade reviews with regression fixes, full1472Python/7Node checks; rolling Lows in75 |

Convergence found no remaining evidenced Critical/High/Medium code finding.
The support matrix was finalized during implementation, rather than published
before every cross-component change; that sequencing deviation is retained.
The reference-host evidence does not authorize or complete production cutover,
automatic independent-store consolidation, Herdr account binding, a day-long
soak or unlimited concurrent model use. A process-killed operator with a retained
migration fence and every real host's compaction UI remain additional rollout
rehearsals; adapter simulations and safe retained-fence procedures do not claim
those live cases. Issue58 stays open for installation-specific rollout, and68
owns the explicitly requested foreground queue and shared compute scheduling.
