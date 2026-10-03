# Change Proposal: Permission-safe query inference reuse

Stable work ID: 5.2; Issue #27. Authorized sequential implementation, 2026-10-03.
Source: merged feature 5.1, `f27acd98e04c7c67d66ca374eded071ac47c0416`.

## Outcome and acceptance

- Reuse bounded HTTP connections and successful query embeddings in long-lived MCP
  processes; one-shot CLI/hook processes close transports on exit.
- Keep at most 256 entries for 300 seconds, scoped by database, caller role,
  project/domain/time selection, model endpoint, dimension and current model digest.
- Check Ollama's current model digest on each reuse; unavailable metadata disables caching.
- Fetch eligible candidates and source evidence from SQL on every call. Cache no results,
  source text, permissions or summaries; correction and expiry apply immediately.
- Handle simultaneous requests, failed inference, TTL/eviction, process fork/shutdown
  and malformed metadata safely. Preserve old public call shapes and warnings.
- Verify populated-state coexistence/rollback, full suites and independent review with
  zero unresolved Critical/High/Medium. Publish three practical paired examples.

## Boundaries and upgrade

Bounded change at the existing embedding/search seams, not a new retrieval subsystem.
No new dependency, schema, persisted index, config migration or data writer. Source and
target use migrations001–014. Old/new clients coexist; restart MCP to adopt or roll back.
No production mutation authorized by read-only Trading test permission. Existing
dependency-security findings remain separately tracked in #37.
