# Changelog

All notable changes to agentic-rag are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). It is **pre-1.0** — the entries below summarize
milestones rather than every commit, and interfaces may still change between `0.x` releases.

## [Unreleased]

## [0.4.1] - 2026-09-04

### Fixed
- **Handoff extraction ignores tags quoted in the prose.** The `<summary>`
  block of Claude's `compact_summary` is now bounded by tags on lines of their
  own (the first `<summary>` starting a line after the first `</analysis>`
  ending one, up to the last `</summary>` ending a line). A second live
  `/compact` on 2026-09-04, in a session that discussed this very mechanism,
  showed the previous first-occurrence match storing analysis remainder plus
  a summary fragment because the prose quoted `<summary>` and `</summary>`
  inline.
- **Truncated handoffs keep their tail.** Over `handoff_max_chars` (and over
  the render budget at `SessionStart`) the middle of the handoff is cut out
  instead of its end, so the summary's pending work, current state, and next
  exact action survive alongside its objective. The `…[truncated]` marker now
  stands on a line of its own between head and tail.

## [0.4.0] - 2026-09-04

### Added
- **Claude compaction continuity.** The default `rag install` now wires six
  Claude lifecycle hooks. `PreCompact` prints the versioned compact
  instructions (Claude appends hook stdout to its compaction prompt),
  `PostCompact` stores Claude's `compact_summary` as a bounded, secret-stripped
  handoff on the checkpoint (only the `<summary>` block of Claude's raw
  output; the `<analysis>` scratch block is discarded), `SessionStart`
  restores it with an age label and caps its whole output at Claude's
  10,000-character hook limit — shortening the checkpoint into the remaining
  budget before any section is dropped — and
  `SessionEnd` queues the final delta for every Claude reason within a 1 s
  timeout. Client detection is payload-driven; Codex behavior is unchanged.
- **Managed 1M/500K Claude policy.** The installer sets
  `autoCompactWindow = 500000`, reports (never rewrites) a model without the
  `[1m]` suffix, and warns about `autoCompactEnabled=false` and overriding
  environment variables.
- **Previewable, recoverable Claude install.** `rag install --check` previews
  the settings merge; a changing install writes a unique `settings.json.bak.<id>`
  backup and a mode-0600 rollback record; `rag install --restore <record>` is
  target-aware for Claude and Codex records.
- **Migration 008** adds `handoff`/`handoff_at` to `continuation_checkpoints`;
  `rag status` shows `checkpoint handoff:` freshness.

### Operational verification
- Migration 008 and the Claude installer were exercised on a real macOS
  deployment: `rag install --check` previewed one change, `rag install` wrote
  the six hooks and `autoCompactWindow=500000` with a unique backup and a
  rollback record, and a manual `/compact` proved the PreCompact →
  PostCompact → SessionStart chain end to end (checkpoint, stored handoff,
  `rag status` freshness, no hook errors). That smoke found and fixed the two
  defects noted above before release. Each operator must still review and
  trust the handlers through `/hooks` and confirm `/autocompact`; automatic
  compaction and SessionEnd tail capture should be monitored in normal use.
- Verified in the Codex sources that `PostCompact` completes before
  `SessionStart(source="compact")` runs and that Codex discovers handlers once
  per session — start a fresh Codex session after `rag install --codex`.

## [0.3.0] - 2026-09-03

### Added
- **Codex continuity implementation (live verification pending).** Added provider-neutral,
  audited continuation checkpoints; bounded deterministic capture and
  rendering; asynchronous provider-backed enrichment; six Codex lifecycle
  handlers; and a versioned, reference-oriented compact prompt. `PreCompact`
  persists state without an inline model call, `PostCompact` records only the
  boundary, and `SessionStart(source="compact")` performs restoration.
- **Recoverable Codex installer.** `rag install --codex --check` previews the
  three managed artifacts without writing; `rag install --codex` preserves
  foreign TOML/hooks, stages and validates changes, creates unique backups and
  a mode-0600 rollback record, and prints the exact `--restore` command plus
  `/hooks` trust guidance. Checkpoint and enrichment health now appears in
  `rag status`.
- **Codex context/native-memory policy.** The installer manages a 600000-token
  context window, 500000-token total-scope compaction threshold (100K reserve),
  native Codex memories, and Luna extraction/consolidation. agentic-rag remains
  the canonical durable store; native memories are complementary.
- **Codex provider adapter.** Mining, curation, and bounded checkpoint
  enrichment can use schema-constrained, ephemeral `codex exec` calls with
  configurable model and reasoning effort; the Claude adapter remains
  available as a compatibility rollback.
- **Provider-health visibility.** `rag status` and SessionStart expose sustained
  provider outages and their remediation without leaking subprocess secrets.

### Fixed
- **Patched release lock.** Updated the transitive `cryptography` lock to
  50.0.1, above the 50.0.0 fix floor for CVE-2026-69247.
- **Lossless provider outages.** A missing CLI, timeout, or expired login now
  returns the claimed job to `pending` without consuming an attempt, applies a
  bounded backoff, records atomic health state, and stops the current drain.
- **Provider-bound pin defense in depth.** Mining secret-strips a copy of every
  matching pin body before assembling the provider prompt, without changing
  the stored pin text.
- **Secret-safe diagnostics.** Worker failures are secret-stripped before they
  reach logs or queue state; provider, health, and Codex-probe excerpts redact
  their full input before truncation; and status scrubs stored queue/backup
  diagnostics before display.
- **Codex continuity pre-install verification.** The whole feature diff,
  focused security/preservation checks, isolated wheel installation, complete
  test suite, and immutable temporary-home check mode passed review.

### Operational verification
- Migrations 006/007 and the Codex configuration installer were exercised on a
  real macOS deployment. Native memories, the 600000/500000 context policy, the
  compact prompt, and all six merged handlers passed the idempotent post-install
  check, `rag status`, and host-side `codex doctor`. Each operator must still
  review and trust the installed handler hashes through `/hooks`; long-context
  compaction and outage/recovery behavior should be monitored in normal use.

## [0.2.0] - 2026-07-09

Cross-platform (Windows) portability hardening. These changes remove the hard
blockers to importing and running the core on non-POSIX platforms and are
verified on macOS/Linux. **Native Windows is not yet verified end-to-end** —
background-job scheduling (Task Scheduler) and a real-Windows test pass remain.

### Fixed
- **Cross-platform worker lock.** The single-writer singleton no longer does an
  unconditional top-level `import fcntl`, which made `agentic_rag.worker`
  unimportable on Windows. The non-blocking exclusive lock is now dispatched by
  platform — `fcntl.flock` on POSIX, `msvcrt.locking` on Windows — behind an
  identical "return a held handle or `None`, never crash" contract.
- **UTF-8 subprocess decoding.** Output of the `claude` CLI is now decoded as
  UTF-8 explicitly (`errors="replace"`), so non-ASCII content (e.g. German
  umlauts) is no longer mangled on platforms whose default text encoding is not
  UTF-8 (Windows `cp1252`).
- **PATH resolution of the `claude` CLI.** The LLM seam and MCP registration
  resolve the CLI through `shutil.which` before spawning, so a bare `claude`
  also resolves where the executable is a `claude.cmd` shim (Windows). Falls
  back to the configured name so the existing "binary not found" error still
  fires with a helpful message.

## [0.1.0] - 2026-07-09

Initial public release.

### Added
- **Storage layer:** PostgreSQL + pgvector document store with hybrid search (full-text +
  vector similarity) and a curated knowledge graph of typed edges between documents.
- **Claude Code integration:** hooks for session-start context injection and transcript
  mining, plus MCP servers exposing memory search, retrieval, and curation tools to Claude
  Code sessions.
- **Autonomous curation:** `claude -p`-driven background jobs that mine session transcripts
  into candidate documents/edges and curate them (dedup, review, promote/refute) without
  blocking interactive use.
- **Cross-platform install:** a single install command that provisions the right background
  scheduler for the platform — `launchd` on macOS; documented `cron`/`systemd` recipes to set up on Linux.
- **Migration tooling:** a generic `migrate` importer for bringing existing wiki-style
  document collections into the store.
- **CLI (`rag`):** commands for search, review, pin management, domain administration, and
  maintenance (log rotation, status reporting).
