---
id: query-cache-measurements
title: Permission-safe query cache measurements
type: reference
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: feature/retrieval-cache against f27acd98e04c7c67d66ca374eded071ac47c0416
depends_on: []
assets: []
last_reviewed: 2026-10-03
summary: Paired Trading inference measurements and immediate correction/expiry checks for issue 27.
---

# Permission-safe query cache measurements

## Overview

Feature 5.2 / [Issue #27](https://github.com/phense/agentic-rag/issues/27) reuses local
query inference and HTTP connections. Database authority remains fresh on every search.
The MCP process owns a vector-only cache; ordinary one-shot Python/CLI retrieval remains
uncached. No retrieved document, source text, evidence summary or permission decision is
cached. Implementation is on the feature branch; merge and production adoption are pending.

## Practical examples

| Practical case | Before | After | Evidence retained |
|---|---:|---:|---|
| Repeated ordinary German question in Trading-scoped MCP | median 1,044.851 ms; p95 1,077.306 ms | median 811.278 ms; p95 839.942 ms | Identical citation lists 20/20 ; 160 original spans checked per route |
| Same question in the programming domain | median 421.827 ms; p95 435.401 ms | median 184.553 ms; p95 189.357 ms | Identical citation lists 20/20 ; 160 original spans checked per route |
| Withdraw a source immediately after its first cached lookup, synthetic | 2 inference calls per two-lookups pair | 1 inference call per pair | 20 trials: correct source initially, no revoked-source exposure after correction, for both routes |

The first two cases reduce warm median latency by 22.4% and 56.2%, respectively. Each
performs 21 lookups including the separate first call: inference calls fall from 21 to 1.
The broad Trading case still spends about 811 ms on the uncached search/metadata path;
this cache does not fix ANN/filter/evidence costs. Source correction saves 50% of inference
calls for the paired initial/corrected lookup while preserving immediate revocation.
Correction tests use a mock local embedding service; they make no wall-clock speed claim.

An additional negative visibility control uses global scope and the trading domain. Both
routes return no source in 20/20 comparisons; median 175.995→11.931 ms and p95 184.256→18.430 ms.
This is empty-result latency, not evidence recall or a positive retrieval speed claim.
Fresh candidate SQL protects that boundary even when the same query exists in another
cached project/domain context. No answer-quality improvement is claimed by this feature.

## Measurement conditions

| Element | Recorded condition |
|---|---|
| Baseline | Actual embed/search/MCP source from merged feature1, commit `f27acd9` |
| Candidate | Four source-file SHA-256 values in [trading-reader.json](trading-reader.json) |
| Live store snapshot | 10,203 documents, 11,593 chunks; existing 14 migrations |
| Access |`rag_reader`; explicit repeatable-read/read-only transaction; rollback on exit |
| Time selection |Fixed current timestamp passed as `as_of` throughout the paired measurement |
| Model |Existing local Ollama `bge-m3`; fresh digest read before every attempted reuse and after inference |
| Samples | 20 alternating paired repetitions per route plus separate first call; cache cleared between cases |
| Boundary |Full MCP function/search/presentation; shared reader lease excludes connection-open and stdio overhead |
| p95 |Nearest-rank percentile over 20 repetitions |
| Privacy |Aggregate output only; no query, document identities, source contents or credentials exported |

First-call times remain in JSON and include initial inference. Neither OS nor Ollama
caches were flushed; these are process-first/warm measurements, not server-cold results.
The fixed timestamp and common snapshot keep candidate visibility identical. A single
question across context selections is a limited sample; no general workload promise follows.
The earlier exact-selector feature and this vector cache address different query paths.

## Bounds, invalidation and fallback

| Resource or condition | Behavior |
|---|---|
| Vector cache |Process-local successful vectors, maximum 256 entries, 300-second TTL, LRU eviction |
| Key |Hashed exact query/context; database/host/role, domain/scopes, as-of/history, endpoint/model/dimension/current digest |
| Metadata identity |Ollama `/api/tags`; unavailable/malformed/ambiguous identity bypasses caching |
| Concurrent misses |At most 8 coalesced keys; pressure falls back uncached; failed futures release waiters |
| Vector payload |Immutable stored tuple and independent returned copies; no failed-inference persistence |
| SQL authority |Candidate and evidence queries run for every call, including cached inference and expiry without a write |
| HTTP transport |At most 8 connections/keep-alive connections, 30-second keep-alive expiry, existing 120-second timeout, rejected cookies |
| Lifecycle |Shutdown closes transport; one weak-registry fork callback clears child vectors/locks/futures; child transport starts fresh |
| Baselines |Legacy retrieval baseline and selector shortcuts bypass vector caching; public old MCP call shapes unchanged |

Model identity is checked at the API boundary. Ollama does not provide an atomic
model-digest-plus-inference snapshot; a concurrent replacement cannot make a combined
model operation atomic. A replacement detected across inference is not inserted under
the old digest, and waiting callers recheck identity before reusing that request.

## Verification evidence

| Check | Result |
|---|---|
| Source baseline | 825 Python tests; 7 Node tests |
| Candidate full suite | 864 Python tests passed in 33.56 s ; 7 Node tests passed |
| New regression cases | 39 tests including 20 source-correction pairs, expiry without write, project/domain/role partition, digest change/race, TTL/LRU/copy, malformed metadata, coalesced failures/recovery, pressure and resource GC |
| Populated coexistence/recovery |Gateway-seeded users/projects, knowledge, pin, checkpoint and queued work; concurrent cached/uncached readers and uncached rollback; all public table rows unchanged |
| Independent implementation review |Zero unresolved Critical/High/Medium/Low; one Low callback-retention finding fixed with a weak registry; real fork and failure/pressure probes passed |

The retained production checkout is still at `0c8addd`. No live deployment, writer,
schema/configuration migration or service restart was performed. Existing dependency
alerts remain in [Issue #37](https://github.com/phense/agentic-rag/issues/37), outside
this feature's clean-diff review.

## Source and adoption references

Reproduction script: `scripts/measure_query_cache.py`. Inputs: `--before-dir` containing
the source revision's `embed.py`, `search.py`, `mcp_server.py` ; `--project`; at least 20
`--repetitions`;  a new`--output` path. It uses the configured reader, validates every
original span and domain filter, and rejects unavailable inference.

Supported source is 0.5.0 at `f27acd9` with migrations 001–014. Adoption/rollback use the
existing [code-only procedure](../2026-10-03-adaptive-search/upgrade.md), selecting this
PR as the target. Restart MCP to adopt or discard its process-local cache; no stored
knowledge or data downgrade is involved. Old/new readers can overlap. Existing audited
writers, adapters and schedules remain intact; process interruption leaves no migration
to resume. Deployment requires separate approval and applicable security triage.

API references: [Ollama model digests](https://docs.ollama.com/api/tags) and
[HTTPX connection pooling/lifecycle](https://www.python-httpx.org/advanced/clients/).
