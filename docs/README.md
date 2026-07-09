# agentic-rag Handbook

A single, progressively-ordered read — from the mental model through everyday
use, configuration, and extension, to the engine's architecture and design
rationale. Each chapter says up front what you'll learn.

## Understand
- [01 · What is agentic-rag?](01-what-is-agentic-rag.md) — the pitch, who it's for, what it is and isn't.
- [02 · The mental model](02-mental-model.md) — documents, domains, edges, chunks; two-signal search; the write gateway; the mining loop at a glance.

## Use
- [03 · Quick start](03-quick-start.md) — prerequisites, exact install order, your first save and search.
- [04 · Working with your memory](04-working-with-memory.md) — save / get / search / pin, domains, and the MCP tools inside a Claude session.
- [05 · Session mining & curation](05-session-mining-and-curation.md) — how your Claude sessions become durable knowledge, and how the store curates itself.

## Configure
- [06 · Configuration reference](06-configuration-reference.md) — every `config.toml` setting and environment override, with defaults.
- [07 · Privacy, cost & control](07-privacy-and-cost.md) — subscription-only (no API key), secret stripping, the role matrix, and backups.

## Extend
- [08 · Knowledge domains & import](08-knowledge-domains-and-import.md) — grow and curate domains, and import an existing llm-wiki store.
- [09 · Maintenance & backups](09-maintenance-and-backups.md) — `rag backup`/`restore`, `rag maintenance`, and scheduling on macOS and Linux.

## Develop
- [10 · Architecture](10-architecture.md) — the schema, roles, indexes, gateway, worker, hooks, and MCP servers.
- [11 · Reference — CLI & MCP](11-reference-cli-and-mcp.md) — every command and flag, the MCP tools, key SQL functions, and exit codes.
- [12 · Contributing](12-contributing.md) — dev setup, tests, the doc-reminder hook, and code layout.

## Appendix
- [99 · Design notes & rationale](99-design-notes.md) — why Postgres over files, why a single writer, why derived domains, and the data-safety choices.
