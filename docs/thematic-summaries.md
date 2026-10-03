---
id: RAG-5.7-reference
title: Thematic memory summaries
type: reference
doc_id: standalone
readers: [operator, maintainer]
status: reviewed
version: source bd01d97 to schema017 candidate
depends_on: [project-context, claim-evidence, fact-validity]
assets: []
last_reviewed: 2026-10-04
summary: Read local thematic excerpts and trace every entry to current eligible original evidence.
---

# Thematic memory summaries

Thematic profiles collect short original passages under a topic, much like an
index card with pointers to the pages it came from. Every excerpt retains its
document, chunk, source and version references. The view is rebuildable; original
knowledge, pins and checkpoints stay in the shared PostgreSQL store.

## Interfaces

| Interface | Inputs | Result and authority |
| --- | --- | --- |
| `rag summary TOPIC` | `--project PATH`, `--domain DOMAIN`, `--history`, `--context-chars N` | JSON view using `rag_reader`; no refresh or provider call. |
| `rag summary TOPIC --refresh` | Same selectors | Audited writer gateway refresh and real rebuilt/reused/elapsed counters. |
| `memory_summary` | `topic, project=None, domain=None, history=False, context_chars=4800` | Reader-only view on both MCP privilege levels; no write parameter. |
| `rag profile --refresh --project PATH` | Existing project selector | Atomically refresh stable/recent references and three default themes through the gateway. |
| SessionStart maintenance | Existing profile_refresh queue job | Missing/stale themes also trigger refresh; source/cache failure retains baseline context. |

Examples:

```sh
rag summary provider-outages --project /path/to/repository --domain infrastructure
rag summary deployment-architecture --project /path/to/repository --history --refresh
rag summary operational-lessons --project /path/to/repository --context-chars 2400
```

## Themes and visibility

| Selector | Meaning |
| --- | --- |
| `provider-outages` | Provider, outage, authentication, OAuth and German outage terms. |
| `deployment-architecture` | Deployment, architecture, PostgreSQL/pgvector and German equivalents. Default profile includes trusted superseded assertions. |
| `operational-lessons` | Lesson, recovery, restore, rehearsal and German equivalents. |
| Custom topic | An EN/DE full-text expression of1–120 characters. Lexical matching can miss paraphrases. |
| Project path | Canonical project selection plus explicitly global documents. No path means global-only. |
| Domain | Optional topic-domain restriction. A `user` domain is still a topic, not a user ACL. |

The supported installation has shared reader/writer/admin roles and no per-user
document ownership or row-level ACL. Summaries preserve those existing boundaries;
no `user_id` filter or additional user isolation is claimed. Both clients use one
store. Manual original `get` and unscoped search retain their existing browsing contracts.

## Entry contract

| Field | Interpretation |
| --- | --- |
| `inference_status=extractive_theme_membership` | Topic membership is a derived lexical decision; the excerpt is exact source text. No synthesized fact or user instruction is created. |
| `citation`, `document_id`, `chunk_id`, `start`, `end` | Reproduce the exact substring in the original chunk; use `memory_get(slug)` or `rag get SLUG --json` for the full document and sanitized source spans. |
| `source_version`, `versions` | Fingerprint plus document/chunk/claim/assertion/all-source versions. Version mismatch withholds an entry until refresh. |
| `sources` | Up to eight active qualified source/span identities and versions, role, time, complete and reviewed flags. All source versions participate in invalidation, including omitted references. |
| `source_kind`, `review_state`, `provenance_status` | Preserve inference/proposal/legacy distinctions and existing source review labels. Legacy evidence remains explicitly incomplete. Source membership does not prove truth or entailment. |
| `temporal_status` | Current or `historical_superseded`. Historical mode still excludes future/expired/withdrawn and unsupported evidence; it differs from ordinary search `--history`. |
| `clipped` | A long sentence or inspected chunk was clipped. Consult the original before interpreting qualifications beyond the excerpt. |
| `status`, `invalidated`, `omitted`, `warnings` | Freshness and visible coverage limits. Missing017/cache/error retains original access. New eligible sources can make a view stale before they appear. |

## Limits and costs

| Resource | Bound |
| --- | --- |
| Cached source documents |24 per selection; a25th candidate discloses partial coverage. |
| Source spans per entry |8; omission is marked incomplete. |
| Inspected chunk / excerpt |4096 /240 characters. |
| Serialized stored entries |262144 bytes. |
| Rendered context |1000–12000 characters, default4800; omit whole entries. |
| Startup profile contribution |Existing2400-character shared budget; at most two excerpts per theme with an omission notice. Pins/checkpoints retain precedence. |
| SQL / lock wait |At most5s /2s per statement, retaining shorter caller limits and restoring them afterward. These are not a whole-request deadline. |

Refresh reuses unchanged excerpts and hydrates changed chunks. It still recomputes
eligible candidate/version metadata; SQL scan work grows with the visible corpus.
No-change refresh preserves cache generation time and adds no audit entry. There is
no provider call or re-embedding. See the [raw paired costs and limits](benchmarks/2026-10-03-thematic-summaries/README.md).

## Related evidence and operation

[Project profiles](project-context.md), [scope](project-scope.md),
[claim trust](claim-evidence.md), [temporal validity](fact-validity.md),
[PB-5.7 upgrade/recovery](playbooks/thematic-summaries.md),
[review and rehearsal](verification/thematic-summaries.md).

The [GraphRAG query overview](https://microsoft.github.io/graphrag/query/overview/)
motivates summary-assisted retrieval. Its benchmark results are not agentic-rag
measurements, and this implementation uses bounded local excerpts without a hosted
community-report pipeline.
