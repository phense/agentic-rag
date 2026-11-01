---
id: V-066
title: Memory lifecycle verification
type: reference
doc_id: standalone
readers: [maintainer]
status: verified
version: 0.6.19 (schema031)
depends_on: [../memory-lifecycle.md]
assets: []
last_reviewed: 2026-11-01
summary: S1 implementation evidence for Issue66 - frozen-fixture measurement, populated 0.6.18 upgrade and recovery, PB-066-OPS rehearsal, defects found and fixed, deviations and limits. Independent review, populated upgrade/restore and full-suite acceptance are verified; production rollout is separate.
---

# Memory lifecycle verification

## Overview

[Issue66](https://github.com/phense/agentic-rag/issues/66) adds source-preserving
lifecycle decisions: duplicate, extension, replacement and contradiction between
two original memories, recorded as an audited overlay that never edits the
originals. Source is 0.6.18/schema030 (`d4d2372`); the target is 0.6.19 with
additive migration031. This record covers the implementation slice S1
(T066-001..009) on branch `feat/memory-lifecycle-66`. The first independent review (S2) found blockers at `1fc0628`; correction review at `4a7f925` accepted the fixes. The source-bound full suite
passed 2,063 tests, skipped one macOS-only test and reported one known warning,
exit 0. All 371 source hashes were unchanged. [Machine-readable acceptance](issue66/acceptance.json).

## What was measured, and what was not

The [measurement](../benchmarks/2026-10-31-memory-lifecycle/README.md) runs the
real gateways, preview, apply/correct, SQL views, lexical search and both
curation versions on 45 hand-labelled synthetic documents, three repetitions at
`4a7f925` after correction review. It is deterministic and calls no provider. It does not measure
semantic accuracy, operator judgement or any model; sustained real-model use
(#21) stays open.

## Results

| Measure | Result |
|---|---|
| False merges by automatic curation | 0.6.19: 0; actual 0.6.18: 1 (T1, different titles) |
| Same-knowledge pairs left for operator review by 0.6.19 curation | 2 (T2 type differs, T3 title differs) |
| Preview checks / view checks / transition checks against frozen labels | 31/31, 32/32, 8/8 in every repetition |
| Original rows of 11 source tables and every `ev1` after all decisions | unchanged |
| Opposing concurrent applies | one decision; the other `stale_version` |
| Replay with new request key / key with other payload | same decision / `replay_mismatch` |
| Injected audit failure, reader-role apply | no decision, event or audit row |
| Provider calls | 0 |
| Lexical search, fixture corpus, before / after decisions | 47.4 ms / 65.6 ms (median of run medians) |
| Worst case, 300 merged members matching one broad query | 322.7 ms / 814.4 ms |

## Inspected examples

From `results.json` → `examples` (first repetition, ids replaced by fixture keys):
E1-copy is hidden by an exact duplicate yet stays `status: active` with its own
slug; P1-old is `replaced` from `2026-06-01T08:00:00+00:00`, and an as-of search
before that time still returns it; C1-a is `contested` and stays current on both
sides. Details in the [measurement README](../benchmarks/2026-10-31-memory-lifecycle/README.md#examples-inspected-by-hand).

## Compatibility and recovery

`tests/service/test_lifecycle_upgrade.py` populates a schema030 store with the
actual 0.6.18 code (git archive of `d4d2372`) and observed (2026-11-01, corrected source `4a7f925`):

- 19 documents, 227 original rows in 45 tables; an interrupted migration left no
  lifecycle table; the retry applied `031_memory_lifecycle.sql` in 2.63 s with a
  verified backup, unchanged original rows and an empty second retry.
- No decision, event, audit row or provider call from the upgrade; `ev1`/`src1`
  of every document and source unchanged by the migration and by decisions.
- 0.6.18 reads were identical before the first decision; after decisions 0.6.18
  search hid the member, `get` still showed the original, evidence history was
  unchanged and ordinary writes worked. A 0.6.18 edit made an extension `stale`.
- 0.6.18 automatic curation with the default budget still archived a differently
  titled pair; with `[curation] budget = 0` it archived nothing. 0.6.19 curation
  archived only the same-title copy.
- A verified backup with decisions restored independently with decisions, the
  hiding effect and the three guard triggers intact. Restoring the pre-upgrade
  dump lost the writes made after it, as documented.

## Playbook rehearsal

[PB-066-OPS](../playbooks/system/rag-066-memory-lifecycle.md) is rehearsed by
`tests/service/test_lifecycle_playbook.py`; observed results are in the
[rehearsal record](../playbooks/system/rag-066-memory-lifecycle-review.md). The
first playbook content review required correction of PB-I1; independent
correction review accepted PB-I1 and its companion fixes at `4a7f925`; the
corrected populated rehearsal passed in the final full suite.

## Defects found and fixed during S1

| Finding | Severity | Red evidence | Fix |
|---|---|---|---|
| Apply and correct on an autocommit connection committed the decision and event before a failed audit write | Medium | `test_autocommit_connection_is_still_all_or_nothing`: 1 failed | `b4ded6f`: explicit transaction for autocommit connections |
| Per-row hidden check re-planned nested SQL functions: a broad query with 300 merged members went from about 270 ms to 2.7 s | Medium | `test_hidden_check_is_flat_and_snapshot_matches_document_version`: 6 nested calls instead of 0 | `ce1c8bf`: `ls1` defined once in an invoker-rights view, check in PL/pgSQL reached only by members |
| `rag review` did not show contested or stale decisions the playbook relies on | Low | PB-066 rehearsal failed at B1 | `baec38f` |

## Recorded S1 deviations and dispositions

- Codes beyond the contract code list: `proof_failed`, `review_required`,
  `not_current`, `invalid_arguments`, `scope_denied`. They name refusals the
  original design described without a code; the as-built contract now lists them.
- Apply checks the inspected versions before the proof: an apply with outdated
  versions reports `stale_version` even when the proof would also fail.
- Two frozen expectations of earlier features (`0.6.18 not in
  SUPPORTED_VERSIONS` in `test_evidence_revisions.py` and
  `test_synthesis_policy.py`) were moved to 0.6.19, because 0.6.18 is now a
  supported upgrade source. The change is marked in both tests.
- Some registration and upgrade-support tests were written after the code they
  cover; their red runs were structural only (missing imports or tables).

## Limits and low findings (for Issue75)

- First-review F1 (moved-member metadata leakage, Medium) and F4 (foreign-key
  collisions, Low) are corrected at `a5f359c` and `30b4064`; independent
  correction review verified both fixes at `4a7f925`.
- The independent managed-index k=1 probe passed on an actual managed generation
  in the exact pool (up to 4096 candidates). The larger ANN path was not tested.
- Trusted direct SQL writers can create an unaudited decision (F5 Low). The
  gateway stays atomic; the playbook detects this state and requires
  maintainer-led repair. This existing trusted-writer boundary is tracked for
  Issue75, not silently called impossible.
- The corrected 300-member worst-case search takes 322.7 ms before
  decisions and 814.4 ms after (median of three run medians). The
  definer helper also adds per-row work without merged members. The previous
  `unaffected` claim is withdrawn; the [current comparison](../benchmarks/2026-10-31-memory-lifecycle/README.md#security-boundary-cost-after-correction)
  publishes absolute full-scan, lexical and direct-call overhead.

## Test runs

Serial runs of the 83 new and affected test files (every file that touches
lifecycle, curation, eligibility, search, get, tools, migrations, upgrade
versions, profiles, thematic, entities, context, graph or research, plus
`test_docs_continuity.py` and `test_evidence.py`), one pytest at a time on the
owned server:

| Revision | Result |
|---|---|
| `49d37bc` | 2 failed, 1,186 passed (1,547 s), exit 1: two earlier expectations, see below |
| `351b6f4` | **1,188 passed**, 1 known Starlette deprecation warning, exit 0 (1,555 s) |

The two failures at `49d37bc` were expectations of earlier features that the
intended RAG-066 changes overtake: `test_temporal_upgrade.py` listed the
migrations newer than 0.6.16 without 031, and `test_scope.py` merged two copies
with different titles to prove a scope rule. `351b6f4` adds 031 to the list and
gives each pair in the scope test one title, so only the scope decides. Both
changes are marked in the tests.

These are historical affected runs; the final full suite is recorded below.

## Coordinator checks before independent review (2026-11-01)

The S1 affected run ended with 1,188 passed, one known warning and exit 0 at
`351b6f4`; the subsequent S1 commit changes documentation only. The coordinator
then found two Medium defects in explicit views. `get` returned replaced, weakly
supported or future originals under an explicit view without testing eligibility,
and a derived current scope inherited `include_merged` inside an autocommit
transaction. Four regression cases failed before either fix. After the fixes,
`tests/test_lifecycle_views.py tests/service/test_lifecycle_transports.py` passed:
19 tests, one known warning, exit 0 (48.23 s). Omitted original inspection remains
available; explicit get views now use their SQL eligibility and active-status
gates. The autocommit view restores the enclosing selection after current reads.

At that handoff, independent review and full-suite acceptance were pending.
The review still had to classify the reported foreign request-key collision and direct-SQL
decision target visibility, exercise managed k=1 retrieval end to end, and check
history pagination through the public tool. The subsequent independent review classified the metadata defect Medium
and drove the corrections below.

## Independent review and corrections (2026-11-01)

The independent review inspected all 68 changed files at `1fc0628` and ran
130 assertions on owned databases: 127 passed, three failed on pagination and
overflow. Other probes reproduced moved-member metadata disclosure. Its separate
playbook check passed five of six assertions; the integrity query falsely counted
a contested relationship as a hiding chain. Verdict: changes required, two Medium
findings (F1/F2), one Important playbook finding (PB-I1), three Low findings
(F3/F4/F5). The first full-suite run was intentionally interrupted after these
blockers were confirmed: exit 2, sources unchanged. It is retained as failed
acceptance evidence and never counted as a full pass.

| Correction | Regression evidence | Current focused evidence |
|---|---|---|
| F1: original-scope-only decision/event RLS, Boolean-only suppression helper, redacted placeholder | two moved-member cases failed before the fix | 27 related tests passed, exit 0, at `a5f359c` |
| F2/F3: history cursor advances events; bounded as-member detail signals overflow | two pagination/overflow cases failed before the fix | three pagination/integrity tests passed, exit 0; `4365348` |
| PB-I1: count only active hiding chains; explain escalation-only unaudited decisions | contested-plus-hiding fixture falsely reported two chains | included in the three passing tests |
| F4: key uniqueness and lookup use domain/project scope | foreign request returned 409 instead of 200 | 33 affected tests passed, exit 0; expanded four-case scope/privileged-operator run passed, exit 0 (14.69 s), at `30b4064` |

The final acceptance below supplies the source-bound full suite and current
populated-upgrade/restore rehearsal. The independent correction review freshly
verified metadata and pagination; prior success/recovery evidence is inherited
only for unchanged paths.

## Final acceptance at `4a7f925` (2026-11-01)

- Full pytest: **2,063 passed, 1 skipped, 1 known warning**, exit 0,
  2134.52 s; all 371 source hashes unchanged. This includes the
  populated old0.6.18 upgrade, empty retry, original-row/grant/owner inventories,
  current031 independent restore, old consumers and public playbook rehearsal.
- Complete first review (68 files) and independent correction review (12 files)
  leave no C/H/M or Important. Fresh correction probes: 50 assertions, 48 passed,
  two documented Low failures, zero probe errors, three owned DBs removed.
  Prior unchanged success/recovery/retention/managed-k1 evidence is inherited
  explicitly; no claim of 50 passing assertions is made.
- Three fresh benchmark repetitions on the same frozen fixtures: deterministic
  outcomes identical, 0 new false merges versus 1 with actual0.6.18 curation,
  two legitimate pairs deliberately left for operator review; 31/31 preview,
  32/32 view and 8/8 transition checks. Zero provider calls. The separate
  seven-round security-cost comparison ran without competing pytest and retains
  the measured overhead; it does not establish production performance.
- Node7/7 and lock55 packages passed. Wheel187 entries, 182 source payloads
  byte-identical, 31 SQL migrations, 18 read-only tools; installed-package smoke
  validates an empty lifecycle overlay and removes its owned DB.
- LOW-045..049 are [collected in Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6552085171).
  PB-M4's recovery hint is added from the independently verified original-scope
  correction flow (P3). This is a documentation-only clarification.

Only documentation and measurement artifacts change after this source-bound run;
the product, SQL, tests, assets and dependency files remain byte-identical. No
live deployment, systemd/TLS restart, macOS or multi-host acceptance is claimed.
