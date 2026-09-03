# agentic-rag — feature registry

This registry separates behavior present in the repository from operational
deployment. A feature is not called live merely because its implementation and
tests exist.

**Status:** ✅ shipped in code · 🔵 in progress · ⬜ planned · 🔒 blocked by a
precondition · ⏸ paused. The numbered source of truth for unfinished work is
[`BACKLOG.md`](BACKLOG.md).

## Memory platform

- ✅ **Durable local store.** PostgreSQL + pgvector documents, structural
  chunks, fixed document/predicate vocabularies, dangling-safe typed graph
  edges, and archive/refute history are shipped.
- ✅ **Hybrid retrieval and graph navigation.** HNSW vector search, bilingual
  English/German full-text, deterministic rank fusion, full document lookup,
  neighbors, shortest paths, and timelines are shipped. Retrieval degrades to
  full-text with a warning if Ollama is unavailable.
- ✅ **Canonical audited writes.** CLI, MCP, mining, and migration writes share
  the secret-stripping `save_document()` gateway and least-privilege database
  roles.
- ✅ **Domains and explicit memory tools.** Dynamic domains, save/get/search,
  scoped user-owned pins, read-write MCP tools, and an independently enforced
  read-only MCP surface are shipped.
- ✅ **Provider-neutral session mining.** Schema-constrained Codex and Claude
  CLI adapters, bounded delta-only transcript digests, single-writer background
  jobs, secret-stripped provider-bound matching pin bodies without mutating
  stored pin text, near-duplicate detection, and lossless outage recovery are
  shipped. Claude remains the configuration-only provider rollback.
- ✅ **Curation and human review.** Bounded dangling-edge resolution,
  exact-duplicate merging, contradiction review, inert suggestions,
  refute-as-archive, confirmed admin-only purge, and `rag review` are shipped.
- ✅ **Migration.** Dry-run, backup-gated import of an existing llm-wiki store,
  domain classification/application, and acceptance reports are shipped.
- ✅ **Operations and recovery.** Provider/queue/checkpoint/status reporting,
  local plus opt-in synced backups, retention, deliberate database restore,
  log rotation, scheduled maintenance, and report-only restore-testing are
  shipped.
- ✅ **Claude Code integration.** The legacy no-option installer registers
  read-write/read-only MCP servers and merges the three Claude hooks without
  replacing foreign settings.

## Codex continuity

- ✅ **Provider-neutral checkpoints.** Audited, non-deleting checkpoint
  persistence; deterministic Git/transcript-cursor capture; bounded rendering;
  and asynchronous schema-constrained enrichment are shipped in code.
- ✅ **Six lifecycle handlers.** `SessionStart`, `UserPromptSubmit`, `Stop`,
  `PreCompact`, `PostCompact`, and `SessionEnd` handlers are shipped. Only
  `SessionStart(source="compact")` can restore checkpoint context after
  compaction; `PostCompact` records the boundary and never injects context.
- ✅ **Compact prompt and policy installer.** The versioned prompt and the
  lossless `rag install --codex` transaction are shipped. The managed policy is
  a 600000-token context window, a 500000-token total-scope compaction limit
  (100K reserve), enabled hooks/native Codex memories, and Luna extraction and
  consolidation.
- ✅ **Safe preview, rollback, and health reporting.** Non-writing check mode,
  unique backups, a mode-0600 rollback record, conflict-safe restoration, hook
  trust instructions, and checkpoint/provider fields in `rag status` are
  shipped in code.
- ✅ **Pre-install review.** Whole-branch review, focused security/preservation
  tests, the full suite, isolated wheel installation, and an immutable
  temporary-home check-mode exercise are complete.
- 🔵 **Global Codex rollout.** The real user configuration and database
  migrations are installed: native memories, the 600000/500000 context policy,
  compact prompt, and six merged lifecycle handlers pass the idempotent
  installer probe, `rag status`, and host-side `codex doctor`. Live verification
  remains pending under backlog 0.2: Peter must trust only the six agentic-rag
  hashes through `/hooks`, then exercise manual/automatic compaction, provider
  outage/recovery, and SessionEnd tail capture. Continuity is therefore
  partially installed but not yet claimed operationally proven end to end.

Native Codex memories are complementary: they may adapt Codex from prior work
and remain inspectable with `/memories`. agentic-rag is the canonical store for
durable, searchable, auditable knowledge and explicit continuation state.

## Planned hardening

- ⬜ Measure and tune prompt-recall firing behavior.
- ⬜ Correct curation cadence/audit growth and cap-aware mining cursors.
- ⬜ Define the intended refute-trigger recency semantics, then decide whether
  a recency check is warranted ([BACKLOG 2.2](BACKLOG.md#2--housekeeping--test-coverage)).
- ⬜ Improve worker-death idempotency and complete the listed coverage gaps.
- ⬜ Validate duplicate review under sustained load, normalize interactive save
  confidence, preserve built SessionStart context on maintenance failure, and
  re-resolve installed scheduler paths after environment moves.

The details, dependencies, reasons, and resumption triggers for every planned
item remain in [`BACKLOG.md`](BACKLOG.md).
