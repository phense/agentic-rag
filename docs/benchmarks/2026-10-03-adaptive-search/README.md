---
id: adaptive-search-measurements
title: Adaptive retrieval measurements
type: reference
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: feature/adaptive-search against 0c8adddfaf96e105990019eef0b664c7e29ceade
depends_on: []
assets: []
last_reviewed: 2026-10-03
summary: Paired read-only Trading measurements, compatibility checks and bounded claims for issue 26.
---

# Adaptive retrieval measurements

## Overview

Feature 5.1 / [Issue #26](https://github.com/phense/agentic-rag/issues/26) skips query
embedding for strict eligible UUID/slug selectors and standalone error symbols. This
measurement compares the pre-feature `search.py` from commit `0c8addd` with the new default.
The source-file SHA-256 values and full aggregate results are in [trading-reader.json](trading-reader.json).
Implementation is on the PR branch; production rollout is pending.

## Practical examples

The same existing knowledge item supplies these three lookup examples. No private query,
document identity or content is included in the report.

| Practical lookup | Before median / p95 ms | After median / p95 ms | Median speedup | Target retrieval, before → after |
|---|---:|---:|---:|---:|
| Follow an existing document UUID from a reference | 1,064.228 / 1,133.503 | 16.927 / 25.212 | 62.87× | 0/20 → 20/20 |
| Find the exact document using its remembered slug | 1,038.627 / 1,054.622 | 16.533 / 23.036 | 62.82× | 20/20 → 20/20 |
| Locate the source of a standalone error symbol | 1,045.560 / 1,057.928 | 17.019 / 25.719 | 61.44× | 20/20 → 20/20 |
| Ordinary German OAuth/newsletter question, control | 1,050.416 / 1,066.234 | 1,048.140 / 1,068.418 | 1.002× | No labeled target; identical citation lists 20/20 |

Each shortcut avoids all 21 embedding calls, including the separate first call. The error
case preserves identical citation lists in 20/20 comparisons. The UUID case previously
returned other semantic candidates and now returns the selected source. The slug case now
returns that document alone, replacing the wider hybrid result set. Every returned snippet
was checked against its cited original chunk and offsets; this validates attribution, not
the truth of the underlying claim or the quality of a generated answer.

## Measurement conditions

| Element | Recorded condition |
|---|---|
| Store snapshot | 10,188 documents; 11,578 chunks; 22 pins; 25,368 audit records |
| Existing schema | All 14 migrations present; no new migration |
| Access | `rag_reader`; repeatable-read transaction with `READ ONLY`; rollback on exit |
| Project selection | Global plus canonical `/Users/peter/Agents/Trading` |
| Embeddings | Existing local Ollama `bge-m3`; unavailable embeddings invalidate the run |
| Samples | 20 paired repetitions per route/case; alternating route order; same connection/snapshot |
| First-call timing | Reported separately in JSON; no server-cold-cache claim |
| Timing boundary | Search, including scope resolution, embedding, SQL, evidence metadata and presentation; connection opening excluded |
| p95 | Nearest-rank percentile over 20 observations |
| Data handling | Queries and source identities stay in process; aggregate numbers only exported |

The standalone script selects an eligible existing symbol with a lexical result, then uses
the associated document for ID/slug measurements. This is a positive-case sample, not a
random corpus evaluation. The ordinary control keeps the old candidate path. These
numbers demonstrate the avoided inference cost on this machine; they do not promise
these speedups for every workload. Misses retain inference and may add a bounded lookup.
Other production jobs continued normally; changes between separate store snapshots are
not attributed to the reader-only experiment.

## Verification evidence

| Check | Result |
|---|---|
| Pre-change Python baseline | 800 passed in 33.02 s |
| Feature regression and existing suites | 825 passed in 31.40 s |
| OpenCode Node tests | 7 passed, 0 failed |
| New adaptive tests | 25 passed; selectors, filtered misses, outages, expired/refuted/archived knowledge, historical retrieval, strategies, old MCP shape, CLI and reader privileges |
| Populated upgrade/recovery | Gateway-seeded two-user, two-project, multi-domain state plus pin, checkpoint and queued work; concurrent hybrid/auto readers and hybrid rollback; every public table's complete JSON rows equal before/after |
| Independent final review | Critical 0, High 0, Medium 0, Low 0 unresolved; 13 independent isolated route/interface checks passed; one Low documentation finding fixed and rechecked ([record](../../openspec/changes/adaptive-search/review.md)) |

The mixed-reader rehearsal uses the retained hybrid pipeline as the legacy reader. The
live paired script additionally executes the actual pre-feature source. No writer,
schema, adapter configuration, hook schedule or queued work is changed by this feature.
See the [code-only adoption and rollback procedure](upgrade.md).

## Reproduction inputs

Run `scripts/measure_adaptive_search.py` from the candidate checkout with `PYTHONPATH=.`.
Provide `--before-search` pointing to `search.py` extracted from the source revision,
`--project /Users/peter/Agents/Trading`, `--repetitions 20` and a new `--output` path.
The script uses the configured reader role, refuses unavailable inference or invalid
citations, and exports no private corpus text. Source hashes identify the actual measured
files independently of later documentation commits.
