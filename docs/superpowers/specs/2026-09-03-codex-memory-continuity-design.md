# Codex-native memories and cross-compaction continuity

**Date:** 2026-09-03
**Status:** Approved in chat; implementation pending
**Owner:** Peter
**Scope:** Global Codex memory and compaction configuration, provider-neutral
continuation checkpoints in `agentic-rag`, Codex lifecycle hooks, installation,
documentation, and operational rollout

## 1. Problem

Long Codex sessions can continue through automatic history compaction, but the
current installation does not preserve enough structured execution state across
that boundary. Global Codex configuration enables hooks only. Native local
memories are disabled, there is no dedicated compaction prompt, and
`agentic-rag` has no `PreCompact`, `PostCompact`, or `SessionEnd` integration.

The existing integration already provides useful building blocks:

- `SessionStart` injects pins, project-relevant documents, and service health;
- `UserPromptSubmit` recalls relevant prior knowledge;
- `Stop` queues transcript deltas for durable mining;
- the mining worker, Codex provider, provider-health artifact, and auth circuit
  breaker already fail open and preserve work during provider outages.

Those facilities retain durable knowledge, but they do not explicitly represent
the live state needed to resume unfinished work: current goal, success criteria,
decisions, plan progress, repository state, test evidence, active processes,
blockers, and the next exact action.

## 2. Product boundary

This feature belongs in `agentic-rag`, not a separate repository.
`agentic-rag` is the canonical provider-neutral memory and continuity engine and
already owns the store, transcript mining, retrieval, health handling, hooks, and
idempotent installation. The Codex integration is an adapter over that shared
core, alongside the existing Claude integration.

Codex-native memories remain enabled as a complementary local recall layer:

- **Codex memories:** convenient personal and session-derived recall managed by
  the Codex client;
- **agentic-rag:** canonical, auditable long-term knowledge, standing pins, and
  explicit continuation checkpoints;
- **checked-in files:** authoritative project requirements and execution state
  (`AGENTS.md`, specs, plans, `BACKLOG.md`, and `FEATURES.md`).

Explicit prompts and checked-in instructions outrank both memory layers.
Continuation injection must point to authoritative artifacts rather than copy
large documents into context.

## 3. Goals and non-goals

### Goals

- Enable native Codex memories globally for generation and later injection.
- Trigger automatic compaction early enough to leave room for a high-quality
  handoff.
- Install a versioned, high-quality global compaction prompt.
- Preserve unfinished execution state across any number of manual or automatic
  compactions and across session resume/start boundaries.
- Mine the remaining transcript delta when the main session ends.
- Reuse the current Codex provider-health and authentication circuit breaker.
- Keep every hook fail-open, bounded, idempotent, and safe under duplicate or
  out-of-order delivery.
- Preserve all foreign Codex configuration and hooks during install/update.
- Keep model-visible restored context concise and slug-oriented.

### Non-goals

- Do not replace native Codex compaction, transcript persistence, goals, or
  memories.
- Do not make native Codex memory the authoritative home for project rules.
- Do not create a second database, queue, scheduler, repository, or provider
  authentication flow.
- Do not block compaction or session shutdown on an LLM call, database outage,
  Ollama outage, or expired Codex login.
- Do not parse Codex transcript JSON as a permanent public schema. Transcript
  handling stays isolated behind the existing tolerant adapter and fixtures.
- Do not auto-run `codex login`, browser authentication, or credential repair.
- Do not inject whole specs, plans, backlogs, diffs, logs, or memory documents.

## 4. Selected architecture

### 4.1 Package boundaries

The implementation introduces explicit provider and core boundaries:

```text
agentic_rag/
  continuity/
    model.py          checkpoint data contract and validation
    capture.py        deterministic snapshot and transcript cursor
    store.py          audited persistence and latest-open selection
    render.py         bounded model-visible continuation context
    enrich.py         asynchronous semantic enrichment
  integrations/
    codex/
      config.py       lossless config.toml merge and validation
      hooks.py        lossless hooks.json merge
      install.py      Codex asset installation and reporting
  hooks/
    pre_compact.py
    post_compact.py
    session_end.py
    session_start.py  extended, not replaced
assets/
  codex/
    compact_prompt.md
```

Exact file splits may be adjusted during planning to match existing module size,
but core checkpoint logic must not depend on Codex hook names. Claude or another
client must be able to reuse the same checkpoint contract later.

### 4.2 Two-stage checkpoint capture

`PreCompact` performs a fast synchronous capture and then queues enrichment.
This separates guaranteed continuity from optional semantic quality.

The synchronous stage:

1. Reads the hook payload (`session_id`, `turn_id`, `transcript_path`, `cwd`,
   `model`, and `trigger`).
2. Captures a tolerant transcript cursor without assuming a stable transcript
   schema outside the transcript adapter.
3. Records bounded deterministic repository state when `cwd` is in a Git
   worktree: repository root, branch or detached state, worktree path, HEAD, and
   a capped porcelain status. It never stores full diffs or file contents.
4. Records links to discoverable checked-in execution artifacts.
5. Persists an open checkpoint atomically and idempotently.
6. Enqueues a priority enrichment job for the transcript delta.
7. Exits successfully even if any stage fails, recording only sanitized health
   diagnostics.

Semantic enrichment uses the existing single-writer queue and configured Codex
provider. It extracts the current goal and success criteria, applicable Peter
instructions/approvals, decisions and rejected alternatives, completed and
remaining plan steps, actual test results, known processes/external states,
blockers/risks, next exact action, and relevant `agentic-rag` slugs. The job is
deduplicated by session and transcript cursor. Provider unavailability restores
the job to pending without spending its content retry budget and uses the
existing circuit breaker.

The `PreCompact` hook never waits for enrichment. The Codex-native compaction
prompt independently carries a semantic handoff inside the compacted chat, so an
unfinished enrichment job does not reduce immediate continuity.

### 4.3 Checkpoint contract

A checkpoint is typed operational state rather than a general memory document.
It has at least:

- stable checkpoint id;
- session id and optional turn id;
- creation/update timestamps;
- source event and automatic/manual trigger;
- transcript path fingerprint and cursor, never transcript content as identity;
- project/CWD and repository/worktree/branch/HEAD metadata;
- lifecycle state: `open`, `superseded`, or `completed`;
- capture quality: `snapshot` or `enriched`;
- goal and explicit success criteria;
- applicable instructions and still-valid approvals;
- decisions and rejected alternatives;
- completed and remaining work;
- touched/current files and concise dirty-state summary;
- commands/tests and their observed outcomes;
- active processes and external states when evidenced by the transcript;
- blockers, risks, and next exact action;
- links to specs, plans, `BACKLOG.md`, `FEATURES.md`, and relevant RAG slugs;
- sanitized capture/enrichment warnings.

Only one checkpoint per `(session_id, transcript_cursor)` is current. Repeated
hooks upsert the same record. A newer checkpoint supersedes an older open one for
the same session but does not delete it. Completion may mark the latest checkpoint
completed; it never hard-deletes history.

Checkpoint persistence uses a dedicated PostgreSQL
`continuation_checkpoints` table because selection and lifecycle updates are
structured operational queries, not general document search. A focused
checkpoint gateway owns every insert/update and writes the existing `audit_log`
in the same transaction. Checkpoint enrichment may link to ordinary documents
but must not duplicate them. The table uses archive/supersede state and has no
ordinary hard-delete path.

### 4.4 Compaction and restoration flow

```text
active context
  -> PreCompact: atomic snapshot + enqueue enrichment
  -> native compact prompt: semantic handoff remains in compacted context
  -> Codex compaction
  -> PostCompact: mark compaction outcome and emit UI warning only if needed
  -> SessionStart(source=compact): best checkpoint + pins + relevant RAG slugs
  -> immediate model continuation
```

Codex documents that `SessionStart(source="compact")` runs before the next model
request, including automatic compaction in the middle of a turn. It is therefore
the authoritative restoration point. Current Codex hook output does not allow
`PostCompact` to inject `additionalContext`: plain stdout is ignored and only
the common control/UI fields are accepted. `PostCompact` therefore performs
idempotent bookkeeping (for example, marking that a captured checkpoint crossed
the compaction boundary) and may emit a concise `systemMessage` warning. It does
not duplicate restoration context.

Restoration selects the latest checkpoint for the current session first. On a
fresh session without one, it may select the latest open checkpoint whose
canonical repository root matches the current project. Cross-project fallback is
forbidden. The rendered injection has a strict character/token budget and
contains:

- checkpoint id, timestamp, and quality;
- goal and remaining success criteria;
- concise repository/dirty-state facts;
- last verified test outcomes;
- blocker and next action;
- paths and RAG slugs needed for explicit retrieval;
- provider-health warning only when enrichment is delayed.

The renderer labels stale or mismatched facts rather than presenting them as
current. It does not claim that a process is still alive without a current
verification signal.

### 4.5 Session end and ordinary stops

The current `Stop` hook remains a debounced, fast mechanism that queues transcript
deltas after assistant turns. A new synchronous `SessionEnd` hook performs a
final bounded enqueue when Codex closes, archives, deletes, or idles out the main
thread. It does not run mining inline and emits no model context.

`SessionEnd` has a maximum Codex-enforced timeout of three seconds, so it performs
only import-light validation and queue insertion. Missing transcripts, duplicate
events, unavailable storage, and shutdown races are logged and swallowed. The
next `SessionStart`, `Stop`, or scheduled maintenance pass can recover queued
work. `SessionEnd` and `Stop` share the same transcript cursor and debounce logic.

### 4.6 Global Codex configuration

The installer manages the following intended user-level values while preserving
unrelated settings:

```toml
model_auto_compact_token_limit = 200000
model_auto_compact_token_limit_scope = "total"
experimental_compact_prompt_file = "/Users/peter/.codex/compact_prompt.md"

[features]
hooks = true
memories = true

[memories]
generate_memories = true
use_memories = true
disable_on_external_context = false
min_rollout_idle_hours = 6
max_rollout_age_days = 90
max_rollouts_per_startup = 32
max_raw_memories_for_consolidation = 1024
max_unused_days = 180
min_rate_limit_remaining_percent = 15
extract_model = "gpt-5.6-luna"
consolidation_model = "gpt-5.6-luna"
```

The values are within the current documented limits. `200000` is a deliberate
operational default, not a universal model limit: it favors a longer
uncompacted working phase while retaining room for hooks, handoff generation,
and continuation before maximum context pressure. The
installer must validate the installed Codex version/configuration and report an
unsupported key rather than silently writing a configuration Codex cannot load.

Because `disable_on_external_context = false` lets tool-using sessions
contribute to native memories, documentation must highlight the privacy and
duplication trade-off and the `/memories` per-chat controls. Secrets remain
forbidden even though Codex performs memory redaction.

### 4.7 Global compact prompt

The canonical prompt lives at `assets/codex/compact_prompt.md`; installation
copies it atomically to `~/.codex/compact_prompt.md`. The prompt instructs Codex
to preserve:

- current objective and measurable completion criteria;
- explicit user instructions, permissions, and constraints still in force;
- decisions, rationale, and rejected alternatives that prevent repeated work;
- repository, branch/worktree, files, and uncommitted state;
- completed and remaining plan steps;
- commands and tests with actual results, never inferred success;
- active/background processes and external state, with identifiers where known;
- blockers, risks, unresolved questions, and the next exact action;
- authoritative artifact paths and relevant RAG slugs rather than copied bodies;
- checkpoint identity and any pending enrichment warning.

It also tells the continuing model to revalidate volatile state, preserve user
ownership of existing changes, avoid claiming unrun verification, and continue
the same task without asking the user to repeat known context.

The prompt has a format contract but no brittle requirement that Codex emit
machine-parseable JSON. agentic-rag checkpoints are produced independently; the
native compact summary is optimized for the next model request.

### 4.8 Installation and ownership

`rag install` remains additive and idempotent. Codex support may be selected by
an explicit target option during initial implementation, but an installed
integration must not hide behind a dead runtime enable flag.

Installation:

1. Backs up files before first mutation.
2. Parses and structurally merges `~/.codex/config.toml`; it must not reconstruct
   TOML in a way that discards comments or unknown keys without an explicit,
   tested preservation strategy.
3. Merges only agentic-rag-owned handlers into `~/.codex/hooks.json`, removing
   stale agentic-rag paths while preserving foreign handlers and metadata.
4. Installs the compact prompt atomically from the repository asset.
5. Reports every changed path and the exact rollback command/path.
6. Instructs the user to inspect and trust changed hooks with `/hooks`.
7. Supports a check/dry inspection mode for tests and diagnostics even though
   production installation is fully supported.

The installer also detects the currently duplicated/broken foreign
`herdr-agent-state.sh` SessionStart entries but does not delete or rewrite them;
it reports them as unrelated configuration requiring separate review.

## 5. Failure and recovery policy

- Hooks fail open and never prevent compaction, continuation, prompt submission,
  or shutdown.
- The synchronous snapshot has no LLM dependency and uses bounded filesystem,
  Git, and database work.
- Queue/database failures write sanitized local hook diagnostics and surface a
  concise warning at the next viable `SessionStart`.
- Enrichment failures use the existing typed provider failure classification.
- Auth/provider outages preserve jobs and retry later; no interactive login is
  attempted.
- Invalid semantic output spends the normal per-job content retry budget and
  leaves the deterministic snapshot usable.
- Restoration ignores malformed checkpoints and falls back to the next valid
  same-session or same-project checkpoint.
- Installed config/prompt writes use temporary files plus atomic replace and
  retain recoverable backups.
- Hook trust is an explicit Codex control; installation must not bypass it.

## 6. Testing strategy

Implementation is test-driven. Required automated coverage includes:

1. Checkpoint schema validation and round-trip persistence.
2. Repeated `PreCompact` delivery is idempotent for the same cursor.
3. A newer cursor supersedes rather than deletes the prior checkpoint.
4. Snapshot capture handles normal branch, linked worktree, detached HEAD,
   non-Git CWD, dirty tree, missing transcript, and capped status output.
5. `PreCompact` returns promptly and successfully during database, Git, transcript,
   provider, and queue failures.
6. Enrichment extracts only the specified fields, preserves observed test results,
   emits slugs, and rejects malformed output.
7. Provider outage leaves enrichment pending without consuming its content retry
   budget; later recovery enriches the same checkpoint.
8. `PostCompact` records the compaction boundary without model-context output;
   `SessionStart(source=compact)` selects and renders the matching checkpoint.
9. Fresh-session restore is same-project only and rejects cross-project state.
10. Rendering obeys a strict budget and uses references instead of large bodies.
11. `SessionEnd` and `Stop` deduplicate the final transcript delta and complete
    within their import-light contracts.
12. Config TOML merge preserves unknown keys/tables and is idempotent.
13. Hook JSON merge preserves foreign hooks, replaces stale owned commands, and
    installs all lifecycle events exactly once.
14. Compact-prompt installation is atomic, idempotent, and recoverable.
15. Config values pass the installed Codex configuration validator.
16. Existing Claude hooks, Codex/Claude mining providers, MCP privilege levels,
    and all current tests remain green.
17. A real manual and automatic compaction smoke test confirms immediate restored
    context without store or repository mutation beyond the checkpoint.

## 7. Documentation and discoverability

The implementation updates:

- README positioning from Claude-centric memory to provider-neutral memory and
  continuity;
- architecture, configuration, session-mining, privacy/cost, CLI/MCP reference,
  and contributing documentation;
- `CHANGELOG.md`;
- root `BACKLOG.md`, adding this work in blocker-first order and retaining every
  open item with why-not-done and resumption trigger;
- root `FEATURES.md`, which is currently absent, with shipped/planned status and
  discoverability for native memory, compact prompt, checkpoints, lifecycle
  hooks, and rollback;
- installer output and `rag status`, including checkpoint freshness and pending
  enrichment/provider health.

Documentation distinguishes Codex's generated local memory files from
agentic-rag's canonical database and warns against manually editing generated
Codex memory state.

## 8. Rollout and rollback

Rollout is staged by evidence, not by a dormant feature flag:

1. Land schema/core behavior and automated tests.
2. Land Codex config/hook/prompt installer and preservation tests.
3. Run the full agentic-rag suite.
4. Install globally with backups and validate Codex configuration.
5. Review/trust the new hooks via `/hooks` and start a fresh Codex session.
6. Exercise one manual compaction, inspect checkpoint and immediate injection.
7. Exercise automatic compaction with a lowered test-only threshold in an
   isolated session, then restore `200000`.
8. Simulate provider unavailability and verify snapshot continuity plus delayed
   enrichment/recovery.
9. Confirm `SessionEnd` captures the final delta and `rag status` is healthy.

Rollback restores the backed-up `config.toml`, `hooks.json`, and compact prompt,
then removes only agentic-rag-owned checkpoint handlers/assets. Database schema
rollback is additive: stop creating/restoring checkpoints and leave historical
records archived. Native Codex memories can be disabled independently with
`features.memories = false` or the Codex personalization setting.

## 9. Acceptance criteria

The feature is complete only when:

- global Codex configuration loads successfully with memories enabled and the
  intended compaction threshold/prompt;
- config, hooks, and prompt are reproducibly owned by versioned agentic-rag
  sources while preserving foreign user configuration;
- manual and automatic compaction both create a checkpoint and restore concise
  context before the next model request;
- the continuation contains goal, evidence-backed progress, blocker, next action,
  repository state, and authoritative references without large duplicated text;
- database, Ollama, provider, and auth failures do not block compaction or lose
  the deterministic checkpoint opportunity;
- session shutdown queues the remaining transcript delta without duplicate
  durable memories;
- native memories and agentic-rag can be independently inspected or disabled;
- full tests pass and operational smoke tests record their actual outcomes;
- README, handbook, `CHANGELOG.md`, `BACKLOG.md`, and `FEATURES.md` match the live
  behavior;
- rollback has been exercised against temporary configuration fixtures and is
  documented for the installed machine.

## 10. Key decisions

- Keep the work in `agentic-rag`; do not create a separate GitHub project.
- Make the continuity core provider-neutral and isolate Codex installation under
  an integration adapter.
- Treat agentic-rag as canonical and native Codex memories as complementary.
- Use a deterministic synchronous snapshot plus asynchronous semantic enrichment.
- Never make compaction wait for an LLM or authentication.
- Use `SessionStart(source="compact")` as the authoritative immediate restoration
  point; keep `PostCompact` idempotent and lightweight.
- Preserve `Stop` and add `SessionEnd` for the final delta.
- Reuse the existing Codex provider and auth circuit breaker.
- Store and inject references/slugs instead of large duplicated documents.
- Install active behavior directly after verification; do not ship dead enable
  flags.
