# Issue59 dashboard verification

Status: code, independent review and final full suite verified; tested PR published. Canonical rollout remains separate.
Base0.6.11 tree29ec9d54 (same tested plugin/queue tree as mergedPR77); target0.6.12/schema 025.
[Requirements](../specs/6-1-dashboard/spec.md), [tasks](../specs/6-1-dashboard/tasks.md),
[operations/playbooks](../15-dashboard.md), [model](../uml/dashboard.md).

## Current evidence

- First meaningful red browser-boundary tests:3 failed because routes/bootstrap did not exist.
- First green:3 passed in4.93s; scoped setup/rotation/audit tests:8 passed in11.55s.
- Additional hardening:4 passed in7.94s. Unsafe grants probe failed as intended before the new owner-only control-table schema check; correction and independent adversarial verification are recorded below.
- Browser dependencies are optional development dependencies. Chromium requires normal Linux shared libraries; on this development VM missing libraries were extracted to private scratch rather than modifying system packages. Infrastructure/dependency failures are not accepted as UI verification.

## Current populated-copy rehearsal

Hetzner CX33, 4vCPU, 7,757MiB RAM, no swap. The canonical API remains
active and its extraction worker remains inactive; the cutover approval marker
is absent. A separate0.6.12 API runs under the existing restricted `rag` account
on loopback8769, behind a private Tailscale HTTPS listener on8449. Its cgroup
has a384MiB memory ceiling and64-task ceiling. This is a rehearsal service.

The owned024 copy upgraded to025 after a complete strict backup restore:
**301,183 original rows,28 original tables, original hashes/ACLs/history and
sequences preserved**. The migration added only `025_dashboard.sql`. No source
or canonical database was migrated. The DBA performed verification because the
inherited default privileges refer to a different historical owner; normal
runtime roles were not elevated. Only the three newly created control tables
were assigned to the runtime owner afterward. The prepared-template option is
separately covered under a nonsuperuser role; it does not bypass historical ACLs.

Private source snapshot manifest at first deployment:
`05eafcca9aa7a667b4c680501d4bc8b678f2eafdf7405827f38bb9447f6e3cc9`.
This is the historical first-deployment manifest; corrected backend/UI synchronization is recorded below.

## Current resource and browser evidence

The first finite read soak used40 distinct synthetic user/session credentials,
20 requests each: **800/800 successful**,384 retryable429 responses,23.05s.
API PSS peaked at69,605,376 bytes (66.4MiB); maximum6 database connections
included the sampler. Database allocation increased16,384 bytes. No models
were invoked by the read workload and no original copied memories were visible
to its restricted scope. This is bounded admission with client retry, not an
inference benchmark or latency guarantee (p95 including retries4.819s).

A subsequent2,400-read warm-up run also completed. It overlapped a browser
navigation attempt that received capacity errors; that attempt is **not** a
successful browser acceptance run. A final serialized browser run then passed
actual private HTTPS, Secure/HttpOnly/Strict cookie properties, scoped empty
library, administration, all5 live setup checks, page-reload resume, logout and
zero JavaScript errors. Embedding and provider probes sent only synthetic text.
A separate successful check after restarting the owned API process preserved
all5 checks and completed setup, retained scoped reads and verified logout.
The first immediate post-restart HTTP call returned502 before startup readiness;
only the later healthy service response is the successful restart evidence.

A final serialized warm-state read soak completed **2,400/2,400 requests**
across40 distinct sessions in63.78s (248 samples;1,503 retryable429s).
PSS:104,781,824→105,164,800 bytes, peak105,190,400 bytes (100.3MiB).
Database allocation stayed exactly656,996,019 bytes; peak6 connections included
the sampler. This run followed the live synthetic provider check and included
no simultaneous browser setup probe. The earlier model probe briefly raised
the API cgroup memory peak (including its child process) to273,428,480 bytes;
its384MiB ceiling remained in place. These finite cold/warm observations and
explicit caps do not prove multi-day stability or combined extraction load.

Three local real-browser tests pass in38.79s: source/search/scope/mobile/keyboard,
admin enrollment/rotation/resumable setup/expiry, and actual first-admin form.
A subsequent UI check covers displayed reported capabilities and effective rights.

Recent local regression selection: **142 passed in47.01s**, covering correction
export025 compatibility, transport limits, legacy scope/domain/entity upgrades.
Prepared-template and nonsuperuser restore selection: **2 passed in15.39s**.
Disabled-owner inventory and first template regression: **2 passed in10.21s**.

The original full-r1 process left no final exit artifact; its partial output is
not a full-suite result. Full-r2 completed with1,541 passed/1 skipped/1 upstream warning in1,385.37s, exit0. Its collection predates the later browser assertions and review corrections; it is baseline evidence only. Final full-r3 is running on the corrected implementation. Independent review2, documentation-set acceptance and its actual final exit remain delivery gates. The rendered operations/reference
set was inspected through Chromium and79 relative Markdown links resolve. Canonical writer cutover
and production migration are outside this PR's authority.


## Independent review1 and verified corrections

Review1 covered all49 changed files at tree
`8e6a2f6161537b93c7a667e79e2052cc90318087` against
`29ec9d54a15ab3d1227cddc59bc58ab9cd2c5333`, with fresh isolated PostgreSQL,
synthetic/mock-provider probes and real Chromium. It found1High/2Medium/2Low.
All three blocking allegations were independently reproduced before changing code:

- H1: real logout returned200 before a pending policy apply still returned200.
  The corrected path locks the exact session row after durable preparation,
  revalidates current admin authority and clock expiry, and holds that lock
  through atomic file replace and applied-journal commit. Regressions verify
  prior logout401/no file change, concurrent logout serialization and expired
  authority/no replace with recoverable prepared audit.
- M1: an unreachable/uncredentialed client target incorrectly became verified.
  Discovery now uses the existing authenticated bounded HTTP transport without
  opening a spool. Tests verify a real API target, restart persistence, changed
  credentials marking checks stale, invalid credentials, true offline failure,
  unsupported protocol and missing queued-tools capability. Saved target ID,
  protocol and safe reported version come from the actual response.
- M2: custom default ACLs exposed new control tables and passed schema checks.
  Migration025 strips all non-owner grants on only its three new tables;
  validation rejects later arbitrary/group grants and non-superuser owner
  memberships. A populated024 regression retains original knowledge and table
  ACL while proving the new control state is private.

Low findings are retained as LOW-013/014 in
[Issue75](https://github.com/phense/agentic-rag/issues/75), after existing68 entries
LOW-011/012. Provider guidance now states20 seconds per process/up to40 seconds
for Codex; configured and effective teams are separately shown. The Chromium
team-display assertion was observed red before correction.

The corrected API/browser/security/upgrade selection passed **46 tests in128.16s**,
exit0. Three durable reviewer-derived whole-feature integrations passed **3 tests
in14.47s**, exit0: first-admin→enroll→restricted source-backed retrieval with
zero automatic admin knowledge rights; abrupt policywriter exit73→new API→audit
recovery→secret replay rejection→explicit rotate/revoke; and known/unknown digest
recovery decisions. No real provider/private data entered these tests.

The corrected source was synchronized to the owned Hetzner service from a
626-file snapshot, manifest SHA-256
`f864e561ce37cb46974ea2f50e103cd6c59f9354dc4b028120e67f049f9397e7`.
The already-applied unreleased025 copy received only the corrected new-table ACL
block; original tables and existing user credentials were retained. A dedicated
zero-knowledge read-only probe key is stored privately. This host cannot resolve
its own Tailscale DNS name, so its file-owned compatibility target explicitly uses
loopback8769; the actual external HTTPS path is independently exercised by the
local Chromium client.

The first new cloud probe correctly refused the unresolved target; it is not
counted as a passing compatibility test. After correcting the operator-owned
URL, actual HTTPS login/cookie/scoped library/admin/5 real synthetic checks/
completion/reload/logout passed with zero JavaScript errors. After another owned
API restart, all5 verified checks and completed setup remained, with scoped reads
and logout working. Canonical worker remains inactive and its cutover marker
absent. Two new40-session read soaks completed:2,400/2,400 each,66.41s then63.76s, with zero private memories/model calls and exactly unchanged657,053,363-byte database allocation in both. Both peaked at6 database connections including the sampler. In the second warm run, API PSS was62,794,752→64,687,104 bytes (61.7MiB peak,1.8MiB rise), with1,458 retryable429 responses and5.429s p95 including retries. These finite samples do not establish a latency SLA, multi-day stability or simultaneous extraction/model saturation. Final full-suite exit remains pending; earlier measurements retain their stated revisions and limits.

## Measured before/after examples

1. Previously CLI-only administration now has4 real-browser acceptance flows
   covering scoped knowledge/mobile, enrollment/setup and first-admin bootstrap;
   the integrated first-admin sees0 documents without grants while the enrolled
   restricted reader sees exactly2 permitted documents and the original quote.
2. Populated024 upgrade retains301,183/301,183 original rows across28/28 tables,
   with hashes/ACLs/history/sequences checked by strict backup/restore; only3 new
   dashboard control tables are added.
3. Policy-race probe changes from logout200 followed by unauthorized apply200 to
   apply401 with unchanged file; the separate live concurrent case serializes
   authorized apply before logout200. These are correctness observations, not
   latency or inference-quality gains.


The round1 corrected wheel built successfully: SHA-256
`8b78c2f5860a92cfecb755c504c9845b005cfbdbc57bd7d645a795ccd92fd9cd`.
All7 OpenCode Node checks, JavaScript parse and offline lock consistency pass.
Clean-wheel bootstrap/native-package smoke previously passed on the reviewed
baseline; the later final clean-wheel reinstallation/smoke below now closes that gate.
The updated operations/reference set was rendered with Pandoc and exercised in
Chromium; all122 checked local links resolve. The set was rerendered after those sentence edits; final documentation acceptance remains a coordinator check.


## Review2 and final correction gate

Whole-feature review2 covered all54 changed files at tree
`72bf46b2cd485c0d18d8eda2a94cb5e933a070fa`. It independently confirmed all
original H1/M1/M2 and LOW-013/014 corrections, with139 passing cases including
all four setup modes, final-clock expiry and credential drift during discovery.
It found1 additional Medium: a limited SQL role directly owning a dashboard
control table still passed validation. New nine-case regressions first failed
for reader/writer/admin ownership of each of the three control tables; they
also prove actual SQL authority and require actual API-start refusal.
Validation now checks all effective privileges of these known limited roles,
covering direct owner, inherited authority and accidental elevation, alongside
arbitrary-ACL/owner-membership checks. The affected security selection passed
23 tests in41.56s, exit0.

The new Low search-filter inconsistency is preserved as LOW-015 in Issue75.
Its explicit browse-only selection/reset behavior is covered by a real browser
red-green test; no partial first-page post-filter or core search contract was
introduced. The corrected baseline full-r3 **completed:1,553 passed/1 skipped/
1 upstream warning,1,413.45s, exit0**. That run predates the final ownership/UI
corrections, which need their own final full-suite and independent round3.
No baseline result is substituted for those final gates.


Coordinator follow-up also reproduced column-only grants invisible to table-level
privilege checks:3 additional failing assertions, then a catalog column-ACL fence.
This remains the same owner-only control-state boundary; no historical grants are
changed. Known-role direct ownership, arbitrary/group grants, owner membership
and column-specific privileges all fail closed. Four real-browser tests now pass
in33.55s, including visible browse-only pending-filter reset/re-enable behavior.
The three additional independent round2 clock/discovery/all-four-mode scenarios
are retained as repository tests (10 selected review regressions pass28.57s).


Final correction selection: **29 passed in55.61s**, exit0, covering the expanded
control-role/column-ACL guards plus existing hardening/review regressions.
Current clean-installed wheel SHA-256:
`52f092a1972f463f0bf02fc18e8d122c544da73ee32e5fb79c2a00cc8b9ed358`.
It passes actual isolated bootstrap/login/scoped read/logout, all25 migrations,
all3 packaged assets and fresh Claude/Codex/Gemini install+doctor checks. JS parse
and offline lock consistency also pass. No optional browser dependency enters
the production environment.

The final backend/UI was resynchronized and every626 deployed file digest
verified against snapshot manifest
`867d605b324aa46592c4030d82c98268746477bb5c26ff4462638547dbc36c46`.
The owned copy passes the strengthened startup schema guard. A fresh real HTTPS
browser run passes session/cookie/scoped-empty-library, the pending-filter
reset/re-enable behavior,2 newly executed DB/permission checks,3 retained actual
model/target observations, completion/reload and logout with zero JS errors.
It makes no new model call and does not silently substitute cached results for
the2 newly executed metadata checks. Canonical deployment and credentials are
unchanged. The final serial full-suite command is running; its actual exit remains a delivery gate. Independent round3 is complete below.


## Final independent review and acceptance mapping

Third and final whole-feature Sol-high review inspected all54 changed files
(+3,125/−56) against base `29ec9d54a15ab3d1227cddc59bc58ab9cd2c5333`,
frozen tree `2672feef4b46f391db20ce41aa59733ee3df6a49`.
It reports **0 Critical / 0 High / 0 Medium / 0 feature Low**. All626 source-file
blobs/modes and the index matched the reviewed tree. Later source changes are
limited to documentation and delivery state; no runtime/test correction follows
that review. Unrelated LOW-012 remains open in cumulative Issue75.

The independent serial selection passed **152 tests in221.90s**, exit0;
six additional private role/column probes passed **6 tests in12.29s**, exit0.
Those probes demonstrate real `SET ROLE` audit/setup/presence changes through
NOINHERIT owner membership or column-only group grants, then require both schema
validation and actual API startup to refuse that state. No real model or private
source content entered this review. Its PostgreSQL instance was stopped.

The152-case command used the isolated review port55459, private socket plugin,
TMPDIR and browser-library environment:

```sh
.venv/bin/pytest -q --tb=short -p no:cacheprovider -p review_socket \
  --basetemp="$TMPDIR/selection" tests/service/test_dashboard*.py \
  tests/browser/test_dashboard_browser.py tests/service/test_upgrade.py \
  tests/service/test_client.py tests/service/test_queued_client.py \
  tests/service/test_review_regressions.py tests/benchmark/test_corrections.py \
  tests/test_embed.py tests/test_plugin_packages.py tests/test_plugin_lifecycle.py
```

The private `review_socket` plugin redirects implicit sockets and restore DSNs
to the owned cluster; its environment, full output and exit are retained with
the review report. The158 independent cases are targeted proof, not the root suite.

| Requirement | Observable acceptance evidence |
|---|---|
| AC/FR001; IC01/02 | Concurrent bootstrap200/409, existing-policy closure; real Chromium first-admin flow; no default password or automatic knowledge grants |
| AC/FR002; IC01 | Actual HTTPS safe cookie, Origin/CSRF/expiry/logout tests, exact-session commit fence, cookie-only v1=401, machine-key browser login denied |
| AC/FR003–004; IC04 | All four modes with real DB/permission/HTTP discovery, interrupted-state resume and idempotent completion; synthetic model checks; existing data refuses fresh setup |
| AC/FR005; IC02 | Revision-checked preview/apply, once-only secret, last-admin guard, exit73→restart prepared-journal recovery, replay409 and revoke401; unsafe owner/table/column authority refuses API startup |
| AC/FR006; IC05 | Configured/effective rights and enabled/revoked versus freshness tests; bounded presence and safe version/capability metadata |
| AC/FR007; IC03 | Admin total0 versus restricted reader total2, exact original quote, absent foreign detail and RO review403; mobile/keyboard/browser search/pending-filter flows |
| AC/FR008 | Populated024→025 strict restore/upgrade/retry,301,183 original rows/28 tables preserved with original ACL/history/sequences; legacy REST/MCP/local/plugin regressions and installed-wheel smoke |
| AC/FR009 | Four Chromium flows and two corrected40-session/2,400-read cloud soaks; bounded memory/SQL/response admission, single fenced extraction worker and existing foreground queue |
| PB05901/02; AF05901..03 | Operator labels/commands/prerequisites/content inspected across all three reviews; owned-copy setup/restart, bootstrap/enrollment/source success and real process-crash/drift recovery rehearsed; as-built model reconciled |

These establish feature/copy acceptance, not canonical migration, multi-day
stability, simultaneous extraction/inference capacity or a latency SLA. Final
full-suite command/exit and documentation synchronization follow separately.


## Final serial full-suite result

Completed **1,569 passed / 1 skipped / 1 upstream warning, 1519.93s, exit0** at `2026-10-30T09:43:35Z`. The full output was
read after the actual exit artifact appeared. This is the final runtime/test
candidate reviewed at tree `2672feef4b46f391db20ce41aa59733ee3df6a49`;
subsequent changes only reconcile documentation/delivery state. Earlier pending
statements above describe their historical gate and are superseded by this result.

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE \
  PGPORT=55458 PYTHONDONTWRITEBYTECODE=1 \
  LD_LIBRARY_PATH="$SCRATCH/browser-libs/usr/lib/x86_64-linux-gnu" \
  TMPDIR="$SCRATCH" RAG_BROWSER_ARTIFACT_DIR="$SCRATCH/browser" \
  .venv/bin/python -m pytest -q --tb=short -p no:cacheprovider
```

`SCRATCH` denotes the private rehearsal directory. The one skip is the Linux
host's macOS/launchd-only installation test. The warning is the existing Starlette
TestClient/httpx deprecation. Log SHA-256:
`2e0fd86a67a04370921a7dc3e38893dd9e66fabe8a9bd0ef432e7cf6bc8cbe19`.

Current clean-wheel SHA-256 remains
`52f092a1972f463f0bf02fc18e8d122c544da73ee32e5fb79c2a00cc8b9ed358`;
production dependencies are unchanged. The seven OpenCode Node tests, JS parse,
45-package offline lock check and122 relative documentation links pass. The
operations/reference HTML was rendered with Pandoc, opened in Chromium and
visually inspected. Glossary table/JSON contain the same 10 entries; the two
reader-facing chunks contain zero avoid-term variants. Architecture semantic
source review and all AF05901..03 dispositions are complete.

Review, requirement/interface mapping, success/recovery integrations, playbook
content/rehearsal and current verification agree. No implementation gap remains.
Merge approval and canonical rollout stay separate; no writer cutover is included.


## Delivery

[PR79](https://github.com/phense/agentic-rag/pull/79) contains this0.6.12 feature
on the0.6.11 promotion branch from PR78. Merge PR78 first, then retarget PR79 to
main. Runtime/tests remain byte-identical to the final reviewed/full-tested
candidate; final convergence edits only documentation and delivery state. Final
documentation synchronization has its own private626-file manifest/receipt;
its hash is kept outside that manifest's input to avoid a self-referencing hash.
The test-copy credentials remain unchanged. No canonical worker was enabled.
