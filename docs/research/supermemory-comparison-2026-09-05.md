# Supermemory comparison and agentic-rag improvement requests

Date: 2026-09-05. This is a code and design review, not a performance benchmark.

## Assessment

Keep agentic-rag's existing architecture and improve the quality of what it stores,
selects and injects. The strongest opportunities are reliable source consumption,
repeatable quality evaluation, consistent project scope, and time-aware fact updates.
Reranking and automatically maintained context profiles should follow measured need.
The evidence does not justify replacing PostgreSQL/pgvector, adopting a hosted memory
service, or assuming a different embedding model is better.

Supermemory describes itself as a research lab and reports strong benchmark results.
Neither statement establishes superior behavior for our bilingual coding-session
workload. Our own checked-in embedding experiment had only three answerable queries
in its sample, so it cannot establish parity either. The appropriate next step is a
representative, reproducible baseline and targeted improvements.

## Reviewed source and evidence limits

- Supermemory: `4d8a4ebfddadc3430f7f59a752cd374670833f50`, cloned with depth 1 to
  `/private/tmp/supermemory-review-20260905` (1,192 tracked files).
- agentic-rag local: `384b50c5406da5a94e0ff20534d221d96403ad30`.
- agentic-rag published: `05f87d07112cc7133a60e782734a82f31e9a9492`.
  The linked implementation/test/benchmark files were byte-compared with the local
  version and are identical. Backlog links point to the published backlog.
- Inspected: repository structure, MCP tools, shared middleware, context deduplication
  and caching, API validation, memory schema, ingestion/graph/profile/benchmark docs;
  and agentic-rag SQL search/graph/storage, mining, transcript handling, curation,
  startup/prompt hooks, MCP, relevant tests and backlog.
- Supermemory's current checkout contains applications, integrations, schemas and
  documentation. Its clients call the separate memory API. The core extraction,
  graph-update, profile-generation and reranking engine implementations are not in
  this checkout. Schema fields and documentation show contracts and intended behavior,
  not proven server-side execution or comparative quality.
- The MemoryBench framework is in a separate repository; its provider interface and
  pipeline documentation were reviewed here, not its full implementation. No benchmark
  claims were reproduced. No dependencies or Supermemory services were installed.
- Only code and synthetic test inputs were used. No private memory corpus was read or
  uploaded, no provider was changed, and no production database operation was performed.

## Capability comparison

| Area | Supermemory evidence | agentic-rag today | Improvement |
|---|---|---|---|
| Quality measurement | Documents a multi-stage benchmark framework with provider adapters | Small embedding sanity experiment and functional tests | End-to-end, held-out EN/DE evaluation |
| Source ingestion | Structured role-bearing conversation client and stable source IDs; incremental update behavior documented | Delta mining, but truncation can over-advance the cursor; per-item commits can replay | Explicit consumed ranges and persisted idempotent extraction batches |
| Project context | Container tags are validated and routed by clients | Domain filter in search; path filtering in SessionStart; inconsistent recall/curation scope | Shared project/global scope policy |
| Fact lifecycle | Schema distinguishes latest version, forgotten state, expiry and inference | Typed supersedes/contradicts edges, refutation and history already exist; search primarily uses active status | Current/as-of eligibility and evidence-backed updates |
| Grounding | Source count, inference flags and structured roles are visible in schemas/clients | Ordinary mined claims have session-level provenance; edges can carry evidence | Claim-level evidence and source identity |
| Retrieval | API controls for reranking, rewriting, related memories; algorithm not included | Vector + bilingual FTS RRF, fixed pools, chunk results and prefix snippets | Diverse results, useful spans, calibrated relevance and measured local reranking |
| Context assembly | Actual stable/recent rendering, mode-aware deduplication, owned context blocks and bounded cache | Pins, domain map, recent project titles and continuation checkpoint; error-only prompt recall | Source-backed profile view plus selective ordinary-query recall |

The two projects also use “hybrid” differently in relevant interfaces: our search
combines vector and lexical rankings; Supermemory's client `searchMode: hybrid`
combines learned memory results and source-document chunks. The matching word does
not establish identical retrieval behavior.

## Prioritized issues

P1 means correctness or a prerequisite for judging improvements. P2 means a quality
improvement after the relevant foundations. These are relative priorities, not an
incident classification; no P0 production outage was established. Effort is a rough
scope estimate, not a time commitment.

| Backlog | Priority | Issue | Effort |
|---|---|---|---|
| 4.1 | P1 | [Add a reproducible end-to-end memory quality benchmark](https://github.com/phense/agentic-rag/issues/3) | M |
| 4.2 | P1 | [Make session ingestion resumable and idempotent at source boundaries](https://github.com/phense/agentic-rag/issues/4) | M–L |
| 4.3 | P1 | [Add explicit project scope across search, recall, and curation](https://github.com/phense/agentic-rag/issues/5) | M |
| 4.4 | P1 | [Track fact validity and supersession in retrieval without deleting history](https://github.com/phense/agentic-rag/issues/6) | L |
| 4.5 | P2 | [Preserve claim-level source evidence and distinguish facts from inferences](https://github.com/phense/agentic-rag/issues/7) | M–L |
| 4.6 | P2 | [Improve retrieval relevance with diverse results and useful evidence snippets](https://github.com/phense/agentic-rag/issues/8) | M |
| 4.7 | P2 | [Build bounded source-backed project profiles and selective recall](https://github.com/phense/agentic-rag/issues/9) | M–L |

Recommended sequence:

1. Fix deterministic source loss and replay behavior ([#4](https://github.com/phense/agentic-rag/issues/4), existing
   backlog 1.4/1.5). This does not need a paid evaluation to justify it.
2. Establish the evaluation baseline ([#3](https://github.com/phense/agentic-rag/issues/3)) and shared scope semantics
   ([#5](https://github.com/phense/agentic-rag/issues/5)). Existing continuity rollout and operational backlog work remains
   visible and is not declared complete by this review.
3. Implement the minimal source-evidence contract from [#7](https://github.com/phense/agentic-rag/issues/7) before
   automating fact replacement in [#6](https://github.com/phense/agentic-rag/issues/6). The broader evidence UX is P2,
   but grounded update evidence is a prerequisite for temporal automation.
4. Use the baseline to select useful retrieval changes ([#8](https://github.com/phense/agentic-rag/issues/8)) and
   then build compact project profiles/selective recall ([#9](https://github.com/phense/agentic-rag/issues/9)).

Each issue contains source permalinks, the current gap, proposed behavior, acceptance
criteria, dependency notes and existing backlog overlap. The seven issues were created
with `enhancement`; the reproducible ingestion defect also carries `bug`. Priority is
explicit in each title and body. Existing closed issue #2 was inspected and does not
duplicate these topics.

## Reproduced failure: an unconsumed tail becomes unreachable

The focused experiment used two synthetic Claude-format events: `first` contained
200 A characters, and `last` contained `TAIL_FACT_ONLY`. With `max_chars=80` and
`per_block=800`, the first digest contained 80 characters and no tail fact, but its
returned cursor was already `last`. The second call using that cursor returned an
empty digest. Neither call exposed `TAIL_FACT_ONLY`.

This independently reproduces existing backlog 1.4. It does not measure how much
historical data was affected, and this review does not requeue or reprocess history.
The related worker-death scenario in 1.5 was inspected in code, not crash-tested here.
Near-duplicate mining currently adds a `duplicate_of` edge and still saves the item;
it is not a deterministic idempotency gate.

## Concrete ideas worth adapting carefully

- **Mode-aware context deduplication.** Supermemory only deduplicates search facts
  against a profile when that profile is actually injected. Copy the invariant:
  deduplicating against hidden context can remove the only visible copy of a fact.
- **Stable and recent context as different sections.** This provides useful broad
  context without a fortunate keyword match. For us, make it a rebuildable view over
  the canonical store, with source references and explicit age, not an autonomous
  replacement for user-owned pins or a second memory database.
- **Source identity before similarity.** Structured conversation IDs and roles are
  useful client-level patterns. Our replay guarantee should use persisted batch/item
  identity; Supermemory's incremental-processing documentation alone does not prove
  its crash guarantees.
- **Separate current facts, history and inference.** Our existing graph is a good
  foundation. Add retrieval semantics and evidence instead of rebuilding another graph.
- **Bounded context caching.** The upstream cache is a bounded LRU; its key uses tag,
  thread, mode and normalized message text. That is not a freshness guarantee. Our
  adaptation needs an actual turn identity and memory revision/invalidation rules.

## Ideas to defer or reject for this workload

Do not copy Supermemory's entire web app, hosted API stack, connectors, OCR/video
processing or UI graph into this task. They broaden inputs and product scope without
establishing better recall for existing coding memories. Source adapters can become
separate requests when a concrete unsupported input is needed.

Do not blindly copy API thresholds or latency claims: our RRF scores are not calibrated
similarities; even upstream docs/schema defaults differ. Reranking and query expansion
need local evidence and latency measurements. Keep the current local embeddings and
FTS fallback unless a controlled comparison supports changing them.

Do not copy similarity-based forgetting as our default correction policy. The inspected
MCP client has a fallback that forgets a sufficiently similar memory after exact-match
failure. Our evidence/audit/history boundary is worth preserving. Similarly, profile
strings should not automatically become authoritative user instructions.

Supermemory's root license is MIT. This analysis copies no implementation. Any future
code reuse must preserve applicable license notices and check the license of the exact
package being reused; a binary/server offering is not made source-available merely by
the client repository's license.

## Source map

The following links are pinned to the inspected published revisions. “Documented”
upstream behavior is explicitly distinguished from inspected client implementation in
the associated issues.

### Add a reproducible end-to-end memory quality benchmark — [#3](https://github.com/phense/agentic-rag/issues/3)

- Current benchmark and its sample limitation: [docs/benchmarks/2026-07-embedding-benchmark.md:7](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/docs/benchmarks/2026-07-embedding-benchmark.md#L7)
- Existing search tests use a small corpus and identical synthetic vectors for the vector branch: [tests/test_search.py:63](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/tests/test_search.py#L63)
- Supermemory documents a resumable INGEST → SEARCH → ANSWER → EVALUATE → REPORT framework: [apps/docs/memorybench/overview.mdx:42](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/docs/memorybench/overview.mdx#L42)
- Its provider interface includes ingestion, indexing readiness, retrieval and isolated cleanup: [apps/docs/memorybench/extend-provider.mdx:44](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/docs/memorybench/extend-provider.mdx#L44)

### Make session ingestion resumable and idempotent at source boundaries — [#4](https://github.com/phense/agentic-rag/issues/4)

- Digest cursor collection and later text truncation: [agentic_rag/transcript.py:45](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/transcript.py#L45)
- Each mined item is saved and near duplicates are merely linked, not suppressed: [agentic_rag/mining.py:315](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/mining.py#L315)
- Existing findings already cover these defects: [BACKLOG.md:117](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/BACKLOG.md#L117) and [BACKLOG.md:123](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/BACKLOG.md#L123)
- Supermemory has a structured conversation client with conversationId and role-bearing messages: [packages/tools/src/conversations-client.ts:75](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/conversations-client.ts#L75)
- Its documented customId contract supports incremental source updates: [apps/docs/ingestion/add-memories.mdx:80](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/docs/ingestion/add-memories.mdx#L80)

### Add explicit project scope across search, recall, and curation — [#5](https://github.com/phense/agentic-rag/issues/5)

- Public search signature has only query/domain/k: [agentic_rag/mcp_server.py:70](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/mcp_server.py#L70)
- Prompt-recall pin lookup lacks a scope condition: [agentic_rag/hooks/prompt_recall.py:100](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/hooks/prompt_recall.py#L100)
- SessionStart already has reusable project semantics: [agentic_rag/hooks/session_start.py:208](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/hooks/session_start.py#L208)
- Exact duplicate merge groups by domain/body: [agentic_rag/curation.py:55](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/curation.py#L55)
- Supermemory validates container-tag configuration and passes explicit tags to tools: [packages/tools/src/tools-shared.ts:96](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/tools-shared.ts#L96); [apps/mcp/src/server/tools/search-memory.ts:32](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/mcp/src/server/tools/search-memory.ts#L32)

### Track fact validity and supersession in retrieval without deleting history — [#6](https://github.com/phense/agentic-rag/issues/6)

- Existing edge vocabulary and validity fields: [sql/001_init.sql:64](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/sql/001_init.sql#L64)
- Search candidate eligibility checks status/domain, not supersession or validity: [sql/003_search.sql:12](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/sql/003_search.sql#L12)
- Mining requires a known slug in its digest: [agentic_rag/mining.py:49](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/mining.py#L49)
- Supermemory memory schema exposes version/root/parent/isLatest and forgetAfter: [packages/validation/schemas.ts:242](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/validation/schemas.ts#L242)
- Its documented distinction between update, extension and inference: [apps/docs/concepts/graph-memory.mdx:67](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/docs/concepts/graph-memory.mdx#L67)

### Preserve claim-level source evidence and distinguish facts from inferences — [#7](https://github.com/phense/agentic-rag/issues/7)

- Ordinary extraction schema: [agentic_rag/mining.py:60](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/mining.py#L60)
- Shared session-level provenance: [agentic_rag/mining.py:313](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/mining.py#L313)
- Role-aware but bounded/redacted transcript input: [agentic_rag/transcript.py:115](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/transcript.py#L115)
- Supermemory distinguishes sourceCount and isInference in its memory schema: [packages/validation/schemas.ts:258](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/validation/schemas.ts#L258)
- Its conversation client preserves structured roles: [packages/tools/src/conversations-client.ts:9](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/conversations-client.ts#L9)

### Improve retrieval relevance with diverse results and useful evidence snippets — [#8](https://github.com/phense/agentic-rag/issues/8)

- Current fixed candidate pools, chunk-level fusion and prefix snippets: [sql/003_search.sql:50](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/sql/003_search.sql#L50)
- The wrapper directly returns SQL hits: [agentic_rag/search.py:25](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/search.py#L25)
- Supermemory exposes rerank/rewrite/related-memory controls in its request schema: [packages/validation/api.ts:470](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/validation/api.ts#L470)
- Its tools normalize exact duplicate facts across context sources: [packages/tools/src/tools-shared.ts:369](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/tools-shared.ts#L369)

### Build bounded source-backed project profiles and selective recall — [#9](https://github.com/phense/agentic-rag/issues/9)

- Current project context is a list of recent titles: [agentic_rag/hooks/session_start.py:227](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/hooks/session_start.py#L227)
- Prompt recall is deliberately error-only: [agentic_rag/hooks/prompt_recall.py:37](https://github.com/phense/agentic-rag/blob/05f87d07112cc7133a60e782734a82f31e9a9492/agentic_rag/hooks/prompt_recall.py#L37)
- Supermemory MCP renders stable/recent profile sections with fact limits: [apps/mcp/src/server/prompts/context.ts:12](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/apps/mcp/src/server/prompts/context.ts#L12)
- Its middleware deduplicates only against sections actually injected: [packages/tools/src/tools-shared.ts:430](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/tools-shared.ts#L430)
- Replaceable escaped context blocks and bounded in-process cache are implemented: [packages/tools/src/shared/memory-context.ts:31](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/shared/memory-context.ts#L31); [packages/tools/src/shared/cache.ts:8](https://github.com/supermemoryai/supermemory/blob/4d8a4ebfddadc3430f7f59a752cd374670833f50/packages/tools/src/shared/cache.ts#L8)

## Validation and delivery boundary

The synthetic cursor experiment passed its assertions reproducing the current failure.
All 36 source anchors were resolved from Git objects; implementation/test/benchmark
links into agentic-rag were checked against current local file contents. GitHub's
published commit was queried before linking. Each created issue was independently
read back and checked for exact title/body, open status and the enhancement label.

This task proposes improvements; it does not implement them. No full application test
suite or comparative retrieval benchmark was run, and no performance gain is claimed.
The numbered backlog tracks the open work; FEATURES.md is not expanded with planned
capabilities.
