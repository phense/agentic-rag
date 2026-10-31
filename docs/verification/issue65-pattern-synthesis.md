---
id: V-065
title: Pattern synthesis verification
type: reference
doc_id: standalone
readers: [maintainer]
status: draft
version: 0.6.18 (schema030)
depends_on: [../pattern-synthesis.md]
assets: []
last_reviewed: 2026-10-31
summary: Frozen-fixture pattern-synthesis measurements, populated 0.6.17 upgrade and recovery evidence, playbook rehearsal and release limits for Issue65; independent review and the full suite are still pending.
---

# Pattern synthesis verification

## Overview

[Issue65](https://github.com/phense/agentic-rag/issues/65) adds opt-in pattern
synthesis: source-linked, reviewable inferences over several original memories.
Source is 0.6.17/schema029 (`81beaf6`); the target is 0.6.18 with additive
migration030. This record covers the implementation slice (S1). The independent
review (S2) and the full test suite (S3) are coordinator-owned and **not yet
done**; nothing here claims them.

Terms: a *pattern* is a stored inference with exact citations. An *independent
event* is a distinct user report after merging same-source and same-text quotes.
The *floor* is three independent events across three memories. *Oracle* answers
are honest scripted model answers; *adversarial* answers try to over-claim,
contradict or escape the output contract. A *non-conclusion* is a run that ended
without a pattern, with a reason.

## What was measured, and what was not

The [harness](../benchmarks/2026-10-31-pattern-synthesis/measure.py) ran the real
preview, scheduler, worker drain, validation, audited application and guarded
reads on product revision `3860576`, three repetitions, PostgreSQL 17.10,
Python 3.13.13. The provider boundary was replaced by frozen scripted answers.
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

Median timings: preview 15.6 ms, schedule 18.9 ms, drain 45.5 ms (includes the
scripted call), inspect 14.9 ms. Prompts carried 1,041 to 1,412 characters.

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
only `030_pattern_synthesis.sql` in 2.22 s with verified restore and unchanged
original rows; the retry applied nothing; no policy, run, job or pattern existed
afterwards. 0.6.17 reads were identical after the upgrade. 0.6.17 local writes
and its central API worked on schema030. Accepted work survived a verified
backup and restore and was recovered without a second provider call. A
pre-upgrade restore loses later writes, as documented.

## Playbook rehearsal

PB-065-OPS parts A–D were rehearsed on owned databases through the real CLI and
the central worker loop; details in the
[review and evidence record](../playbooks/system/rag-065-pattern-synthesis-review.md).
The rehearsal found one documentation error (empty backfill windows close
without a run), corrected before commit.

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
- A 0.6.17 process returns a pattern body from `memory_get` by id on schema030;
  its search stays guarded.
- A writer transaction longer than the 60-second settle window can be skipped by
  the forward cursor; a backfill covers it.
- The curation report (`rag review`) can still list withheld pattern slugs.
- Disable every policy before a code rollback: a 0.6.17 worker cannot process
  queued pattern jobs.

## Pending before delivery

Independent review (T065-009), as-built reconciliation, the full test suite and
the pull request (T065-010/011).
