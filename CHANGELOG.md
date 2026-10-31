# Changelog

All notable changes to agentic-rag are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). It is **pre-1.0** — the entries below summarize
milestones rather than every commit, and interfaces may still change between `0.x` releases.

## [0.6.18] - 2026-10-31

- Preserve table and sequence ACLs during in-place backup restoration: reset inherited default grants and restore the archive in one transaction, committing only after both PostgreSQL tools succeed. Internal dashboard/tracing state and protected history remain inaccessible to knowledge roles after restore.
- Add opt-in pattern synthesis (Issue65): a scoped, default-off policy per domain and project lets the existing worker ask the configured provider for at most three source-linked pattern suggestions over at least three independent user events across three original memories. Patterns are `dtype=synthesis` inferences written through the audited claim gateway, with exact `ev1`/`src1` citations; they never become user statements and never feed other patterns.
- Add `rag pattern preview|status|list|show|enable|disable|backfill|recover`, four read and three write MCP tools (`memory_pattern_preview`, `memory_pattern_status`, `memory_patterns`, `memory_pattern`, `memory_pattern_policy`, `memory_pattern_backfill`, `memory_pattern_recover`) locally and on the central service, and `[synthesis]` configuration with finite input, output, time and per-tick limits.
- Preview is provider- and write-free. Enabling records a forward boundary; history needs an explicit bounded backfill. Accepted provider output is committed before application, retries reuse it, and a stable application key prevents duplicates. Outages keep runs pending; parked accepted runs are re-queued explicitly without a new provider call. Forward processing records which originals a finished run analysed (per enable epoch), so a late-committing save is never skipped; runs are fitted to the complete input budget before any call (the rest stays pending, oversized memories are reported, never consumed) and include a bounded window of recently analysed memories as context so recurrence can span adjacent runs.
- Withhold a pattern on every read path (get, evidence, graph, search eligibility, pattern tools, dashboard browse) when a cited memory, span, source, authorization or the policy changes, including withdraw-reinstate cycles and time-only expiry.
- Add additive migration030 (policies, backfills, runs, processed membership, patterns, dependencies, `rag_pattern_current`, redefined `claim_eligible`/`assertion_eligible`); upgrade from 0.6.17 rehearsed on populated copies (PB-065-OPS). Before the first enable every process with direct database access must run 0.6.18 (observable gate B0); once a pattern exists, a code-only rollback to 0.6.17 is unsupported and the way back is the verified pre-upgrade backup. The central worker loop now schedules pattern runs. Frozen-fixture measurement in `docs/benchmarks/2026-10-31-pattern-synthesis/` (scripted provider, not a model-quality figure).

## [0.6.17] - 2026-10-31

- Add opt-in EN/DE temporal search (Issue64): `temporal=auto|off|prefer|filter` with optional `reference` and `timezone` on `rag search`, local/remote `memory_search` and REST. A bounded standard-library grammar maps yesterday/gestern, last week/letzte Woche, next month/nächsten Monat, ISO/German full dates and inclusive ranges to half-open UTC intervals in a named IANA zone; ambiguous or unsupported forms are reported, never guessed.
- Order (`prefer`) or strictly filter (`filter`) already eligible candidates by canonical event time: the assertion event, otherwise qualifying active source times, never import time. Graph-expanded hits are re-checked. Responses add a `temporal` explanation and per-hit `evidence.temporal` only when interpretation was requested or applied; legacy envelopes are unchanged.
- Add `[temporal] enabled` (default `false`) and `timezone` (default `UTC`). Soft mode keeps the base order on metadata failure; hard mode fails closed. Client-mode `rag search` now uses the central service; new arguments are sent only when set, so 0.6.16 services keep accepting legacy calls.
- Add the independently reviewed and full-copy-rehearsed PB-064-LIVE path from existing0.6.15/schema028 directly to0.6.17, applying bundled029 with original-row/ACL/owner preservation, retained old-code recovery and secure fresh-backup checks.
- No new schema change (schema029). Populated 0.6.16 compatibility, actual old-code rollback and frozen held-out measurements are in `docs/benchmarks/2026-10-31-temporal-query/`.

## [0.6.16] - 2026-10-31

- Add source evidence contract v1 (Issue63): `memory_evidence`/`memory_evidence_history` in local and central MCP/REST, `rag evidence show|history` and a dashboard drilldown with exact stored quotes, opaque source/span references, event time or unknown, separate source trust, claim review, fact lifecycle and exclusion reasons. No host session or file locator is returned.
- Bind reviews and source-trust changes to the inspected version via optional `expected_version` (required by the dashboard). Stale decisions, including withdraw→reinstate cycles, conflict with no state, history or audit change. Legacy no-token calls keep working and still invalidate inspected versions.
- Add additive migration029: persisted, restore-stable source/claim revisions and append-only, scoped decision history written by triggers; no original row, grant or audit record is rewritten and no review is backfilled. Upgrade from 0.6.15 rehearsed on populated copies (PB-063-UPGRADE).
- Fix thematic history labels: a replacement in another domain no longer marks a current value as superseded, matching the canonical domain-isolated predicate.

## [0.6.15] - 2026-10-30

- Add administrator Settings with MiniLM L6 EN/DE, mMARCO DE/EN (new default) and Jina tiny English-only presets, pinned optional offline CPU runtime and durable revision-checked selection.
- Add additive audit-kind migration028, verified0.6.14 upgrade/retry/code rollback and explicit legacy model configuration support; preserve original knowledge and citation payloads.
- Add sealed bilingual public failure-derived evaluation, target-class service resource accounting and populated code/config rollback evidence.

## [0.6.14] - 2026-10-30

- Add independent immutable embedding profiles and bounded Ollama/compatible HTTP adapters, protected credential references and offline inspection/synthetic probes. Existing Claude/Codex CLI login remains supported.
- Add opt-in model-bound generations with dimension-specific HNSW indexes, bounded resumable rebuilds, current-source coverage checks, atomic selection and catch-up rollback that preserves post-cutover knowledge.
- Keep managed search/dedup in one verified space, retain contextual lexical recall and original citations, and degrade to lexical evidence on model/identity failure without provider fallback.
- Preserve legacy columns and all original rows through additive migration027; extend populated local/central upgrade and strict-restore verification. Historical legacy vectors remain explicitly unverified until rebuilt.
- Bound new HTTP jobs by the configured attempt budget, honor shared foreground model admission and invalidate setup checks after either provider slot or credential changes.

## [0.6.13] - 2026-10-30

- Add bounded metadata-only request tracing with generated request IDs, scoped keyset filters and current job outcomes in the dashboard, REST API and CLI (Issue60).
- Preserve transactional source/foreground job origins across retry and trace retention. HTTP acceptance remains distinct from successful knowledge application.
- Restrict trace rows, totals, details and paginated exports to current authority; exclude credentials, request payloads, raw URLs and exception text.
- Bound tracing retention, storage and capture failure independently from canonical knowledge and its audited writes. Additive migration026 preserves populated025 originals.

## [0.6.12] - 2026-10-30

- Add an authenticated responsive dashboard with one-time first-admin bootstrap, protected browser sessions and scoped knowledge/source browsing.
- Add resumable four-path setup checks, real authenticated target negotiation, explicit synthetic model probes and file-owned configuration exports.
- Add validated policy preview/apply, enrollment, once-only API credentials, rotation/revocation, restart-recoverable administrative audit and bounded client freshness metadata.
- Serialize policy commits with exact session revocation and expiry; keep new control tables owner-only despite custom default grants or inherited role authority.
- Preserve local and protocol1 clients; additive migration025 extends the verified upgrade/restore path from populated024.


## [Unreleased]

## [0.6.11] - 2026-10-30

- Add optional durable foreground tool requests with owner/team quotas, fair
  dispatch, finite retention, status/cancel handles and atomic write/result commit.
  Compatible synchronous protocol-1 endpoints remain available.
- Prefer interactive context/retrieval over source extraction and bounded shared
  embedding pages. Keep one central source worker and fixed foreground consumers.
- Package native Claude/Codex plugins and a separate Gemini CLI extension; reuse
  existing source/checkpoint transport and preserve original input at compaction.
- Add private bounded request outboxes and plugin status/cancel tools. Host UI
  observations, reference-host measurements and rollout limits are documented in
  [the plugin operations guide](docs/14-agent-plugins.md).
- Known non-blocking status detail: a completed request may retain an earlier
  transient deferral code; successful result consumption is unaffected. Tracked
  as LOW-012 in issue #75.

## [0.6.10] - 2026-10-29

### Added
- Add the optional protocol1 REST/remote-MCP service foundation with separate
  static machine/user identities, human login, revocation and scoped engine
  connections (Issue58). Local stdio behavior remains available.
- Add durable client spooling and compaction continuity, owned source receipts,
  serial fenced workers, explicit reauthorization and finite storage/log limits.
- Add explicit session teams: colleagues share retained redacted source logs and
  checkpoints through bounded REST reads while keeping uploader/audit identity
  and job mutation authority distinct. Department access is server-enforced.
- Add operator CLI, populated legacy inventory, strict verified backups and
  additive local/remote upgrade procedures with private deployment examples.
- Add service authorization/state migrations021/022 and an additive023 upgrade
  for scoped evidence lookup performance and original022 uploader profiles.
  Preserve original session fields and require fresh login for pre-profile sessions.
- Prioritize interactive API processes over serial background extraction with
  explicit CPU weights and a one-CPU worker quota.
- Preserve canonical knowledge and existing embeddings during additive upgrades.
  Production rollout remains separate.

## [0.6.9] - 2026-10-29

### Dependencies
- Upgrade the locked certifi CA bundle from 2026.6.17 to 2026.10.19,
  including removal of compromised emSign roots (Dependabot alert20).
- Existing installations can update the isolated runtime and restart clients;
  no schema migration or knowledge reprocessing is required. Runtime recovery
  must account for the older bundle retaining the affected trust anchors.

## [0.6.8] - 2026-10-29

### Dependencies
- Upgrade the locked MCP SDK from 1.28.1 to 1.30.0. Retain the existing
  stdio tool contracts and read-only registration; no data migration is required.
- Existing installations can update their isolated runtime and restart MCP
  processes. Recovery uses the prior runtime with the same unchanged database.

## [0.6.7] - 2026-10-29

### Documentation
- Index the standalone/central multi-VM service foundation and 15 follow-up
  feature requests as planned work in BACKLOG.md ([Issue58](https://github.com/phense/agentic-rag/issues/58)).
- Keep GitHub Issues canonical and explicitly require verified upgrades for
  installations that remain local. This release introduces no service behavior,
  schema migration or deployment change.

## [0.6.6] - 2026-10-05

### Fixed
- Parse native Codex rollout response items for checkpoint enrichment instead of
  accepting an empty digest; share an opaque cursor with bounded checkpoint capture
  ([Issue12](https://github.com/phense/agentic-rag/issues/12)).
- Preserve existing Claude/Antigravity readers, lossless mining-window cursors,
  queued work and historical checkpoints without a schema migration or bulk replay.
- Document populated018/019 compatibility, local before/after evidence, and the
  outstanding sustained-session acceptance criteria.

## [0.6.5] - 2026-10-05

### Fixed
- Keep atomic assertion comparison, deduplication, locks and temporal supersession
  within exact project/domain/entity/attribute boundaries ([Issue48](https://github.com/phense/agentic-rag/issues/48)).
- Add retryable migration020 to correct the shared reader function without rewriting
  assertions, source attachments, graph history, pins or audit records.
- Retry simultaneous assertion slug-allocation collisions through gateway savepoints;
  preserve existing slug format and caller-owned transaction boundaries.
- Document populated018/019 upgrade, writer cutover, read-only code recovery and
  aggregate diagnosis of historical cross-domain edges.

## [0.6.4] - 2026-10-05

### Fixed
- Reject failed or interrupted maintenance backup restores and inventory all restored
  public tables without comparing to a different live snapshot ([Issue41](https://github.com/phense/agentic-rag/issues/41)).
- Use fresh scratch databases and verify their identity and ownership before cleanup.
  Successful restore reports explicitly leave source fidelity and ACL preservation unverified.

## [0.6.3] - 2026-10-04

### Fixed
- Apply the existing 24-hour curation freshness gate after the worker queue drain;
  explicit queued curation still runs, and provider outages still skip the automatic
  pass ([Issue17](https://github.com/phense/agentic-rag/issues/17)).
- Retain built SessionStart context when maintenance scheduling or connection
  cleanup fails. Emit a separate bounded, sanitized `systemMessage` warning without
  consuming the context budget ([Issue23](https://github.com/phense/agentic-rag/issues/23)).
- Document the code-only 0.6.2 upgrade and recovery in
  [Session mining & curation](docs/05-session-mining-and-curation.md#worker-and-sessionstart-fix-upgrade).

## [0.6.2] - 2026-10-04

### Fixed
- Upgrade locked PyJWT from 2.13.0 to 2.15.0 for the upstream JWT/JWK
  security corrections ([PR11](https://github.com/phense/agentic-rag/pull/11),
  [Issue37](https://github.com/phense/agentic-rag/issues/37)); retain AnyIO 4.14.2.
- Document stdio deployment applicability and the advisory with incomplete
  patched-version metadata in [Contributing](docs/12-contributing.md#dependency-security-updates).

## [0.6.1] - 2026-10-04

### Fixed
- Upgrade locked AnyIO from 4.14.1 to 4.14.2 for its process-group, IDNA TLS
  and process-worker stderr security corrections ([PR10](https://github.com/phense/agentic-rag/pull/10),
  [Issue37](https://github.com/phense/agentic-rag/issues/37)).
- Fix the stale 0.5.0 metadata assertion while retaining historical release coverage.
- Document isolated dependency validation and explicit caller-path recovery in
  [Contributing](docs/12-contributing.md#dependency-security-updates).

## [0.6.0] - 2026-10-04

### Added
- Evidence-backed entity identities and project/domain-scoped aliases with original
  history and audited revocation (018; [Issue33](https://github.com/phense/agentic-rag/issues/33)).
- Exact input/model embedding reuse and bounded preprocessing under ordered audited
  writes (019; [Issue34](https://github.com/phense/agentic-rag/issues/34)).
- Offline failure evaluation with sealed development/held-out profiles, private local
  confirmed-correction evaluation and explicit public configured-provider mining
  comparison ([Issue35](https://github.com/phense/agentic-rag/issues/35)).
- Adaptive exact/lexical/semantic retrieval, permission-safe caches, contextual original-backed
  chunk indexing (015) and filter-aware vector retrieval (016).
- [0.6.0 feature map and measured limits](docs/00-whats-new-in-0.6.md), plus
  [actual approved 018→019 production acceptance](docs/verification/features9-10-production-adoption.md).
- Local incremental `rag summary` and reader-only `memory_summary`, extending
  bounded project profiles with original excerpts, source/version drill-down,
  explicit inference/review labels and correction/expiry/access invalidation.
  Audited refresh reuses unchanged entries; additive017 cache preserves baseline
  access on016 and code rollback. See [original/synthetic paired measurements](docs/benchmarks/2026-10-03-thematic-summaries/README.md).
- Bounded read-only `rag research` and `memory_research`: compound-question
  retrieval, relevant graph passages, original citations, source-qualified
  quoted support, disagreement and missing evidence, with call/context/time
  caps and process cleanup. Local processing is the default; configured
  provider assessment requires explicit opt-in. Schema016 is unchanged.
  See [measurements and compatibility](docs/benchmarks/2026-10-03-bounded-research/README.md).
- Selective local multilingual neural ordering for ambiguous auto searches, with
  bounded inference, original-source preservation and a no-migration fallback.
  See [paired quality/latency and rollback evidence](docs/benchmarks/2026-10-03-neural-rerank/README.md).
- Native OpenCode RAG adapter with startup context, selective recall, matched
  checkpoint/handoff, bounded transcript projection and debounced idle mining.
  Install on the execution host with `rag install --opencode`; existing MCP
  configuration and other plugins are preserved. See [scope and limits](docs/opencode.md).
- Verification of DeepSeek Flash native manual compaction/restoration using a
  synthetic test database, plus canonical context delivery and an actual
  read-only RAG search through T3 on the Mac. See [evidence](docs/verification/opencode.md).
  Sustained automatic compaction and automatic Flash/Pro routing are not claimed.

### Changed
- Require every future PR to include a `0.0.1` patch bump and matching documentation.
  Minor and major bumps require an explicit manual maintainer instruction and replace
  that PR's normal patch increment. Keep package/lock/README/changelog versions aligned;
  stacked PRs use consecutive patch versions. See [the mandatory project rule](AGENTS.md#mandatory-version-bump-and-documentation-for-every-pr).

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
