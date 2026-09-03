# What is agentic-rag?

*What you'll learn: the one-paragraph pitch, who this is for, how durable
memory differs from compaction continuity, and what agentic-rag is — and isn't.*

## The pitch

agentic-rag is provider-neutral long-term memory plus continuity, backed by
PostgreSQL and pgvector. It stores what you and a coding agent learn as a
searchable knowledge graph and finds it again with hybrid vector + full-text
search. Session mining uses the configured Codex or Claude CLI to extract
durable facts, lessons, and error signals through one audited gateway. The
Codex integration also captures bounded checkpoints before compaction and
restores them before the next model request.

## Who it's for

You, if you use a supported coding agent across long or repeated sessions and
are tired of re-explaining context, rediscovering the same bug, or losing a
hard-won decision when the terminal closes or context compacts. It expects you
to be comfortable running local Postgres — this is infrastructure you host,
not a service you sign up for.

## What it is

- **A hybrid search engine over your own knowledge.** Every document is chunked and embedded via a local multilingual model (`bge-m3`), so semantic search works in any language, and is also keyword-indexed for English and German full-text. Search blends vector similarity with lexical ranking into one result list — better recall than either alone.
- **A memory that writes itself.** Session mining reads supported local session transcripts and turns what you learned into new documents — memories, lessons, and recognizable error signals — automatically, without you stopping to write anything down.
- **A compaction continuity layer.** On Codex, `PreCompact` saves fast,
  deterministic state and queues optional semantic enrichment.
  `SessionStart(source="compact")` injects the newest same-session checkpoint
  after compaction. `PostCompact` cannot inject context; it only marks the
  boundary.
- **Self-curating.** A background process de-duplicates near-identical entries, flags dangling links and stale pins, and gives you a `rag review` report instead of letting the store rot silently.
- **Local-first and provider-configurable.** Your data lives in a Postgres database on your machine (or one you control). Mining and curation call the configured Codex or Claude CLI. Embeddings are always local (Ollama), and there's no separate hosted RAG service in the loop.
- **RAM-lean.** There's no always-on daemon beyond Postgres and Ollama themselves. The background worker is single-writer and event-driven; between sessions, agentic-rag's own footprint is close to zero.
- **Data-safety-first.** Writes go through one gateway that strips secret-shaped tokens before anything reaches disk, refuting a document archives it instead of deleting it, and backups get a real weekly restore-test — not just a file that might be a backup.

Native Codex memories remain enabled by the managed Codex policy and can be
inspected with `/memories`. They are complementary: agentic-rag is the
canonical, queryable, audited record for durable knowledge and explicit
continuation checkpoints.

## What it is NOT

- **Not a hosted product.** There's no managed backend to sign up for. You run Postgres and Ollama; agentic-rag connects them to supported agent integrations.
- **Not a hosted RAG service.** It doesn't call a third-party RAG backend — LLM work goes through your configured local Codex or Claude CLI. If that provider is unavailable, jobs remain pending and the outage is surfaced.
- **Not a file-based wiki.** Knowledge lives in Postgres, not a folder of Markdown you edit by hand — though it can import an existing file-based wiki store (see the migration chapters later).
- **Not a general document-ingestion pipeline.** It's not built to bulk-load arbitrary PDFs or websites; its primary knowledge source is supported coding sessions, plus what you save directly with `rag save`.
- **Not proof of a live rollout.** The implementation and installer are shipped
  in this repository, but the global Codex install and end-to-end smoke tests
  remain open until backlog 0.2 is completed.
- **Not zero-config.** It expects PostgreSQL 17 with `pgvector`, a running Ollama with the `bge-m3` model pulled, and a logged-in Codex or Claude CLI. There's real infrastructure here in exchange for the search quality and transactional safety a database buys you.

## Next →

[02 · The mental model](02-mental-model.md) — documents, domains, edges, and chunks; two-signal search; the write gateway; and the mining loop, at a glance.
