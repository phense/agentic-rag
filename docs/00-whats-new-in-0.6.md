---
id: release-0.6
title: What's New in 0.6.0
type: reference
doc_id: standalone
readers: [operators, maintainers]
status: accepted
version: 0.6.0
depends_on: []
assets: []
last_reviewed: 2026-10-04
summary: Ten adopted retrieval and ingestion features, measured limits and supported upgrade boundaries.
---

# What’s New in 0.6.0

agentic-rag 0.6.0 includes the ten sequential retrieval and ingestion features tracked
by Issues 26–35. All ten have been merged and adopted on the maintainer’s local
installation. Features 9 and 10 were activated together at `b849d34` on 2026-10-04,
upgrading schema 001–018 to 001–019. The
[production acceptance](verification/features9-10-production-adoption.md) records
strict restores, retained state, full suites and fresh CLI/MCP clients.

## Feature map

| Feature | Behavior | Reference and evidence |
| --- | --- | --- |
| 1. Adaptive retrieval | Exact, lexical and semantic routes preserve original citations. | [Measured routes](benchmarks/2026-10-03-adaptive-search/README.md) |
| 2. Retrieval caches | Permission-safe reuse and reusable local inference connections. | [Original-backed cache measurements](benchmarks/2026-10-03-query-cache/README.md) |
| 3. Local reranking | Selective multilingual ordering for ambiguous queries. | [Runtime, RAM and latency limits](local-reranker.md) |
| 4. Contextual indexing | Separate contextual vectors retain original chunks and source spans. | [Indexing and backfill](contextual-indexing.md) |
| 5. Filter-aware vector search | Bounded exact fallback searches eligible project/domain material. | [Paired correctness and latency](benchmarks/2026-10-03-filter-aware-search/README.md) |
| 6. Bounded research | Compound questions receive source-qualified support, disagreement or abstention. | [Research reference](bounded-research.md) |
| 7. Thematic summaries | Audited reuse of original excerpts with invalidation and drill-down. | [Summary reference](thematic-summaries.md) |
| 8. Entity identities | Confirmed source-backed aliases, historical lookup and audited revocation. | [Entity reference](entity-identities.md) |
| 9. Incremental ingestion | Exact input/model embedding reuse and bounded ordered preprocessing. | [Ingestion reference](incremental-ingestion.md) |
| 10. Failure evaluation | Sealed offline profile selection, local private correction evaluation and explicit public mining comparison. | [Evaluation reference](failure-evaluation.md) |

## Measured examples

| Workload | Before → after | Evidence and limits |
| --- | --- | --- |
| Edit one of twelve chunk inputs | Embedding HTTP inputs 240→20; p50 845.923→311.768 ms. | [Feature9](benchmarks/2026-10-04-incremental-ingestion/README.md), 20 paired synthetic edits with real local embeddings. Every original chunk/vector/scope checked; retained service caches. |
| Retry accepted mining plus auxiliary reembedding | HTTP inputs 160→0; p50 1299.945→100.007 ms. | Same 20-pair fixture. Savings belong to eight auxiliary reembeddings; accepted worker replay already avoided inference before this change. |
| Offline scoped/current-answer routing | Supported exact answers 30/48→48/48; p50 223.982→44.0895 ms. | [Feature10](benchmarks/2026-10-04-failure-evaluation/README.md), 48 held-out public queries in six synthetic families, 20 alternating pairs/query. This measures extractive support, not general model accuracy or an activated production policy. |

## Upgrade and recovery boundaries

The tested combined source is `1294d6c44fd02b66715692f12791bfa2fd4c8856`/schema018.
[PB-5.9](playbooks/incremental-ingestion.md) performs a strict verified source backup,
checks exact clean checkouts and the singleton worker lock, applies additive019
atomically, then activates the approved code. Recovery detaches source code while
retaining019 and later audited writes. A full database restore requires a separately
approved loss boundary. Older installations must complete their intervening documented
upgrades; this evidence does not validate a direct 0.5.0/schema014 jump to019.

The existing interpreter, client settings, hooks, jobs and provider selection remain.
Fresh MCP clients expose ten reader and eighteen main tools; already-running clients
load new code on reconnect. The worker lock causes a busy upgrade to reject immediately;
no service interruption is part of the procedure. Feature10 adds no SQL or live policy
loader. Candidate files alone cannot change search or mining prompts.

## Limits and defaults

- Embedding reuse requires exact sanitized input and a known, unchanged local model
  identity. The derived FIFO cache is capped at 8192 entries. Known-identity misses
  use at most sixteen inputs per request; preprocessing uses at most two requests per
  process and ordered gateway application. The legacy fallback preserves its original
  payload under the same two-request concurrency limit.
- Alias links require original evidence inside the same project/domain boundary.
  Embedding similarity never confirms an identity. Shared roles and domains remain
  the existing access model; the benchmark does not introduce per-user ACLs.
- Eight public native mining calls selected the existing prompt. Held-out corrections
  were 2/2 on both compared prompts; no mining quality gain is claimed.
- Domain-free temporal assertion comparison remains tracked separately in
  [Issue48](https://github.com/phense/agentic-rag/issues/48). Historical benchmark and
  release records retain their original revisions and limits.
