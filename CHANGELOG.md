# Changelog

All notable changes to agentic-rag are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). It is **pre-1.0** — the entries below summarize
milestones rather than every commit, and interfaces may still change between `0.x` releases.

## [Unreleased]

_Nothing yet._

## [0.5.0] - 2026-09-06

### Added
- **Antigravity CLI (`agy`) compaction continuity.** `rag install --agy`
  merges one named hook (`SessionStart`, `PreInvocation`, `Stop`) into
  `~/.gemini/config/hooks.json` with check mode, unique backup, and a
  target-aware rollback record. `SessionStart` injects pins, domains, project
  knowledge, and the checkpoint as an ephemeral message; `PreInvocation`
  treats a `/compact` turn as PreCompact (checkpoint, enrichment, versioned
  `assets/agy/compact_prompt.md`), detects an automatic-compaction marker
  after the fact (boundary, handoff, checkpoint re-injection), and recalls
  error signatures; `Stop` stores the `/compact` summary as the handoff and
  queues mining. Mining, enrichment, and checkpoint cursors understand the
  Antigravity transcript step format (`agy-step-<n>`). Facts about Gemini
  3.8 Flash / 3.1 Pro (1,048,576 tokens) and Antigravity's hook/compaction
  behaviour are recorded in `docs/00-whats-new-in-0.5.md`.
- **Bounded project context (issue #9).** Source-backed stable/recent profile
  references with audited asynchronous refresh, scoped EN/DE selective recall
  on explicit project/history prompts, and post-output receipts; shared by the
  reader CLI/MCP and the hooks (migration 014).
- **Retrieval evidence quality (issue #8).** Diverse bounded hybrid candidates,
  query-centered contiguous spans with chunk citations, exact-symbol
  preservation, optional two-hop evidence-bearing graph expansion, and a
  validated local reranker seam (migration 013).
- **Claim evidence and inference status (issue #7).** Mined claims retain
  bounded source spans, event identity, speaker and kind; distinct event counts
  exclude assistant corroboration; hooks and retrieval expose evidence status.
- **Atomic fact validity (issue #6).** Evidence-backed immutable assertions with
  explicit replacement, extension, expiry, and as-of/history retrieval;
  `rag assert`, `rag search --as-of/--history`.
- **Consistent project applicability (issue #5).** CLI/MCP scope selectors,
  Git-worktree/symlink normalization, before-limit retrieval and every-hop graph
  filtering, scoped hooks/pins, equal-known-scope curation and audited legacy
  repair. Migration 010 keeps unknown distinct from explicit global scope;
  scope-only repairs preserve content timestamps.
- **Reproducible memory benchmark (issue #3).** `rag benchmark run/compare` uses a
  versioned synthetic EN/DE corpus and isolated local database. It separates
  curated retrieval from session extraction and optional answers/judging, records
  source recall/MRR, failure denominators, context/latency/indexing and explicit
  unknown provider costs, and guards equal-budget comparisons. Offline CI contracts
  require no services or provider credentials.

### Fixed
- **Lossless, replay-safe session ingestion (issue #4).** Mining now resumes
  bounded source windows without skipping clipped prose and persists accepted
  extraction batches before atomic gateway application. Crash recovery reuses
  the accepted output; continued windows do not spend failure attempts. Native
  Codex messages are supported, appends during processing request another pass,
  and `rag status` exposes batch/source progress. Apply migration 009 first;
  historical source recovery is explicit and continuity digests remain unchanged.

### Changed
- **Price-aware Codex context policy.** The managed Codex window is now
  350000 tokens with total-scope automatic compaction at 250000. This keeps the
  existing 100K reserve while adding a nominal 22K buffer below GPT-5.6's
  higher-pricing boundary at more than 272K input tokens. An unusually large
  incoming prompt can still cross the boundary because Codex's pre-turn check
  occurs before recording the new prompt, so the lower threshold reduces risk
  rather than acting as a hard cap.

## [0.4.2] - 2026-09-04

### Fixed
- **Checkpoint enrichment no longer fails on its own subject matter**
  (issue #2). The enrichment job now screens model output value by value: a
  transcript-, diff-, or dialogue-shaped value, an evidence item whose claim
  is not a verbatim part of a digest fragment, or a slug the digest never
  references is dropped on its own and recorded on the checkpoint as
  `enrichment <field>: N items dropped (<reason>)`, which the renderer's
  `Warnings:` line shows. A credential in the output or a malformed shape
  still fails the job into `last_error`, and the store's own gate
  (`validate_enrichment`) stays all-or-nothing. The word guard for
  `transcript`, `diff`, and `body` exempts path and identifier forms such as
  `transcript.py`, `hooks/transcript`, or `transcript_delta`.

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
