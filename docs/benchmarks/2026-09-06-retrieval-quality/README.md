# Retrieval quality measurements — 2026-09-06

All runs use audited ingestion into owned temporary local databases, k10 and at most
4,000 context characters. Every source indexed, every query completed, cleanup verified,
and zero hosted/model-provider calls attempted. Hybrid uses local bge-m3 embeddings.
JSON contains per-query evidence, snippets, citations, warnings, timings and bootstrap
rank intervals. Both retrieval implementations run from the same code/migration hash;
`--retrieval-baseline` selects the retained pre-change temporal SQL and prefix snippets.

## New regression fixture

Nine fictional documents, ten queries: six held out (four answerable, two negative) and
four development (two answerable, two negative). Facts/answers and explicit families
are disjoint across splits. These are author-known regression fixtures, not a blind
research holdout; implementation tests use analogous failure cases. Preliminary
measurement exposed same-fact split leakage, corrected before these retained runs.
No generic threshold or learned model was tuned to these results. Small denominators
and one sequential run per variant preclude broad superiority or latency claims.

| Variant | Held-out source recall@10 | Held-out evidence recall | Held-out negative false positives | Held-out MRR | Mean context chars (all10) | Retrieval p95 ms (all10) |
|---|---:|---:|---:|---:|---:|---:|
| [fts-before](fts-before/report.md) | 0.500 | 0.000 | 0.000 | 0.750 | 494.3 | 21.5 |
| [fts-after](fts-after/report.md) | 0.625 | 0.500 | 0.000 | 0.750 | 146.5 | 21.3 |
| [hybrid-before](hybrid-before/report.md) | 0.750 | 0.250 | 1.000 | 1.000 | 3982.8 | 371.1 |
| [hybrid-after](hybrid-after/report.md) | 1.000 | 1.000 | 0.500 | 1.000 | 1255.9 | 254.6 |
| [graph](graph/report.md) | 1.000 | 1.000 | 0.500 | 1.000 | 1255.9 | 292.9 |
| [rerank](rerank/report.md) | 1.000 | 1.000 | 0.500 | 1.000 | 1255.9 | 234.2 |
| [rewrite](rewrite/report.md) | 1.000 | 1.000 | 0.500 | 1.000 | 1255.9 | 271.3 |
| [fts-graph](fts-graph/report.md) | 0.750 | 0.750 | 0.000 | 0.750 | 165.4 | 38.7 |
| [fts-rewrite](fts-rewrite/report.md) | 0.875 | 0.750 | 0.000 | 1.000 | 176.1 | 20.7 |

The hybrid default makes all four held-out labeled evidence strings available versus
one before. Document crowding and a late identifier are repaired. Negative retrieval
falls from two of two to one of two solely because the missing exact error identifier
now abstains; the unrelated Venus question still gets candidates. Development negatives
show the same split: exact missing exception abstains, ordinary unrelated query does
not. RRF cannot support a probability threshold and this evidence does not justify a
generic semantic cutoff. These metrics do not measure generated-answer correctness.

## Optional stages: decisions

- Graph expansion adds no hybrid evidence gain in this nine-document fixture because
  the default already fits all eligible sources. Under FTS it supplies the two-hop
  leaf, increasing held-out evidence from2/4 to3/4, with additional latency/context.
  Keep explicit graph depth available; default0.
- Lexical-overlap local reranking adds no hybrid evidence or ranking gain. Timing
  differences are single-run noise, not a demonstrated speedup. Keep the validated
  callback/fallback seam, with no model or dependency enabled by default.
- Authored German rewrites contain synonyms, not answer labels. They restore lexical
  recall under FTS but do not improve hybrid. This is a controlled expansion experiment,
  not a deployable rewrite generator; no automatic or hosted rewrite is enabled.
- All variants stay below the declared synthetic p95 budget of500ms. This budget is
  a fixture acceptance choice, not a production SLA or confidence interval.

## Existing 60-query corpus

The unchanged corpus gives recall@10 1.000 → 1.000, MRR 0.9896 → 0.9896, mean context 1765.4 → 1765.4 characters and measured p95 198.2 → 202.4ms.
Both still return candidates for all12 negative queries. This corpus has no evidence
substring labels, so that metric remains unmeasured; no answer/judge stage ran.
See [before](regression-before/report.md) and [after](regression-after/report.md).

## SQL cost and reproducibility

A strictly read-only check on the current private store exported only timings and
sanitized plan node/count metadata, never content. The first exact per-document vector
ranking scanned all eligible documents and cost576–653ms. It was replaced before final
measurements with ANN oversampling256 and per-document caps in that bounded pool.
The retained plan uses `idx_chunks_embedding`:251 scanned vectors,218 eligible pool
rows,50 fused candidates. Three SQL timings: prior42.57/15.93/12.19ms,
new40.05/26.50/23.44ms. These exclude embedding/Python time and are not p95 estimates.
See [plan evidence](readonly-sql-plan.json). Selective filters and ANN behavior can
produce fewer candidates than the requested pool size. Extremely long duplicate runs
can still exhaust the bounded vector pool; no exact-corpus fallback is enabled.

Commands and variant semantics are in [retrieval quality](../../retrieval-quality.md).
Replay each saved corpus with its results.json config and a fresh output directory.
The [comparison JSON](comparison.json) includes equal-budget deltas. Raw results retain
all misses and negative-query candidates; no failed or inconvenient query was removed.

Source SHA-256 for every run: `a92cfcdb1efd8fda74e917ade6e9f5d34eb05e81b7e3df82f6d56bc2cb03304d`.
