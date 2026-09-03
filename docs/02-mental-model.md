# 02 · The mental model

**What you'll learn:** the handful of objects agentic-rag is built from — documents, domains, edges, chunks — how a write actually happens, how search actually ranks, and how a session turns into knowledge. Everything here is "at a glance"; internals live in [10 · Architecture](10-architecture.md).

Six ideas cover the whole system. Once they click, every CLI command, MCP tool,
and lifecycle hook is just a door into one of them.

## Documents: the unit of knowledge

Everything you save is a **document** — a row with a title, a Markdown body, a domain, and a `dtype`. The `dtype` says what *kind* of claim the document is making, and the schema enforces it with a `CHECK` constraint, not a convention you have to remember:

| dtype | what it's for |
|---|---|
| `concept` | a durable idea or definition |
| `lesson` | something learned the hard way |
| `signal` | a recognizable error/observation pattern |
| `source` | an external reference (a doc, a URL, an import) |
| `synthesis` | a conclusion drawn from other documents |
| `memory` | a fact worth remembering across sessions |
| `reference` | material kept for lookup, not for its own claims |
| `index` | a document whose job is pointing at other documents |

Why a fixed vocabulary instead of free-text tags: it makes dtype a reliable filter and a reliable *signal to the miner* — "this session produced a `lesson`" means something specific, both to you and to search. A document also carries `status` (`active` / `archived` / `refuted`) — nothing is hard-deleted; a refuted document keeps its `refuted_reason`, `refuted_evidence`, and `refuted_at`, enforced by a database constraint, not application discipline. Deletion loses the "we used to believe X, here's why we don't anymore" trail; archiving keeps it. See [07 · Privacy, cost & control](07-privacy-and-cost.md) for the data-safety angle and [05 · Session mining & curation](05-session-mining-and-curation.md) for how refutation actually gets triggered.

## Domains: data, not configuration

A **domain** is just a row in a `domains` table — a name and a description. That's the whole mechanism. Domains answer "where would I look for this?", and because they're data rather than a hardcoded enum, you can add one at any time with `rag domain add`, and the importer can derive them from an existing knowledge store instead of you hand-curating a taxonomy up front. A fresh install always has one domain, `general` ("uncategorized knowledge"), seeded automatically so `rag save` works before you've defined anything — everything else is yours to create. See [08 · Knowledge domains & import](08-knowledge-domains-and-import.md).

## Edges: a typed graph, dangling-safe

Documents don't just sit next to each other — they can point at each other with a **typed edge**. The predicate vocabulary is fixed and CHECK-enforced, same discipline as dtype:

`references · extends · depends_on · complements · contrasts_with · informs · part_of · derived_from · supersedes · contradicts · duplicate_of`

An edge is directional (`src_id → dst_slug`) and carries optional `evidence` and a `confidence` (`high`/`medium`/`low`). The interesting design choice is that an edge is created **by slug**, not by ID, and the slug survives even if the target document doesn't exist yet: `dst_id` can be `NULL` while `dst_slug` holds the name. That's a *dangling* edge — it renders as "not found yet" rather than failing outright. Why this matters: the session miner and the migration importer both create edges against documents they can *name* but haven't necessarily *seen* yet (a slug mentioned in a transcript, a cross-reference in an imported wiki). Forcing every edge to resolve immediately would mean losing real relationships just because of write order. Instead, the moment a document with that slug is finally saved, the gateway resolves every edge that was dangling on it — no separate repair pass, no cron job.

## Chunks: what search actually touches

A document's body doesn't get searched directly — it's split into **chunks**, and search runs over those. Splitting is structural: headings first, then paragraph breaks, and only as a last resort a hard split — Markdown structure never gets sliced mid-heading or mid-fence. Chunks target ~1000 characters and cap at ~4000; short documents (under the cap) stay as a single chunk.

Each chunk carries three things generated for it automatically:

- an **embedding** — a 1024-dimension `halfvec` from the local `bge-m3` model (via Ollama), for semantic/vector search;
- an **English tsvector** (`tsv_en`) and a **German tsvector** (`tsv_de`) — both generated columns, both GIN-indexed, so keyword full-text covers English and German — while semantic recall, via the multilingual `bge-m3` embeddings above, spans any language.

Why bilingual FTS as a first-class citizen rather than an afterthought: a memory store that only does English full-text is only half-searchable if any of your source material is German. Both tsvectors are computed and indexed on every chunk unconditionally — there's no per-document language switch to get wrong.

## Two-signal search: vector and full-text, one ranked list

A query hits both signals at once and the results are fused into a single ranked list — this is what "hybrid search" means here, concretely. `hybrid_search()` (see `sql/003_search.sql`) runs three independent ranked candidate lists — cosine similarity over embeddings, English `ts_rank_cd`, German `ts_rank_cd` — each capped at its own top-50, then combines them with **Reciprocal Rank Fusion**: every chunk's score is `Σ 1/(60 + rank)` across whichever lists it appeared in, and the final list is sorted by that fused score. A chunk that ranks well on *both* the semantic and lexical signal outranks a chunk that only nails one — which is exactly the property you want from "search my memory": a query that's mostly a keyword match and a query that's mostly a paraphrase should both work, and a chunk that satisfies both should win over a chunk that only satisfies one.

If Ollama is unreachable, the vector leg simply contributes nothing — `search()` degrades to full-text-only and returns a warning rather than failing the query. Depth on the fusion constant, index types (HNSW), and degrade paths: [10 · Architecture](10-architecture.md).

## The write gateway: one audited path in

However a document gets into the store — `rag save`, an MCP tool call, the session miner, or the wiki importer — it goes through exactly one function: `save_document()`. That single choke point is what makes every other guarantee in this handbook possible:

1. **Secrets are stripped first.** Title, body, meta, provenance, and edge evidence all pass through the secret gateway *before* anything is written. Nothing bypasses this — not even automated mining output, which is the whole reason it exists there and not just on the CLI's manual-entry path. Full detail: [07 · Privacy, cost & control](07-privacy-and-cost.md).
2. **The slug is assigned and made unique.** A new document without an explicit slug gets one slugified from its title, with a numeric suffix appended if that slug's already taken.
3. **Chunks and embeddings are regenerated,** and swapped in atomically through `replace_chunks()` — a `SECURITY DEFINER` function scoped to one document, which exists because the ordinary write role has no `DELETE` privilege at all (see the role matrix in [10 · Architecture](10-architecture.md)). If the embedding model is unreachable, the save still succeeds without vectors and queues a retry — fail-open on embeddings only, never on the save itself.
4. **Edges are upserted,** and any *other* document's edge that was dangling on this slug gets resolved in the same transaction.
5. **An audit row is written** — who (actor), what operation, which document, a one-line summary.
6. **All of the above commits together**, or none of it does.

The payoff of routing every writer through one place: you get secret-stripping, slug safety, dangling-edge resolution, and an audit trail *for free*, on every write, regardless of which of the four callers (CLI, MCP, miner, importer) produced it — instead of re-implementing (and re-forgetting) those guarantees at each call site.

## The mining loop, at a glance

The store is meant to fill itself from the sessions you already have, not just from things you deliberately `rag save`. The shape of the loop:

**hooks → queue → worker → configured LLM CLI → gateway.** A lifecycle hook enqueues a supported session's transcript. A single-writer background worker drains the queue and uses the configured Codex or Claude adapter to extract durable memories, lessons, and signals from the session digest. Each candidate item is checked for a near-duplicate against what's already stored before it is written, and every extracted item still goes through `save_document()`. Provider-wide outages restore the job's attempt budget, pause that drain, and remain visible until a later success. The miner can also flag contradictions with existing documents or pins, and propose new domains — those surface for review rather than mutating anything unattended.

Full mechanics — the digest format, the extraction schema, the dedup threshold, curation (`rag review` / `rag purge`) — live in [05 · Session mining & curation](05-session-mining-and-curation.md).

## Continuation checkpoints: operational state, not knowledge

A **continuation checkpoint** answers “what must the next model know to resume
this exact task?” It is deliberately separate from general RAG documents. The
checkpoint has its own audited lifecycle (`open`, `superseded`, `completed`),
quality (`snapshot` or `enriched`), same-session cursor, canonical project root,
bounded Git state, artifact references, blockers, and next action. Superseded
history is retained; there is no checkpoint delete path.

The fast path is deterministic. `PreCompact` persists a snapshot without
calling an LLM, then queues optional schema-constrained enrichment for the
single-writer worker. The renderer always preserves checkpoint identity,
blockers, and the next exact action within its configured budget, labels
snapshot-only state as enrichment pending, and tells the next model to
revalidate volatile process or external state.

The restoration boundary matters: `PostCompact` cannot inject context and
never tries. It only marks the stored checkpoint as compacted.
`SessionStart(source="compact")` runs before the next model request and injects
the latest open checkpoint for that same session. A normal startup/resume may
fall back to the newest checkpoint for the same canonical Git project; compact
restoration never crosses sessions or projects.

Native Codex memories solve a different problem. They are complementary
adaptation managed by Codex and inspectable with `/memories`; agentic-rag is the
canonical store for durable, searchable knowledge and explicit, auditable
continuation state.

## How the pieces fit together

```
 supported session ──(mining)──┐
 rag save ───────────┤
 MCP tool call ───────┼──► save_document() ──► documents + chunks + edges
 wiki import ─────────┘        (gateway)              │
                                                        ▼
                                            hybrid_search() (vector + FTS)
                                                        │
                                                        ▼
                                              ranked results back to you

 Codex PreCompact ──► continuation checkpoint ──► async enrichment
        │                         │
        └── Codex compacts ───────┴──► SessionStart(source="compact")
```

Every arrow into the gateway is a different *source* of knowledge; every arrow out of it is the same audited, secret-stripped, transactional write. That's the mental model — one shape, four entry points, one exit into search.

---

**Next →** [03 · Quick start](03-quick-start.md)
