---
id: V-064
title: Temporal search verification
type: reference
doc_id: standalone
readers: [maintainer]
status: reviewed
version: 0.6.17 (schema029)
depends_on: [../temporal-query.md]
assets: []
last_reviewed: 2026-10-31
summary: Frozen-corpus temporal-search measurements, independent review, populated old-client compatibility, recovery evidence and release limits for Issue64.
---

# Temporal search verification

## Overview

[Issue64](https://github.com/phense/agentic-rag/issues/64), stable feature6.6,
roadmap step6/15, adds opt-in calendar interpretation and event-time preference
or explicit filtering. Source0.6.16/schema029 is `8772fbd`; product changes end at
`6291685`, independently reviewed through `517263c`. Target0.6.17 retains schema029.
The independent review found zero Critical, High or Medium defects. The full-suite
gate is 1,896passed,1expected macOS skip,1known Starlette warning,exit0,1686.96s. No production deployment is included.

Terms: a candidate is a hit already selected by authorized retrieval; an event
time is an assertion time or qualifying original source time, never import/update
time. Held-out cases were frozen before implementation and not used by development
tests. Top-1 counts whether the first hit is expected; MRR is the mean reciprocal
rank of the first expected hit; Recall@5 is the per-query fraction of expected
sources among five hits. Paired latency compares the same query with the feature
on and off. A manifest contains file or table counts and content hashes.

## Measured practical examples

The [harness](../benchmarks/2026-10-31-temporal-query/measure.py) ran on clean
`6291685`; [results](../benchmarks/2026-10-31-temporal-query/results.json) record
36 synthetic documents, PostgreSQL17.10 and Python3.13.13. Retrieval is lexical
full-text only; no embeddings, neural reranker or provider calls are measured.

| Case | Feature off | Time words removed, feature off | Feature on | Limit |
|---|---|---|---|---|
| HD01: certificate renewal failed yesterday, Berlin spring DST |1 of2 expected sources in top5 | Boundary source rank5; other expected source outside top5 | Both expected sources at ranks1/2, Recall@5 0.5→1.0 |23-hour local day; source at00:30 next local day remains outside the matched interval |
| HD04: Druckerwartung nächsten Monat |0 hits | Expected future-plan source rank4 | Expected source rank1; one legacy source explicitly unknown | A source-backed plan can match; this never bypasses future-assertion eligibility |
| RD03: nightly backup job failed gestern, hard filter |0 hits |5 hits, expected source rank5 |1/1 expected source,4 other candidates excluded | Filtering is limited to retrieved candidates; unreviewed assistant/partial and withdrawn evidence cannot supply the matching date |

## Quality and latency

| Measure | Development | Held-out |
|---|---:|---:|
| Parser labels correct |24/24 |24/24 |
| Quality-query denominator |10 |11 |
| Top-1 off / words removed / on |0.10 /0.30 /0.90 |0.09 /0.27 /1.00 |
| MRR off / words removed / on |0.10 /0.49 /0.90 |0.09 /0.51 /1.00 |
| Recall@5 off / words removed / on |0.10 /0.90 /0.90 |0.05 /0.88 /1.00 |
| Ordering-only Top-1 better / worse |6/0 |8/0 |
| Hard-filter exact expected sets |2/2 |3/3 |
| No-intent controls identical |3/3 |3/3 |
| Forbidden documents returned, off / on |0/0 |0/0 |
| Paired period-query median / p95 overhead |+18.3 /+40.1ms,165pairs |+24.4 /+39.7ms,195pairs |
| Paired no-intent median / p95 difference |+0.2 /+16.6ms,45pairs |+0.0 /+18.9ms,45pairs |

Each latency case has3 warm-up and15 alternating measured pairs. These are
single-host synthetic figures. The words-removed arm was added after the first
run and uses the product parser; it is a diagnostic control rather than an
independently implemented parser. Frozen titles include date-label tokens,
favoring feature-off in RD01/HD01. RD07 has zero candidates in every arm because
its text is absent. Both-empty ambiguous controls test safe nonapplication, not
ranking quality. These limits and all denominators remain in the
[benchmark record](../benchmarks/2026-10-31-temporal-query/README.md).

## Verification evidence

| Gate | Actual result | Artifact |
|---|---|---|
| Targeted calendar, search, transports, populated compatibility and public upgrade |104passed,1known warning,exit0,98.56s |[log](issue64/coordinator-targeted.log) |
| Independent complete bounded review |32/32files;0Critical/High/Medium;6Low and1process note |[original review](issue64/independent-review.txt), [source manifest](issue64/reviewed-source-manifest.json) |
| Independent architecture success |29/29checks |[plan](issue64/architecture-plan.txt), [result](issue64/architecture-result.json) |
| Independent failure/recovery |12/12checks; total41/41,exit0;36non-operational table hashes unchanged |Same result; own database removed |
| Full project suite |1,896passed,1expected macOS skip,1known Starlette warning,exit0,1686.96s |[exit/result](issue64/full-suite-result.json), [full log](issue64/full-suite.log) |
| Wheel contents and version |181entries;176source/SQL/assets files byte-identical;0.6.17 |[wheel check](issue64/wheel-check.json); no SQL change |
| Populated actual old-code compatibility |2passed,1known warning,exit0,11.26s; refreshed at reviewed runtime517263c |[table-hash evidence](../benchmarks/2026-10-31-temporal-query/compatibility-evidence.json) |

The full suite ran from2026-10-31T11:36:43Z to12:04:51Z on `517263c`;
its log SHA-256 is `a1cb67f3d2bc5d8264f4744f59dd763c8002d6cf9addd6db4af3a7d7a8425ae7`.
Runtime, tests, schema, version and packaged assets remain byte-identical after
the review and test boundary; subsequent edits correct documentation/evidence only.
The original review/architecture plan still records the then-pending full-suite
gate; the exit artifact above supplies its later completion.

The independent probes drive authenticated REST and server MCP through the real
registry, engine, RLS and PostgreSQL. They cover the169-hour autumn DST week,
assertion/source precedence, unknown/assistant/source-trust cases, foreign scopes,
future assertions/plans, graph limits and legacy/off/no-intent parity. Recovery
revokes access only to `source_at` in an owned disposable database: soft preference
returns the base order with a warning, hard filtering returns an error without
hits, the caller transaction stays usable, and restoring the ACL restores the
same responses. The [executable probe](issue64/architecture-probes.py.txt) is
preserved byte-for-byte. The [first failed run](issue64/architecture-first-run-failed.json)
contains4 probe-design failures; run2 corrected those without a product change.
Neither a running suite nor the first failed probe counts as acceptance.

## Compatibility and recovery boundary

The populated fixture uses actual archived0.6.16 gateway code to write36documents
and dated/unknown source evidence, then checks new reads, old local/REST reads,
unset-option requests to an old server and feature-off rollback. All35
non-operational table hashes remain unchanged. An old server accepts old payloads
and rejects explicitly requested new options with400 `invalid_arguments`.
The public operator upgrade accepts source0.6.16, verifies backup restoration and
original rows, and applies zero migrations. No re-embedding or data rewriting is
needed. New defaults are not sent to old services unless requested.

Installations still on0.6.15/schema028 first follow the separately verified
[source-evidence upgrade](../playbooks/system/rag-063-source-evidence-upgrade.md)
to0.6.16/schema029. The code-only0.6.16→0.6.17 compatibility evidence here does
not replace that migration or authorize a live rollout. A restart loads new
code/config/signatures. Removing `[temporal]` or setting enabled=false restores
legacy auto behavior; explicitly requested prefer/filter still opt in. Actual
0.6.16 code also reads the same schema029 data and ignores the new config section.

## Review dispositions and limits

[Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6543044931)
tracks LOW-031..035: version/common-word false positives, long no-intent diagnostics,
unrecognized synonyms, extreme reference overflow and empty mode coercion. They
remain nonblocking deferred work under the maintainer's Low-bug policy. Broad
production opt-in should follow the parser-context correction; defaults remain off.
LOW-036 covers documentation/evidence corrections in this delivery. RV064-P1
records retrospective transport-test red evidence; it is not original test-first
proof. Coordinator fixes for upgrade-source acceptance, graph k=3 eviction and
fresh source withdrawal have observed red/green regressions and independent review.

No production data, native model accuracy, real TLS/systemd restart, target-host
load or multi-client production performance is claimed. The150-candidate and20-node
budgets bound temporal recall; strict filtering guarantees the interval only for
returned hits. Existing as_of/history and source/claim authority remain independent.

Writing scope: medium standalone reference. Facts are checked against the linked
code/evidence; terminology and source/production boundaries are checked together.
Document links and local HTML rendering are verified before final handoff.
