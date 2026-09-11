# OpenCode lifecycle adapter
Work ID: RAG-OC-001; backlog 0.6. User authorized implementation and local installation after Engineering Method publication.

## Acceptance
- AC1: main sessions receive startup/resume and selective prompt context; SDK failure is visible and bounded.
- AC2: compaction captures deterministic state, attaches the matching completed summary, and restores before the next main model call.
- AC3: idle queues sanitized user/assistant prose and tool names with stable identities; no reasoning, tool output, synthetic context or subagent ingestion.
- AC4: install/check/uninstall preserves other configuration and refuses modified loaders; package includes runtime JS.
- AC5: Python/Node and test-database tests, native DeepSeek smoke, independent review, full regression suite and local rollout evidence.

Existing host-adapter seam; no schema migration or new store. Excludes automatic model routing, historical re-mining, a new mining provider and RAG remote publication.
