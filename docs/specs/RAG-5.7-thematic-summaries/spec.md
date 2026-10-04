# Feature specification: Incremental thematic summaries

Stable work ID RAG-5.7, feature7/10, [Issue32](https://github.com/phense/agentic-rag/issues/32).
Accepted intent: maintainer's end-to-end implementation request. Supported source
`bd01d97b1188e6bb0cf71e838c7c35e3449d8f3b`, package0.5.0, populated schema001–016.

## Scenarios and acceptance

| ID | Required behavior | Evidence |
| --- | --- | --- |
| AC-001 | Local thematic views extend bounded profiles, retain original document/chunk/source/span identities and versions, and disclose extractive inference, source kind, review and completeness. | Citation/claim tests; three paired examples. |
| AC-002 | Correction, expiry, source withdrawal, scope/domain changes and replacement invalidate cached excerpts before output. Historical mode labels trusted superseded assertions while excluding future/expired/withdrawn/review-only assertions. | Temporal/source/scope tests. |
| AC-003 | Preserve canonical knowledge, pins, checkpoints, queues, accepted batches, evidence and historical audits. Cache writes use an atomic audited gateway with transactional composition, serialized concurrent refresh and idempotent retries. | Rollback/concurrency tests; populated016→017 rehearsal. |
| AC-004 | Bound selected sources, transferred text, references, cache bytes, context and SQL/lock waits. Reuse unchanged excerpts; report creation/refresh cost, query latency, coverage and context size without inventing semantic accuracy. | Raw measurements; budget/failure tests. |
| AC-005 | Shared PostgreSQL store and existing reader/writer authority remain canonical. Project+global or global-only selection and optional topic-domain filter are explicit. No per-user ACL or ownership exists in this source installation; no new user-isolation claim or selector. | Existing schema/role inspection; multi-actor/domain/project rehearsal. |
| AC-006 | Add CLI summary and reader MCP summary; preserve search/get/profile and both MCP levels on old/new clients, including missing017/error fallback and code rollback. Default profile worker also refreshes themes; missing/stale themes trigger maintenance. | Actual old/new/rollback CLI/MCP; hook/profile tests. |
| AC-007 | Full Python/Node suites, complete independent reviews, upgrade/recovery evidence and2–3 practical comparisons precede specific merge approval. Live rollout requires separate authorization. | [Verification](../../verification/thematic-summaries.md). |

## Interfaces and limits

`rag summary TOPIC [--project PATH] [--domain DOMAIN] [--history]
[--context-chars N] [--refresh]` emits a JSON evidence view. Read-only
`memory_summary(topic, project=None, domain=None, history=False,
context_chars=4800)` is available on both MCP servers. `store.refresh_summaries`
is the only public derived-write gateway; `commit=False` composes atomically.

At most24 eligible document/chunk excerpts per view,8 source spans per entry,
4096 inspected chunk characters and240 excerpt characters; cache JSON ≤262144
bytes. Context1000–12000 characters, default4800. Per-statement SQL timeout≤5s,
lock timeout≤2s, respecting shorter caller limits. SQL scans remain corpus-dependent.
No provider call, embedding, configuration change or new scheduler.

## Upgrade and procedure obligation

Additive migration017 creates only a disposable cache and its grants. Current
readers continue to work on016; missing cache never removes baseline evidence.
Old code remains compatible with017 and ignores the new table. Code rollback
retains017 and all data; no downgrade/drop is required. PB-5.7 must be reviewed
and rehearsed before delivery, with strict backup restore, interrupted migration,
safe retry, old/new clients and protected-state checks. The canonical installation
remains on016 until separately authorized adoption.

## Interpretation limits

An exact excerpt proves source membership, not factual truth or semantic
entailment. Thematic grouping is a local lexical/extractive index; it never merges
historical facts into a new canonical instruction. Custom topics are bounded EN/DE
full-text expressions; named themes provide explicit synonym queries.
