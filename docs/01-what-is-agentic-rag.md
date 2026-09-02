# What is agentic-rag?

*What you'll learn: the one-paragraph pitch, who this is for, and what agentic-rag is — and isn't.*

## The pitch

agentic-rag is a long-term memory for [Claude Code](https://docs.claude.com/en/docs/claude-code), backed by PostgreSQL and pgvector. It stores what you and Claude learn as a searchable knowledge graph — documents, chunks, and typed edges between them — and finds it again with hybrid vector + full-text search. The distinctive part: it mostly fills itself. When a session ends, agentic-rag mines the transcript for durable facts, lessons, and error signals, and writes the ones worth keeping through a single audited gateway. It runs on your own machine and uses the Codex or Claude CLI provider you configure.

## Who it's for

You, if you use Claude Code across many sessions and are tired of re-explaining the same context, re-discovering the same bug, or losing a hard-won decision the moment the terminal closes. It's aimed at a developer evaluating or installing a memory layer for their own Claude Code setup, and at a contributor who wants to extend it. It expects you're comfortable running a local Postgres instance — this is infrastructure you host, not a service you sign up for.

## What it is

- **A hybrid search engine over your own knowledge.** Every document is chunked and embedded via a local multilingual model (`bge-m3`), so semantic search works in any language, and is also keyword-indexed for English and German full-text. Search blends vector similarity with lexical ranking into one result list — better recall than either alone.
- **A memory that writes itself.** Session mining reads your Claude Code transcripts and turns what you learned into new documents — memories, lessons, and recognizable error signals — automatically, without you stopping to write anything down.
- **Self-curating.** A background process de-duplicates near-identical entries, flags dangling links and stale pins, and gives you a `rag review` report instead of letting the store rot silently.
- **Local-first and provider-configurable.** Your data lives in a Postgres database on your machine (or one you control). Mining and curation call the configured Codex or Claude CLI. Embeddings are always local (Ollama), and there's no separate hosted RAG service in the loop.
- **RAM-lean.** There's no always-on daemon beyond Postgres and Ollama themselves. The background worker is single-writer and event-driven; between sessions, agentic-rag's own footprint is close to zero.
- **Data-safety-first.** Writes go through one gateway that strips secret-shaped tokens before anything reaches disk, refuting a document archives it instead of deleting it, and backups get a real weekly restore-test — not just a file that might be a backup.

## What it is NOT

- **Not a hosted product.** There's no managed backend to sign up for. You run Postgres and Ollama; agentic-rag is the layer that connects them to Claude Code.
- **Not a hosted RAG service.** It doesn't call a third-party RAG backend — LLM work goes through your configured local Codex or Claude CLI. If that provider is unavailable, jobs remain pending and the outage is surfaced.
- **Not a file-based wiki.** Knowledge lives in Postgres, not a folder of Markdown you edit by hand — though it can import an existing file-based wiki store (see the migration chapters later).
- **Not a general document-ingestion pipeline.** It's not built to bulk-load arbitrary PDFs or websites; its primary knowledge source is your own Claude Code sessions, plus what you save directly with `rag save`.
- **Not zero-config.** It expects PostgreSQL 17 with `pgvector`, a running Ollama with the `bge-m3` model pulled, and a logged-in Codex or Claude CLI. There's real infrastructure here in exchange for the search quality and transactional safety a database buys you.

## Next →

[02 · The mental model](02-mental-model.md) — documents, domains, edges, and chunks; two-signal search; the write gateway; and the mining loop, at a glance.
