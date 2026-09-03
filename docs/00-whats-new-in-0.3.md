# What’s New in 0.3.0

agentic-rag 0.3.0 adds durable continuity for Codex sessions that cross a
context-compaction boundary. It keeps the existing PostgreSQL + pgvector
knowledge engine as the canonical store while allowing native Codex memories
to operate alongside it.

## Codex compaction continuity

Six lifecycle handlers now cover the whole session boundary:

- `PreCompact` captures a bounded, deterministic continuation checkpoint before
  Codex compacts the active context.
- `PostCompact` records the matching boundary without attempting unsupported
  context injection.
- `SessionStart(source="compact")` restores the same-session checkpoint,
  including goals, decisions, repository state, verified tests, blockers, and
  the next concrete action.
- `SessionEnd` captures the final transcript delta; `Stop` and
  `UserPromptSubmit` retain their mining and recall roles.

Checkpoint persistence is audited and non-deleting. Model-assisted enrichment
runs asynchronously, so compaction is never held open by a provider call.
Rendered state includes age and project-applicability labels so historical
repository details are not silently presented as current.

## Native memories and the compact prompt

The Codex installer can enable native memories and install a versioned global
compact prompt. The default managed policy uses a 600,000-token context window
and compacts at 500,000 total tokens, leaving a 100K reserve. Memory extraction
and consolidation use `gpt-5.6-luna` by default.

Native memories are complementary. agentic-rag remains the durable,
searchable, auditable source of truth for knowledge and explicit continuation
state.

## Safe, recoverable installation

Preview the exact changes before writing anything:

```bash
uv run rag init-db
uv run rag install --codex --check
uv run rag install --codex
```

The installer preserves foreign TOML settings and hook entries, validates the
staged configuration with an isolated Codex process, creates unique backups,
and prints a conflict-safe rollback command. After installation, start Codex,
open `/hooks`, inspect the six agentic-rag commands and trust only the hashes
you reviewed.

## Provider-neutral mining and recovery

Mining, curation, and checkpoint enrichment now share a provider-neutral seam.
Codex with ChatGPT login and Claude with its supported authentication remain
available. Provider-wide failures return work to the queue without consuming
its attempt budget, apply bounded backoff, and appear in `rag status` and
session-start context.

Provider-bound transcript and pin copies are secret-stripped without mutating
the canonical stored pins. Diagnostics are redacted before they are bounded or
persisted. The release lock also uses `cryptography` 50.0.1, above the patched
50.0.0 floor for CVE-2026-69247.

## Upgrade notes

1. Pull or download v0.3.0 and run `uv sync`.
2. Run `uv run rag init-db` to apply migrations 006 and 007.
3. Preview and apply the Codex integration with the commands above.
4. Review `/hooks`, then run `uv run rag status`.

The 600K/500K policy is intentionally configurable. Contexts above the
provider’s higher-pricing boundary can cost more and take longer, so measure
real sessions and lower the compaction threshold if the trade-off is not worth
it for your workload.

For the complete behavior and recovery contract, continue with
[Quick start](03-quick-start.md), [Privacy, cost & control](07-privacy-and-cost.md),
and the [CLI & MCP reference](11-reference-cli-and-mcp.md).
