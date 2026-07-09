# Embedding benchmark (2026-07)

## Decision

**Chosen: bge-m3 / 1024 dimensions.**

Reasoning: of the 10 golden queries, only 3 had a matching page in this run's random 200-doc
sample (the other 7 print a "no sampled page matches" note and are excluded as undecidable);
on those 3 decidable queries bge-m3 hit 3/3 vs embeddinggemma's 2/3, and bge-m3's throughput
(10.2 docs/s) is far above the 2 docs/s floor — so the decision rule's switch condition
(embeddinggemma matches bge-m3's score **and** bge-m3 is unacceptably slow) is not met on
either count. This keeps the spec default (bge-m3/1024); no changes are needed to the `1024`
literals slated for `sql/001_init.sql` / `sql/003_search.sql`, and no `[embed]` section needs
to be added to `~/.agentic-rag/config.toml` beyond the existing default.

## bge-m3
- dim: 1024
- 200 docs in 19.6s (10.2 docs/s)
- retrieval sanity: 3/10 queries hit expected page in top-3

## embeddinggemma
- dim: 768
- 200 docs in 19.3s (10.4 docs/s)
- retrieval sanity: 2/10 queries hit expected page in top-3
