---
id: V-065
title: Pattern synthesis verification
type: reference
doc_id: standalone
readers: [maintainer]
status: accepted
version: 0.6.18 (schema030)
depends_on: [../pattern-synthesis.md]
assets: []
last_reviewed: 2026-10-31
summary: Frozen-fixture pattern-synthesis measurements, populated 0.6.17 upgrade/recovery and independent acceptance for Issue65; full-suite acceptance and coordinator correction evidence are recorded below.
---

# Pattern synthesis verification

## Overview

[Issue65](https://github.com/phense/agentic-rag/issues/65) adds opt-in pattern
synthesis: source-linked, reviewable inferences over several original memories.
Source is 0.6.17/schema029 (`81beaf6`); the target is 0.6.18 with additive
migration030. This record covers the implementation slice (S1) and the
review-driven corrections (S4/S5). Independent review through `73ddd02` is
accepted with no open Critical/High/Medium or Important finding. The final full test suite at `ea6697b` passed: **1,974 passed, 1 skipped, 1 known warning**, exit 0 in 2084.56 s; all 355 source hashes stayed unchanged. [Machine-readable acceptance](issue65/acceptance.json) retains the review and correction boundaries.

Terms: a *pattern* is a stored inference with exact citations. An *independent
event* is a distinct user report after merging same-source and same-text quotes.
The *floor* is three independent events across three memories. *Oracle* answers
are honest scripted model answers; *adversarial* answers try to over-claim,
contradict or escape the output contract. A *non-conclusion* is a run that ended
without a pattern, with a reason.

## What was measured, and what was not

The [harness](../benchmarks/2026-10-31-pattern-synthesis/measure.py) ran the real
preview, scheduler, worker drain, validation, audited application and guarded
reads on product revision `8d9043e` (clean tree, after S4), three repetitions,
PostgreSQL 17.10, Python 3.13.13. Every outcome, count and provider call equals
the earlier run at `3860576`. The provider boundary was replaced by frozen scripted answers.
**These numbers describe how the pipeline handles honest and dishonest output.
They are not a model-quality result; no real model was called.** An optional
real-model run on the synthetic fixtures was not performed.

Fixtures were frozen in `84bce47` (2026-10-31T17:30:15Z) before product code:
35 synthetic rows in 10 cases, 10 scripted answers, labels for 15 evaluations
(11 development, 4 held-out). Hashes: `corpus.json` `8b238817…38d8d7081`,
`responses.json` `4cd4fb6b…190244afb76`, `labels.json` `d7fbcff3…a88901dc4`.

## Results

The frozen labels call citation-valid parts `supported_parts`; that historical field
is interpreted as cited parts when checking the unchanged labels. The revised
measurement reports semantic support separately, using a published human review
of the frozen answers and quotes. C2 contributes one cited but unsupported part;
none of these counts establishes actual-model accuracy.

| Measure | Value |
|---|---:|
| Evaluations matching the frozen label | 14 of 15, plus 1 recorded label erratum |
| Patterns applied (honest K1, K2, I1; adversarial C2) | 4 |
| Cited parts in applied patterns | 8 |
| Semantically supported parts (human inspection) | 7 |
| Semantically unsupported parts (C2, human inspection) | 1 |
| Rejected suggestions | 3 |
| Non-conclusions | 11 |
| Provider calls (all below-floor cases: 0) | 9 |
| Outcomes identical across 3 repetitions | yes |

Median timings: preview 22.9 ms, schedule 33.2 ms, drain 83.3 ms (includes the
scripted call), inspect 22.9 ms (at `3860576`: 15.6, 18.9, 45.5, 14.9 ms; the
scheduler now fits the budget and looks up context, and the box was shared).
Prompts carried 1,041 to 1,412 characters.

## S4 correction: forward processing

Review findings R65-02, R65-03 and R65-06 showed that forward synthesis could
lose originals: a 60-second settle window plus an advancing cursor skipped a save
whose transaction committed late, an over-budget batch was consumed without a
call, and observations arriving in different runs never met. S4 replaces this
with processed membership per enable epoch, a budget fit before any run and a
bounded window of recent context (contract *Forward processing*). Each behavior
was first observed failing on the earlier code, with real simultaneous database
connections where it matters (`tests/test_synthesis_forward.py`):

| Regression | Before S4 | After S4 |
|---|---|---|
| Save in a held-open transaction, committed after 3 later originals were analysed | never pending, never analysed | `pending 1`, analysed as new in the next run |
| 12 quotes of 1,100 characters, default 12,000-character input | run ends `input_budget_exceeded`, all 12 consumed, no call | first run analyses the fitting group, the rest stays pending and runs next |
| Two DNS reports in run 1, a third in run 2 | run 2 sees only its 3 new memories: no pattern | run 2 adds run 1's memories as context: pattern citing all three |
| Policy disabled and re-enabled during the provider call | `non_conclusion` recorded | `withheld policy_changed`, nothing consumed |
| 6 excluded rows ahead of 3 eligible, scan bound 5 | eligible rows starve | the rotating scan reaches them on the next tick |

These are pipeline tests with an in-process scripted provider, not model quality.

## Inspected examples

| Case | Model answer | Outcome | Why |
|---|---|---|---|
| K1, honest | "VPN reconnect clears the DNS suffix list", medium confidence | Applied as unreviewed inference; parts cite 3, 3 and 1 memories; 4 events in 4 memories | Floor met, every citation offered, no contradiction |
| C1, adversarial | "Dedup causes backup overruns", citing "was not the dedup job" as support | Non-conclusion `conflicting_support` | A supporting and a contradicting quote on one suggestion |
| I1, adversarial | Adds `kind: stated`, another domain and scope, cites an unoffered id | Non-conclusion `invalid_output`, no retry | Fails the strict output schema |
| C2, adversarial | "Port 8443 is blocked", marking "8443 is open" as supporting | **Applied** | Known limit: a lying stance is not detectable by the validator |

The F1-adversarial label expects one provider call, but below the floor the
contract forbids any call. The harness validates the frozen answer directly
instead; outcome, reason and applied count match. The label stays unchanged
and the erratum is published in `results.json`.

## Compatibility and recovery

Rehearsed on owned copies (`tests/service/test_synthesis_upgrade.py`,
[evidence](../benchmarks/2026-10-31-pattern-synthesis/compatibility-evidence.json)):
the archived 0.6.17 code populated 302 rows in 39 tables; the upgrade applied
only `030_pattern_synthesis.sql` in 2.44 s (final full run at `ea6697b`; earlier `8d9043e`: 1.61 s) with verified restore and unchanged
original rows; the retry applied nothing; no policy, run, job or pattern existed
afterwards. 0.6.17 reads were identical after the upgrade. 0.6.17 local writes
and its central API worked on schema030 while no pattern existed. Accepted work
survived a verified backup and restore and was recovered without a second
provider call. After a pattern existed and its policy was disabled, 0.6.18
withheld it while actual 0.6.17 get, evidence and history still served it: the
recorded verdict for a code-only rollback is `forbidden`. A pre-upgrade restore
loses later writes, as documented.

## Playbook rehearsal

PB-065-OPS parts A–D were rehearsed on owned databases through the real CLI and
the central worker loop; details in the
[review and evidence record](../playbooks/system/rag-065-pattern-synthesis-review.md).
The rehearsal found one documentation error (empty backfill windows close
without a run), corrected before commit. After S4 the rehearsal also runs the B0
reader-gate snippets against a deliberately stale process and recovers a parked
run through a writer's central client CLI, the REST API and the central worker
with one provider call.

## Defects found and fixed during S4

- `tests/service/test_reranker_upgrade.py` still expected 29 applied migrations
  after an upgrade; since migration030 there are 30. Found by the S4 serial run of
  affected suites, corrected; the file then passed (2 tests).

## Remaining correction after independent S4 review

The independent review at `39b6bd9` resolved the original High and five Medium
findings, but exposed a backfill budget defect (N1) and a hardlink-installation
gate defect (PB065-R07). The coordinator reproduced both before fixing them:

- Three 600-character originals and a 2,100-character input limit used to
  create a below-floor run and advance the backfill. The corrected scheduler
  creates no run, preserves the cursor and batch allowance across repeated
  ticks, and exposes `input_budget_below_floor` in JSON and CLI status. Raising
  the budget applies the pattern with one call and closes the backfill. All
  10 forward/backfill tests passed (6.88 s, exit 0).
- A hardlink installed after a reader started retains the cache file's old
  modification time. The old playbook gate falsely passed that reader. Using
  the later modification/change time blocks it; restarting the reader passes.
  The playbook and local-capture suites passed together (8 tests, one known
  warning, 29.77 s, exit 0). The RO proxy now checks the four additional pattern
  reads and rejects the three pattern writes.

The earlier full runs were not accepted. The first
full run was interrupted (exit 2, 997 passed/9 failed): eight browser launches
lacked the existing library search path; one RO proxy test still expected 12
instead of 16 tools. These failures are retained, not counted as acceptance.
With the existing browser-library path restored, all 98 affected browser,
synthesis, transport and upgrade tests passed (223.39 s, one known upstream
warning, exit 0). The six retained Low findings are recorded as
[LOW-038..043 in Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6548367780).

## Independent final acceptance and package

The independent final review at `73ddd02` verified all 60 files against the
manifest, read all 13 files changed since the previous review, and reused the
unchanged earlier complete review and probes explicitly. It found no open
Critical/High/Medium or Important issue. Fresh probes passed **34 of 34
assertions**, covering authenticated waiting status, writer/RO/foreign scopes,
local and client CLI, no consumption across repeated ticks, one-call recovery
after raising the budget, concurrent forward progress, the SQL constraint and
the exact hardlink gate. Four owned databases were created and removed; none
remained. Earlier success/recovery, policy/source/credential changes and atomic
apply probes are reused for byte-identical code; they were not all re-run.

The final review also found a rare liveness limit:
[LOW-044](https://github.com/phense/agentic-rag/issues/75#issuecomment-6548506675).
Three independent large memories can jointly exceed the maximum 24,000-character
input. That backfill stays visibly pending, holds later backfills of the policy
and has no cancel route. Nothing is sent or consumed. The coordinator corrected
the companion Minor documentation finding (PB065-R09) in C1/C9 and the user
guide; the product limit remains deferred in Issue75.

An offline wheel built at `bfeedf0` was verified against `ea6697b` after the test-only fixture correction. Its 184 entries include all **179
tracked Python/SQL/assets files**, byte-identical to source; all Python entries
compile. A smoke process imported the extracted wheel, initialized an owned
schema030 database, verified the nullable waiting field, 16 read-only tools and
default-off empty synthesis status, then removed its database. Wheel SHA-256:
`75569d18793bf078cc8a08301229a8fa19f599f06abcb3ecefbd53de1dcdc390`.

## Defects found and fixed during S1

- The central `rag service worker` loop never scheduled pattern runs; only the
  local hook-started worker did. Fixed with a regression test in
  `tests/service/test_runner.py`.
- Resuming an interrupted central cutover restore (`restore_target --resume`)
  rejected every schema030 target with `target_drift`, because the five new
  `synthesis_*` tables were missing from its allowlist of post-dump tables (they
  must still be empty). Found by `tests/service/test_upgrade.py`; fixed.

## Limits

- No real-model quality figure; synthetic corpus of 35 rows in one domain.
- The validator cannot detect a model that misstates a quote's stance (C2).
- Once a pattern exists, actual 0.6.17 code with direct database access is a
  forbidden boundary: its get, evidence and history serve a disabled pattern
  (rehearsed). PB-065-OPS B0 must pass before the first enable; it cannot find
  hosts that are not listed or not connected.
- Recurrence is found within one run: new memories plus up to 48 recently
  analysed ones of the epoch, within 12 memories and the input limit. Every pair
  of an arbitrarily large history is not compared.
- A memory larger than the maximum input limit (24,000 characters) stays
  `oversized` and is never analysed.
- The curation report (`rag review`) can still list withheld pattern slugs.
- Widely interleaved excluded documents can prevent a sufficient group from
  meeting inside one bounded scan. A failed or withheld run is reconsidered
  only at the next policy interval. A backfill overlapping a parked accepted
  run can pay for the same originals again (code inspection, not reproduced).
  These Low findings are tracked with the other deferrals in Issue75.
- A code-only rollback is supported only before the first pattern; disable every
  policy first, because a 0.6.17 worker cannot process queued pattern jobs.

## Final full-suite correction

The completed run at `73ddd02` returned exit 1: **1,965 passed, 3 failed,
1 skipped, 1 warning**. Two older tests expected eight writer tools instead
of eleven. The third exposed an existing in-place restore defect: table creation
inherited target default grants that the archive did not revoke. The dashboard
schema validator correctly refused the resulting exposed control tables.
The restore/dashboard test pair reproduced this; a strengthened restore test
also observed 87 extra relation privileges. This is not a synthesis read-gate
failure. The correction resets the creating operator's object defaults
inside the restore transaction and commits only after the complete archive
script succeeds. Regression tests compare all relation/default ACLs and retain
post-backup rows on SQL or archive-producer failure. The additional independent review at `c3df902` found two Medium cases that the
normal-schema tests missed: large-object sections emit an internal COMMIT,
and custom function defaults add EXECUTE access to SECURITY DEFINER writers.
The coordinator reproduced both as regression failures, then refused
large-object archives before a target connection and extended the default reset
to functions, types and schemas with their built-in PUBLIC defaults. This
explicitly narrows in-place recovery; large-object data require verified empty-
target recovery. Mid-stream producer/SQL failure tests supplement end-of-stream
failures. The aborted full run at `c3df902` (exit 2, 356 passed, 1 warning) is
retained; the final frozen run at `ea6697b` passed as recorded above.

## Legacy fixture isolation correction

The frozen full run at `bfeedf0` ended exit 1: 1,973 passed, 1 failed, 1 skipped,
1 known warning. The failing dashboard probe now passed the restored ACL
checks, but found `mining_batches` without its later RLS/policies. An old
migration test had dropped that table and reapplied009 in the shared current
database. The exact migration-test→dashboard sequence reproduced the failure.
The coordinator moved the real008→009 test into an owned database with just
those migrations, retaining queue preservation and idempotency checks.
Production code, SQL and the accepted restore correction remain unchanged.
The final full run at `ea6697b` passed; the earlier failed run is retained.

## Final verification and delivery boundary

The restore correction at `bfeedf0` passed all **119** targeted backup/synthesis/
research/thematic tests (exit 0, 65.25 s), with all 355 source hashes unchanged.
A coordinator adaptation of the independent restore probes passed **28/28**
assertions, including no target connection on large-object refusal, unchanged
large-object bytes and original/default/function ACLs, and mid-stream failures.
All six owned probe databases were removed. This is coordinator correction
verification, not another independent run; the complete 16-file independent
restore review at `c3df902` and its 23/26 result remain preserved, with M1/M2
explicitly resolved by these corrections.

The final full suite passed 1,974 tests, skipped one macOS-only launchd test and
reported one upstream Starlette/httpx deprecation warning (exit 0, 2084.56 s).
Seven Node adapter tests pass; the offline lock check resolves 55 packages.
The test-only legacy fixture correction passed 32 tests; the final full run uses
the isolated fixture. Product and SQL files are unchanged from `bfeedf0`.
All 179 wheel payload files match source. Relative documentation links and the
exact 0.6.17→0.6.18 patch bump were checked. The full log digest, source binding,
package hash, current populated-upgrade proof and retained failed/interrupted
runs are in [acceptance.json](issue65/acceptance.json).

A separate same-owner, synthetic empty-target recovery using `pg_restore --single-transaction` preserved the original row, large-object bytes and function ACLs; the owner-control schema validator passed. Both owned databases were removed. This proves the documented fallback on PostgreSQL17/Linux, not a live cutover or complete production large-object inventory. Its first probe had a setup-assumption error about seeded domains; the corrected check compared the full source domain inventory and passed. Both attempts are retained.

[PR88](https://github.com/phense/agentic-rag/pull/88) is ready for maintainer review. The merge decision remains separate. No live store, service, model or
client was changed. Production use still requires PB-065-OPS, all-reader
restart, an explicitly enabled policy and the documented recovery boundary.
