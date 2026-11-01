---
id: V-067
title: Extraction policy verification
type: reference
doc_id: standalone
readers: [maintainer]
status: accepted
version: 0.6.20 (schema032)
depends_on: [../extraction-policy.md]
assets: []
last_reviewed: 2026-11-01
summary: Independently accepted extraction-policy implementation; final full suite 2151 passed with unchanged sources, populated 0.6.19 upgrade/retry/restore verified. Production rollout remains separate.
---

# Extraction policy verification

## Overview

[Issue67](https://github.com/phense/agentic-rag/issues/67) adds a versioned,
file-configured extraction policy for session mining. Source is
0.6.19/schema031 (`01bc13b`); the target is 0.6.20 with additive migration032.
This record covers implementation and independently accepted integration on
`feat/extraction-instructions-67`. The final full suite passed at `d0fe52e`; convergence found no additional
blocking work. The sections below retain evidence in revision order; earlier
pending statements describe their historical stage, not the latest review.

## Commits

| Commit | Task | Content |
|---|---|---|
| `ad256e7` | T067-001 | Frozen EN/DE fixtures, policies and labels with checksums, before product code |
| `a8b63ec` | T067-002 | `extraction_policy.py` strict v1 file, precedence, identities, bundles; `[mining] policy_file` |
| `347894c` | T067-003 | Migration032 bindings (immutable, RLS, grants), `mining.bind_policy`, schema/upgrade allowlists, 0.6.19 source |
| `a29ad62` | T067-004 | Admission capture (local and central), binding before the provider, enforcement on eight channels |
| `3e221de` | T067-005 | `rag extraction validate|inspect|dry-run`, shared `validate_source` |
| `47e7bf8` | T067-006 | Populated 0.6.19 → 0.6.20 upgrade rehearsal with actual old code |
| `048a9f8` | T067-007 | 0.6.20 version, reference doc, PB-067-OPS and its rehearsal, measurement script |
| final docs commit | T067-007 | Measured results, this record, playbook evidence sidecar, task checkboxes |

## What was measured, and what was not

The [measurement](../benchmarks/2026-11-01-extraction-policy/README.md) runs
seven frozen cases three times through actual mining with a mock provider at
`048a9f8`. All deterministic outcomes were identical and matched the frozen
labels. Three before/after examples:

1. R1 (EN): without a policy the batch kept 1 memory, 1 lesson and 1 signal; with
   policy A it kept the 1 decision memory, dropping the abandoned-experiment lesson
   and the error signal (`category_disabled`). 1 provider call either way.
2. D1 (DE): 2 memories, 1 lesson, 1 pin suggestion and 1 domain proposal became
   1 memory and 1 pin suggestion (`item_limit`, `body_limit`, `category_disabled`).
3. P1: after a provider outage and a file replacement, the retry used the
   admitted digest without reading the file (2 provider calls until acceptance,
   0 on replay, replay 4.00–4.43 ms); a new admission took the new policy.

Not measured: real-model extraction quality or guidance adherence. Case L1
records that an abandoned experiment labelled as an allowed memory is kept.

## Populated upgrade and recovery

`tests/service/test_extraction_policy_upgrade.py` (store written by the actual
0.6.19 code, 177 original rows in 47 tables): interrupted migration032 rolled
back; verified upgrade applied `032_extraction_policy.sql` in 2.67 s; empty
retry; original rows (including queue, batches, windows, lifecycle tables),
`ev1`/`src1`, grants, owners and sequences unchanged; 0 provider calls by the
upgrade; 0.6.19 reads identical and ordinary writes working on schema032 before
and after bindings; the old pending job mined under builtin rules although a
custom file was configured; the old accepted batch applied unchanged without a
file read and without a binding; a 0.6.19 miner kept 2 categories the captured
policy disables (activation gate required); post-upgrade backup restored with
its binding and trigger; pre-upgrade restore loses later writes.

## Requirement dispositions

| ID | Disposition | Evidence |
|---|---|---|
| AC-001 | Implemented | `tests/test_extraction_policy.py` (strict v1, bounds, codes/locations, identity) |
| AC-002 | Implemented | frozen `effective` labels, `rag extraction inspect` test |
| AC-003 | Implemented | `tests/test_extraction_cli.py` (0 calls/0 writes by default; explicit `--evaluate` 1 call, 0 writes; redaction) |
| AC-004 | Implemented within stated limits | eight-channel enforcement test, unchanged grounding in fixtures S1, L1 semantic limit |
| AC-005 | Implemented | binding-before-provider, retry/continuation/replay tests local and central |
| AC-006 | Implemented | legacy job/window tests, accepted legacy batch test, upgrade rehearsal |
| AC-007 | Implemented | shared validator, service-owned central capture, per-admission read, bind audit with digest only |
| AC-008 | Implemented | no re-mining command; replay tests; prospective rollback in PB rehearsal |
| AC-009 | Independently accepted and full-suite verified | upgrade rehearsal, PB-067-OPS rehearsal, activation gate |
| AC-010 | Accepted: fixtures, measurement, independent review and full suite | final gate below |
| AF-067-001..008 | Addressed in S1 as mapped in tasks.md | see the slice report |

## Deviations and limits

- Review M1 rejected cross-job binding reuse. New admissions with conflicting
  effective rules or bound projects now fail before the provider; wrong-project admitted
  captures are invalid. Bindings and failed jobs remain intact. Direct retries
  keep their original policy only within the original project.
- A malformed central snapshot ends the receipt as `error`/`processing_failed`
  (no dedicated public code); the local job records `policy_snapshot_invalid`.
- The binding audit adds one `audit_log` row per newly mined cursor; one earlier
  test that counted exactly one acceptance row now names both rows.
- `rag service job-retry` and PB-063 R1–R4 were not executed end to end in the
  playbook rehearsal; the central retry path is covered by service tests.
- The `PYGATE` rehearsal has one-second start-time resolution and can flake
  under load (observed once on the existing PB-065 rehearsal).

## Verification run

Serial targeted and affected suites at `048a9f8` (66 test files: all new RAG-067
tests plus mining, jobs, worker, hooks, ingest, source worker, queue, authority,
schema, every earlier upgrade and playbook rehearsal, backup/restore, store,
evidence and MCP): **626 passed, 0 failed, 1 known warning
(`StarletteDeprecationWarning`), exit 0, 703.78 s** on PostgreSQL 17.10, port
55460. The root full suite, Node, packaging and browser gates are pending at root.

## Coordinator corrections before independent review

At `115ea50` four new regression cases failed for two Medium boundary defects:
CLI sample preparation collapsed exact source whitespace and forwarded secret-like
source IDs/timestamps; validation error locations echoed unknown TOML keys even
when they contained a recognizable credential. The coordinator preserves sample
wording, validates sample metadata without echoing values, and redacts/bounds error
locations. Four reds then **44 passed**, exit0 (safety, policy and public CLI
suites),4.25s. Logs: owned `root-safety-red.log` / `root-safety-green.log` under
`/dev/shm/rag67-20261101-tests/logs/`. These are targeted checks; full verification
and independent acceptance remain pending.

The coordinator also reproduced refusal of a truthful current-release backup:
`verified_backup(..., '0.6.20', ...)` failed with `unsupported_source_version`.
Supported sources now include0.6.20; the post-upgrade backup/restore procedure
records that actual version. Future0.6.21 remains unsupported. The new real
backup/independent-restore case and affected schema, PB-067, lifecycle and synthesis
upgrade tests passed together: **13 passed**,1known warning,exit0,108.16s.
Earlier evidence of0.6.20 refusal describes the pre-correction source only.

## Independent-review correction (M1 and PB-I1)

Four new regressions reproduced cross-job policy override, project changes and a
validly hashed wrong-project capture. The correction rejects a conflicting new
admission with extraction_policy_conflict before any provider call, batch or
cursor advance; an invalid admitted project is policy_snapshot_invalid. Failed
jobs and the original binding are retained. Direct same-project retries still
reuse the original binding without reading the file. Queue tests also resume
under the original policy/project without modifying either failed job.

Affected verification:35passed,1known Starlette warning,exit0,30.62s
(root-review-conflict-green.log). This covers local mining, binding schema,
central admission/retry/scope and PB-066 populated upgrade/restore. The PB-066
future-version refusal now uses0.6.21, since0.6.20 is supported by this release.
Full1 failed on a stopped test database; full2 was interrupted for these code
corrections (445passed,1stale-test-expectation failure). Neither is a full pass.
Independent correction review and a source-bound final full suite are pending.

The changed PB-067 commands and documentation continuity check were also
rehearsed after the correction:18passed,1known warning,exit0,15.92s
(root-review-pb-docs-green.log). Nonblocking findings LOW-050..055 are tracked in
[Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6553145423).

## Domain-set correction (CM1 / PB-CI1)

The independent correction review rejected 624dce6: full-bundle comparison could
strand builtin retries after domain additions or permission revocations, and
unchanged-file recovery after adding a domain. The comparison now checks
common-domain and domainless effective policy hashes; legacy retries require a
builtin binding. Project checks, immutable binding and current-authority
intersection remain. Newly available domains are not added to an existing
binding. C2 distinguishes compatible domain-set changes from rule conflicts.

Focused regressions reproduced three failures (local builtin retry, unchanged
file recovery, central builtin retry) and one passing captured-policy control.
After correction 41 affected tests passed,1known warning,exit0,19.61s. Three
additional negative cases protect real common-domain rule changes, domainless
rule changes and custom-to-builtin conflicts. The test harness initially reused
a module-scoped central session and then duplicated earlier fixture content;
unique session/source text corrected those test-only assumptions. Original
failed logs are retained, not counted as product evidence. Full3 was interrupted
on unchanged624dce6 for this repair and is not a pass. Independent focused
acceptance and final full-suite verification remain pending.

### Post-CM1 evidence at e88717f

- Actual PB-067 populated upgrade/restore plus upgrade preservation and docs
  continuity:19passed,1known warning,exit0,36.88s.
- Coordinator rerun of the unchanged prior independent correction script:
  37/37 checks passed,0errors; own databases cleaned. This reuses the probe
  design but is not an independent review. Its prior failed artifact is retained.
- Frozen EN/DE measurement:3repetitions,all labels matched,identical deterministic
  outcomes; new raw observations in results-final.json preserve the first run.
- Node adapter:7/7,exit0. Offline lock check:55packages,exit0.
- Built wheel:191entries,186source payloads byte-identical,32SQL migrations.
  SHA256953cf5f60c3e3716690cde5dea2271590abbc54af71684c44512c47d57c26814.
  Import from the extracted wheel on a new owned database passed schema
  validation and durable binding; the database was dropped after the smoke test.

No full-suite pass or independent acceptance is inferred from these checks.

## Independent acceptance before final full4

Reviewed source `eadd2e5`, product fix `e88717f`:0Critical/High/Medium and
0Important. The final independent probes passed36/36 with0errors, including
builtin/captured retries through domain addition and revocation, original
binding preservation, real effective/domainless/project conflicts, conditional
recovery and accepted-batch replay. Only provider output was mocked. Previous
full-slice evidence is inherited only for unchanged paths. Test-strength Low
LOW-056 stays in Issue75; LOW-057/058 wording/typography is corrected.

The final full-suite gate remains open. The public review summary is
[issue67-extraction-policy-review.json](issue67-extraction-policy-review.json).
No production, TLS, systemd, macOS, multi-host or model-quality claim is made.

## Full4 diagnosis and test-only correction

The complete run at `ad937dd` ended with exit 1: 2,148 passed, three failed,
one skipped and the known Starlette warning. All 385 source hashes remained
unchanged. Two failures were obsolete assertions rejecting current-release
backups, although the independently tested operator path supports 0.6.20.
The third was reproduced with a process launched 1.200 seconds after the
installation marker: `ps` rounded its start time back before the marker.
The test now leaves 2.2 seconds between installation and restart; the same
mechanical correction applies to the PB-065 and PB-066 rehearsals. The
production process gate, policy code and SQL are unchanged.

All five affected test files passed together: 26 passed, one known warning,
exit 0 (104.90 seconds). Coordinator review covered the complete mechanical
test diff. Independent product acceptance remains at `eadd2e5` / product
`e88717f`; it does not stand in for the pending source-bound full5 run.

## Final acceptance at d0fe52e

The source-bound full5 run completed on 2026-11-01 at 05:49:43Z: **2,151 passed,
one skipped, one known Starlette deprecation warning, exit 0**. Wall time was
2,396.37 seconds. All 385 product, SQL, test, asset and package metadata hashes
matched before and after the run and still match this documentation-only update.
Raw terminal and populated-upgrade results are published in
[issue67-extraction-policy-final.json](issue67-extraction-policy-final.json).
The log SHA-256 is
`60b39be53788409caa2fe7746576c20c0691ec89d4745770a2a89d74fc543660`.

The actual archived 0.6.19 source (`01bc13bd`) upgraded from schema031 to032 in
2.50 seconds. All 177 original rows across 47 tables, source/evidence versions,
pending/accepted work, grants, owners and sequences were preserved. Migration
interruption, retry, old/new reads and writes, and post-upgrade restore passed.
Upgrade invoked no provider. Old miners ignore custom policies: stop or upgrade
all such processes before activating a file. A pre-upgrade restore loses later
writes; prospective file rollback preserves already bound work.

Convergence checked AC-001..010, IC-001..005, AF-067-001..008, as-built boundaries,
independent success/recovery and playbook acceptance against this exact evidence.
There are no open Critical/High/Medium or Important findings. Nonblocking follow-ups
remain in Issue75, including file-replacement activation auditing (LOW-054) and
the isolated domainless test-strength gap (LOW-056). Node, lock, wheel and three
frozen EN/DE repetitions remain applicable because their product inputs did not
change. This accepts the implementation and upgrade path; it does not authorize
or demonstrate a production rollout or real-model extraction quality.
