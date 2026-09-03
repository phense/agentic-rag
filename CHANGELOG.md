# Changelog

All notable changes to agentic-rag are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). It is **pre-1.0** — the entries below summarize
milestones rather than every commit, and interfaces may still change between `0.x` releases.

## [Unreleased]

### Added
- **Codex continuity implementation (rollout pending).** Added provider-neutral,
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
- **Codex mining provider.** Mining and curation can use schema-constrained,
  ephemeral `codex exec` calls with configurable model and reasoning effort;
  the Claude adapter remains available as a compatibility rollback.
- **Provider-health visibility.** `rag status` and SessionStart expose sustained
  provider outages and their remediation without leaking subprocess secrets.

### Fixed
- **Lossless provider outages.** A missing CLI, timeout, or expired login now
  returns the claimed job to `pending` without consuming an attempt, applies a
  bounded backoff, records atomic health state, and stops the current drain.

### Not yet rolled out
- The whole-branch pre-install review and the live global install, `/hooks`
  trust, manual/automatic compaction, provider recovery, and SessionEnd smoke
  tests remain open in backlog 0.1/0.2. This changelog does not claim the
  global Codex configuration is installed or operationally verified.

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
