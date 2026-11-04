---
id: V07301
title: Typed metadata filter verification
type: reference
doc_id: standalone-typed-metadata-verification
readers: [maintainers]
status: reviewed
version: 0.6.30
depends_on: []
assets: []
last_reviewed: 2026-11-04
summary: Exact original-selection results, measured overhead and compatibility evidence for schema039.
---

# Typed metadata filter verification

## Overview

Version 0.6.30 adds optional typed conditions to existing authorized retrieval.
The measured benefit is precise selection of originals. The measurements below
report the cost as well: a filter can take more time, and no search-speed gain
or production latency target is claimed. The [operator procedure](../metadata-filters.md)
keeps field registration and historical label adoption separate from installation.

## Evidence identity

| Element | Recorded value |
|---|---|
| Source installation | 0.6.29/schema038, `a151ee5918cf4b1d8e0e8b18bddfe4adadc7658b` |
| Implementation | `837517b116fb261021a82b40f6cfcacc778c1cf6`, 0.6.30/schema039 |
| Root rehearsal | `frozen-837517b-3`, 2026-11-04 04:04 UTC, exit 0, 76/76 assertions |
| Fixture | 522 synthetic documents and 522 chunks; nine manually described controls, 512 nonmatching background originals, one CLI save |
| Authority | Actual `rag_reader` under a general-domain principal bound to `/projects/metadata` |
| Inference | No external or actual model inference; in-process embeddings stubbed, CLI points to a dead loopback endpoint |
| Selection | Lexical, reranker/context off, k=50; 13 manually declared expected-ID sets |
| Samples | Two warm-ups plus 30 measured serial calls per arm and example; nearest-rank p50/p95 |
| Read preservation | Canonical table hashes unchanged across reads; only audited fixture creation writes |
| Cleanup | Own isolated database removed; shared stores and production unmodified by this rehearsal |

The unfiltered query returns seven authorized originals from the fixture.
Foreign project/domain controls never appear. The three conditions below narrow
that baseline; they are different result sets, so timing differences do not prove
an implementation speed-up. Arms run sequentially and include ordinary host
variation rather than a randomized capacity experiment.

## Practical before/after examples

| Condition | Original count | Unfiltered p50 / p95 (ms) | Filtered p50 / p95 (ms) |
|---|---:|---:|---:|
| Production Linux originals updated this month, importance ≥3 | 7 → 1 | 40.83 / 56.09 | 39.51 / 61.86 |
| NOT production, including missing/null/wrong-type labels | 7 → 5 | 19.88 / 44.95 | 55.57 / 72.35 |
| Originals containing both operations and storage labels | 7 → 1 | 38.94 / 42.88 | 24.23 / 31.95 |

Each timed response was checked against the fixed expected-ID set. The same
AST was also tested across the library and MCP function for all 13 cases; the
production/Linux condition additionally passed the actual CLI, authenticated
REST endpoint and HTTP MCP transport. Literal snippet offsets match stored
original chunks. The remaining cases cover presence, explicit null, wrong
historical types, Unicode, literal wildcard characters, lists and disjunction.

## Contract and compatibility checks

| Boundary | Evidence |
|---|---|
| Mandatory truth | A newer nonmatching replacement still suppresses an older matching assertion; historical view remains explicit. |
| Candidate completeness | Raw ANN fixture has 270 closer excluded originals and 300 permitted farther originals. Contextual/planned paths and managed vectors retain filtering before their candidate limits. |
| Graph and research | A nonmatching bridge blocks traversal; actual reader child returns only matching originals and literal citation spans. |
| Derived text | Filtered summaries/context contain matching originals, omit mixed cached prose/unbound pins/checkpoints, and leave the cache unchanged. |
| Export | A complete matching correction family exports with history; a mixed family is withheld rather than truncated. |
| Current rights | A generic prepared query on the same RLS session loses access after revocation and returns the initial IDs after the complete binding is restored. |
| Invalid and expensive inputs | Duplicate predecode keys, wrong types, version/bounds, UTC overflow and a forced SQL timeout yield explicit errors. Shorter caller timeouts and subsequent requests remain usable. |
| Writes | Audited merge preserves reserved siblings; occupied incompatible envelopes are refused, and an injected audit error rolls back labels, original text and chunks. |
| Older server | Typed requests are refused before submit instead of silently dropping filter/metadata. Omitted fields retain legacy wire arguments. |
| Upgrade | Archived populated029, interrupted039 before commit, retry, old scoped readers/writer, source/target independent restores and limited owner. Published SQL001–038 remain byte-identical. |

The implementation runs recorded 267 affected tests, 11 integration tests,
32 contract/upgrade tests and 32 final narrow tests, all exit 0. These are
separate, overlapping selections and must not be added into a unique-test count.
The last selection is exactly hash-bound to the implementation; earlier runs
precede the documented narrow validation/test additions. Final suite and release
checks are recorded separately before the PR.

## Plans, limits and untested claims

A fresh `EXPLAIN (ANALYZE, BUFFERS)` under the actual RLS reader shows a sequential
scan over 522 documents for the standalone metadata predicate, returning one
row and removing 521. It completed in about 591 ms in that observed plan.
No new application index is installed and no GIN acceleration is claimed.
Selective lexical search timings above apply only to this fixture. Filters
retain an explicit 50,000-visible-document work limit and a maximum 5 s per
statement while preserving a shorter caller limit; errors never become complete
empty or unfiltered responses.

One nonblocking coverage limitation remains: the contextual ANN fixture indexes
only one contextual original. It verifies contextual/planned result filtering,
but does not independently exercise continuation beyond 256 contextual vectors.
The complete filtered SQL bodies were independently compared with their
predecessors; after removing only the optional predicates and explicit original
default arguments, all nine sibling bodies are identical.

No model quality, 40-client capacity, macOS execution or production adoption is
claimed from the local synthetic measurements. Production upgrades require their
own backup/restore, original preservation and live access checks. Existing
metadata is never relabeled or recoded automatically.

## Reproduction and retained artifacts

From the repository root, the root probe command was:

```sh
PGPORT=55460 PGUSER=administrator .venv/bin/python \
  .engineering-method/inputs/RAG-073/root_rehearse.py frozen-837517b-3
```

Ignored artifacts under `.engineering-method/runs/RAG-073/` retain the
implementation report, complete code-review manifest and SQL-body comparison;
`root-rehearsal/frozen-837517b-3/` retains inputs, expected-case assertions,
measurements, plan and terminal result. These are private engineering artifacts,
not required product files. The first root attempt omitted required CLI `--dtype`;
the second used a mismatched synthetic credential ID. Both failed runs are kept
and excluded from successful evidence. The third changes only the probe and
procedure, never product behavior or the acceptance conditions.
