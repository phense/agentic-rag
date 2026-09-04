# agentic-rag Handbook

A single, progressively-ordered read — from provider-neutral durable memory and
Claude/Codex compaction continuity through everyday use, configuration, extension,
architecture, and design rationale. Each chapter says up front what you'll
learn. Shipped versus still-planned rollout state lives in
[`../FEATURES.md`](../FEATURES.md) and the blocker-first
[`../BACKLOG.md`](../BACKLOG.md).

## Start here
- [What’s New in 0.4.0](00-whats-new-in-0.4.md) — Claude compaction continuity, the managed 1M/500K policy, handoff capture, check/restore for the Claude install.
- [What’s New in 0.3.0](00-whats-new-in-0.3.md) — Codex continuity, native memories, safe installation, upgrade steps, and operational boundaries.

## Understand
- [01 · What is agentic-rag?](01-what-is-agentic-rag.md) — provider-neutral memory, Codex continuity, native-memory complementarity, and boundaries.
- [02 · The mental model](02-mental-model.md) — documents, graph/search, the write gateway, mining, and continuation checkpoints.

## Use
- [03 · Quick start](03-quick-start.md) — prerequisites, the Claude six-hook install and the Codex target, check/trust/verify/rollback for both, and your first save/search.
- [04 · Working with your memory](04-working-with-memory.md) — save / get / search / pin, domains, and the MCP tools inside a Claude session.
- [05 · Session mining & curation](05-session-mining-and-curation.md) — durable mining, the Claude and Codex checkpoint lifecycle/restoration (including the Claude handoff), provider recovery, and curation.

## Configure
- [06 · Configuration reference](06-configuration-reference.md) — agentic-rag defaults, the `[continuity]` handoff/context caps, the managed Claude 1M/500K policy, and the managed 600K/500K Codex policy.
- [07 · Privacy, cost & control](07-privacy-and-cost.md) — provider calls, native/external memory, long-context pricing, hook trust, secrets, roles, and recovery.

## Extend
- [08 · Knowledge domains & import](08-knowledge-domains-and-import.md) — grow and curate domains, and import an existing llm-wiki store.
- [09 · Maintenance & backups](09-maintenance-and-backups.md) — `rag backup`/`restore`, `rag maintenance`, and scheduling on macOS and Linux.

## Develop
- [10 · Architecture](10-architecture.md) — schema, roles, gateway, worker, the Claude and Codex hook tables, both checkpoint data flows, installers, and MCP.
- [11 · Reference — CLI & MCP](11-reference-cli-and-mcp.md) — every command/flag, Claude and Codex check/install/restore and hook contracts, MCP, SQL, and exit codes.
- [12 · Contributing](12-contributing.md) — dev setup, tests, the doc-reminder hook, and code layout.

## Appendix
- [99 · Design notes & rationale](99-design-notes.md) — why Postgres over files, why a single writer, why derived domains, and the data-safety choices.
