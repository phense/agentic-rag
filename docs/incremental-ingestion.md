# Incremental embedding reuse

Available in 0.6.0; [approved local schema019 adoption](verification/features9-10-production-adoption.md) completed on 2026-10-04.

A document edit often leaves most of its chunks unchanged. The write gateway can
reuse their embeddings when the exact sanitized model input and observed model
identity match. Original documents, evidence, project/domain selection and source
cursors retain their existing contracts.

Migration019 adds a disposable8192-entry FIFO cache containing input/model hashes
and half-vectors. It stores neither original text nor endpoint strings and does not
import untagged legacy vectors. Raw and contextual representations have separate
versioned keys. Context prefixes, source excerpts and project labels participate in
the actual contextual input hash. Endpoint, normalized model tag, model digest and
dimension participate in the model key. Unknown or changing identity disables reuse.

The gateway batches known-identity misses in requests of16 inputs and runs at most2
preprocessing requests per process. Cache reads and prepared groups use at most256
chunks/1MiB input. Large documents retain every chunk through ordered pages; the
legacy fallback preserves its original payload while obeying the concurrency limit.
Accepted mining prepares at most16 final memory/lesson/signal documents before
applying them in original order. Assertions and contradictions use the ordinary
gateway. Deduplication uses its own unchanged representation and current SQL state.
Other existing query/provider workloads retain their own concurrency contracts.

Cache persistence and eviction share one nonblocking transaction lock. A busy cache
can cause repeated inference; it cannot block another document writer on cache locks.
Optional SQL errors use savepoints. Canonical writes, cache fills and aggregate audits
commit or roll back together. Mining's durable extraction, locked application/result
transaction and queue acknowledgements remain separate existing recovery boundaries.
The worker never preclaims speculative jobs.

Existing `rag save`, `memory_save`, CLI upserts and queued reembedding automatically
use the cache after019. No new configuration or flag is required. Saving identical
content still regenerates chunk IDs; reuse does not make canonical saves no-ops.
The shared database roles provide no new per-user row ACL. A vector reused across
scopes never changes retrieval/evidence eligibility.

For diagnostic code, `embedding_reuse.measure()` exposes actual generated input and
HTTP call counts, persisted-cache hit occurrences and prepared-vector consumptions
as separate counters. These request-level counters are not unique unchanged chunks;
preparation and final application are distinct events. Public measurements count
actual HTTP inputs independently. Speculative preparation can be unused when a claim
already exists or an application fails. Its work is bounded and does not establish truth.

Supported source1294d6c, schema018; target additive019. Candidate code on018 preserves
the original inference route. Source code on019 ignores derived cache entries. Code
recovery retains all knowledge and019. No provider/dependency/client configuration
change is required. See [PB-5.9](playbooks/incremental-ingestion.md) and
[verification](verification/incremental-ingestion.md) before adoption.
