# Claude Code compaction continuity

**Date:** 2026-09-03
**Status:** Approved in chat; implementation pending
**Owner:** Project maintainer
**Scope:** Claude Code lifecycle hooks, a managed context/compaction policy in
`~/.claude/settings.json`, a versioned Claude compact prompt, reuse of the
provider-neutral continuation checkpoints, installation, documentation, and
operational rollout
**Companion:** `2026-09-03-codex-memory-continuity-design.md` (the Codex
adapter over the same core)

## 1. Problem

agentic-rag 0.3.0 preserves execution state across Codex compaction. Claude
Code sessions cross the same boundary with the same losses: after automatic
or manual compaction the model keeps only its own summary, and agentic-rag's
`SessionStart` restores pins and knowledge but no explicit continuation state.

The Claude installation (`rag install` without a target) wires only three
hooks (`SessionStart`, `UserPromptSubmit`, `Stop`). `PreCompact`,
`PostCompact`, and `SessionEnd` are implemented in `agentic_rag/hooks/` but are
neither installed for Claude nor adapted to Claude's payload and output
semantics. The continuation checkpoint core (`agentic_rag/continuity/`) is
provider-neutral by design and must be reused, not duplicated.

## 2. Verified Claude Code facts (2.1.259)

The design binds to the following behavior. Every fact was verified against
the installed Claude Code binary (`~/.local/share/claude/versions/2.1.259`)
and, where marked, the official documentation at `code.claude.com/docs`. The
implementation must keep a one-time payload probe in the smoke test because
hook schemas can drift between releases.

| Fact | Evidence |
|---|---|
| `PreCompact` payload: `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `trigger` (`manual`/`auto`), `custom_instructions` (nullable). | Binary zod schema; docs list the event and matchers. |
| `PreCompact` stdout on exit 0 is **appended as custom compact instructions**. Exit 2 blocks compaction. | Binary `/hooks` help text: "Exit code 0 - stdout appended as custom compact instructions". |
| `PostCompact` exists, matcher `manual`/`auto`, payload adds `compact_summary` (the produced summary). | Binary zod schema and `/hooks` help ("receives summary"); docs list the event. |
| `SessionStart` `source` values: `startup`, `resume`, `clear`, `compact` (docs also list `fork`). Output `hookSpecificOutput.additionalContext` is honored. | Existing working hook; docs. |
| `additionalContext` is capped at **10,000 characters per hook**. | Docs, hooks reference. |
| `SessionEnd` `reason` values: `clear`, `resume`, `logout`, `prompt_input_exit`, `other`. All `SessionEnd` hooks share a **1.5 second total budget**. | Binary enum; docs. |
| `autoCompactWindow` in `settings.json` is a **token count** (`/autocompact` prints "N tokens (from settings)", "capped to X by model"). `CLAUDE_CODE_AUTO_COMPACT_WINDOW` and `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` take precedence; `autoCompactEnabled=false`, `DISABLE_AUTO_COMPACT`, and `DISABLE_COMPACT` disable compaction. | Binary strings; docs for the setting and the pct override. |
| A `[1m]` model suffix (for example `claude-fable-5-1[1m]`) selects the 1M-token context window. | Binary; docs model-config. |
| There is no `additionalContextLimit` hook field in Claude. | Binary contains no such string. |
| Hook edits in `~/.claude/settings.json` are reloaded live; no restart is required. | Docs, settings. |
| Compaction writes a `system`/`compact_boundary` transcript entry with `compactMetadata` and a `user` entry flagged `isCompactSummary`. | Observed in real transcripts under `~/.claude/projects/`. |
| Hook and Bash children of Claude Code run with `CLAUDECODE=1` in the environment. | Observed in-session. |

## 3. Product boundary

Claude Code's auto-memory (`~/.claude/projects/<slug>/memory/`) is the
Claude analogue of native Codex memories: a complementary local recall layer
owned by the client. agentic-rag remains the canonical, auditable store for
knowledge, pins, and explicit continuation checkpoints. Checked-in files
(`CLAUDE.md`, `AGENTS.md`, specs, plans, `BACKLOG.md`, `FEATURES.md`) remain
authoritative for project rules and execution state. Nothing about auto-memory
is installed or changed by this feature.

## 4. Goals and non-goals

### Goals

- Preserve unfinished execution state across any number of manual or
  automatic Claude compactions and across session start/resume boundaries,
  using the same checkpoint contract and store as Codex.
- Supply Claude's compaction with the versioned agentic-rag compact prompt on
  every compaction, without per-session `/compact <instructions>`.
- Retain Claude's own compact summary as a bounded, secret-stripped handoff on
  the checkpoint so a fresh same-project session can restore semantic state
  without waiting for an LLM call.
- Trigger automatic compaction at 500,000 tokens inside the 1M window.
- Mine the final transcript delta when a Claude session ends for any reason.
- Keep every hook fail-open, bounded, idempotent, and safe under duplicate or
  out-of-order delivery; never exceed Claude's per-hook context limit silently.
- Keep `rag install` additive, previewable, backed up, and recoverable.

### Non-goals

- Do not replace Claude's compaction, transcript persistence, or auto-memory.
- Do not fork the checkpoint core per provider or add a second table, queue,
  scheduler, or authentication flow.
- Do not manage the `model` setting. The installer only reports whether the
  configured model carries a `[1m]` suffix.
- Do not inject restored context from `PostCompact`; `SessionStart` stays the
  single restoration point (parity with Codex, no duplicated context).
- Do not block compaction (exit 2) under any circumstance.
- Do not store transcript bodies, diffs, or file contents; the handoff is a
  bounded summary, never the transcript.

## 5. Selected architecture

### 5.1 Package boundaries

```text
agentic_rag/
  continuity/               unchanged contract; store/render gain "handoff"
  integrations/
    claude/
      settings.py           lossless settings.json merge: six hooks + policy
      install.py            check mode, unique backups, rollback record, report
    codex/                  unchanged
  hooks/
    common.py               client detection (claude | codex)
    pre_compact.py          + compact prompt on stdout for Claude
    post_compact.py         + turn-less matching and handoff capture for Claude
    session_end.py          + all Claude reasons enqueue
    session_start.py        + handoff section; total-output cap with warning
assets/
  claude/compact_prompt.md  versioned Claude compact instructions
sql/
  008_checkpoint_handoff.sql
```

The hook modules are shared by both clients; the client-specific behavior is
confined to three explicit branches. Codex behavior is unchanged and remains
covered by the existing tests.

### 5.2 Client detection

`common.client_kind(payload) -> "claude" | "codex"`:

1. `--client claude|codex` on the hook command line wins (tests, diagnostics).
2. `CLAUDECODE` present in the environment means Claude.
3. A non-empty `turn_id` in the payload means Codex.
4. Otherwise Claude (the project's historical default client).

The installer does not write `--client` into settings; detection is
environmental so already-trusted Codex hook commands do not change.

### 5.3 PreCompact for Claude

Order of operations, each step fail-open:

1. Validate `session_id`, `trigger`, `transcript_path` (unchanged).
2. Persist the seed snapshot, then the repository snapshot, then enqueue
   enrichment and spawn the worker (unchanged).
3. **Claude only:** write the compact prompt to stdout and exit 0. The prompt
   is the versioned `assets/claude/compact_prompt.md`, loaded via
   `importlib.resources`, followed by one line
   `agentic-rag checkpoint: <id>` when a checkpoint was persisted. The prompt
   is written even when the database, Git, or queue step failed, because the
   handoff instructions are static and still improve the compacted context.

Codex output stays silent (unchanged).

### 5.4 PostCompact for Claude

Claude payloads carry no `turn_id`. For Claude the hook:

1. Selects the most recent checkpoint for `session_id` with
   `source = 'PreCompact'` and the same `trigger`, ordered by
   `created_at DESC`, regardless of `compacted_at` (the newest compaction
   wins, compacted or not: when a later PreCompact failed to persist, the
   next PostCompact re-matches the previous checkpoint and replaces its
   handoff rather than losing the newer summary). If none exists, it does
   nothing.
2. Marks that checkpoint compacted (existing `mark_compacted`).
3. Attaches the handoff: `compact_summary` reduced to its `<summary>` block
   (Claude's raw compaction output carries an `<analysis>` scratch block
   first, which Claude Code itself discards; observed live 2026-09-04). The
   block boundaries are tags on lines of their own — the first `<summary>`
   starting a line after the first `</analysis>` ending one, closed by the
   last `</summary>` ending a line — because the prose may quote the same
   tags inline (observed live 2026-09-04 in a session about this mechanism,
   where a first-occurrence match stored analysis remainder plus a summary
   fragment). The body is whitespace-normalized, secret-stripped through
   `strip_secrets`, and bounded to `checkpoint_handoff_max_chars` (default
   8,000) by cutting out its middle: the head (objective, constraints) and
   the tail (pending work, current state, next step) survive around a
   `…[truncated]` marker line. It is stored through a `store.attach_handoff()` gateway
   that writes `audit_log` (`checkpoint_handoff`) in the same transaction.
   A replay with an identical summary is a no-op; a different summary for the
   same cursor replaces the handoff (the newest compaction wins).

No `additionalContext` is emitted. Failure emits only a `systemMessage`
(unchanged behavior).

### 5.5 SessionEnd for Claude

All five reasons (`clear`, `resume`, `logout`, `prompt_input_exit`, `other`)
enqueue the final transcript delta through the shared
`transcript_delta.enqueue_transcript_delta()`. Codex keeps the `other`-only
filter (unchanged).

Claude's 1.5 second total budget is a hard constraint. The implementation
measures the end-to-end hook wall time in the test suite with the real
interpreter (`python -m agentic_rag.hooks.session_end` against a local
database) and records the observation in the plan. The hook entry uses
`timeout: 1`. If the measured wall time exceeds one second in practice, the
`Stop` hook remains the safety net: it already enqueued a debounced delta
after the last assistant turn, so a missed `SessionEnd` loses at most the
tail after that turn. No spool-file fallback is built unless the measurement
demands it; the plan records the decision.

### 5.6 SessionStart for Claude

Unchanged selection semantics: same-session checkpoint first; only
`startup`/`resume` fall back to the same canonical project; `compact` never
falls back. Two additions:

- **Handoff section.** When the selected checkpoint carries a handoff, the
  renderer emits `Handoff (Claude compact summary, <age>, <applicability>)`
  followed by the bounded text, inside the existing
  `checkpoint_render_max_chars` budget. When the budget is exceeded the
  handoff is first shortened into the remaining budget (head and tail kept
  around the `…[truncated]` marker) so that a full-length handoff never evicts the
  reference lists or volatile state; it is dropped whole only when fewer
  than 200 characters would survive, immediately after the reference lists
  and always before the mandatory goal, next action, and blocker sections.
  Handoffs older than `stale_days` are labelled
  `historical`; handoffs from a different canonical project are never rendered
  (the checkpoint itself is not selected across projects).
- **Total output cap.** `build_context()` caps the emitted `additionalContext`
  at `context_max_chars` (default 9,500; hard-limited to 10,000). The
  checkpoint is *elastic*: before any whole section is dropped it is
  re-rendered into whatever budget remains (down to the renderer's 400-char
  minimum), which shortens the handoff around the `…[truncated]` marker while
  keeping pins, the domain map, recent knowledge, and the checkpoint's
  mandatory lines. Only when that is not enough are whole sections trimmed,
  in this order: recent project knowledge, domain map, checkpoint, pins —
  re-shrinking the checkpoint after each drop. A trimmed output starts with
  `⚠️ context truncated to fit the N-char Claude hook limit: <detail>; see
  rag status`, where the detail names the shortened section and every
  dropped one. Pins are trimmed last and the warning names how many pins were
  cut, because pins are law and their absence must be visible.
  *(Amended 2026-09-04 after the live smoke: a real 8,000-char handoff made
  the whole-section trimming evict knowledge, domains, and the checkpoint
  itself.)*
- **Ordering caveat (observed 2026-09-04).** Claude Code starts
  `SessionStart(source="compact")` and `PostCompact` concurrently after a
  compaction; in the live smoke SessionStart finished about 150 ms before
  PostCompact wrote the handoff. The injection that immediately follows a
  compaction therefore usually carries the checkpoint without the handoff.
  That is acceptable: at that moment Claude's own compact summary is still in
  the conversation. The stored handoff serves the next `startup`/`resume`
  injection, `rag status`, and any other consumer of the checkpoint.
  Codex is not affected: its compaction task awaits `PostCompact` before it
  ends, and the queued `SessionStart(source="compact")` runs at the next turn
  start or immediately after a mid-turn automatic compaction (verified in
  `codex-rs/core/src/compact.rs`, `session/mod.rs`, `session/turn.rs`,
  2026-09-04). Codex also stores no handoff, so nothing SessionStart renders
  depends on PostCompact.

### 5.7 Compact prompt asset

`assets/claude/compact_prompt.md` is derived from the Codex prompt (same
ordered content contract: objective and success criteria, active
instructions, decisions, repository state, plan progress, test results,
observed processes, blockers and next action, `[[slug]]` references) with
Claude-specific framing: it addresses Claude's compaction summarizer, states
that the following `SessionStart` hook will inject the agentic-rag checkpoint
and pins so the summary should reference rather than repeat them, and asks
for the `agentic-rag checkpoint: <id>` line to be preserved verbatim. Version
line `Version: 1.0`. Bounded to 4,000 characters so it never dominates the
compaction request.

### 5.8 Managed settings policy

`integrations/claude/settings.py` merges into `~/.claude/settings.json`:

- Six owned hook entries (matcher `startup|resume|clear|compact` for
  `SessionStart`, `manual|auto` for `PreCompact`/`PostCompact`, none for the
  rest) with timeouts `SessionStart 10`, `UserPromptSubmit 5`, `Stop 10`,
  `PreCompact 3`, `PostCompact 3`, `SessionEnd 1`. Owned entries are
  recognized by the `agentic_rag.hooks.` marker, replaced in place, and all
  foreign entries and keys are retained byte-for-byte in structure.
- `autoCompactWindow = 500000`.

The merge is a pure function over the parsed JSON and is idempotent. The
installer reports, without changing them:

- whether `model` carries a `[1m]` suffix (hint when it does not: the 500,000
  window is capped to the model's window);
- `autoCompactEnabled == false` (compaction disabled; continuity idle);
- `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`,
  `DISABLE_AUTO_COMPACT`, or `DISABLE_COMPACT` present in the settings `env`
  block or the installer's process environment (they override the managed
  window).

### 5.9 Installer transaction

`rag install` (no target) remains the Claude path and gains `--check`:

- `--check` parses the current settings, computes the merge, prints the
  managed values, the would-change path, and the warnings above, and writes
  nothing (no MCP registration, no launchd).
- Without `--check`: MCP registration and launchd as today; then settings are
  staged to a temporary file in the same directory, the current file is
  backed up to a unique `settings.json.<uuid>.bak` (mode 0600), and the
  staged file is published with `os.replace`. A rollback record with the
  backup identity (reusing `integrations/codex/install.FileIdentity` and the
  existing record format, extended with a `target` field) is written to
  `~/.agentic-rag/state/claude-rollback-<uuid>.json`, and the exact
  `rag install --restore <record>` command is printed.
- `--restore <record>` becomes target-aware: the record's `target` selects the
  Claude or Codex restore path. `--codex --restore` keeps working for Codex
  records; the record's `target` field selects the restore path. A Claude
  record combined with `--codex` is rejected with a clear error; a Codex record
  restores through either invocation.
- A corrupt `settings.json` still aborts loudly (unchanged).
- The installer prints `hooks: review changed handlers with /hooks` and
  `autocompact: verify with /autocompact`.

### 5.10 Data model

`sql/008_checkpoint_handoff.sql`:

```sql
ALTER TABLE continuation_checkpoints
  ADD COLUMN handoff text,
  ADD COLUMN handoff_at timestamptz;
```

Grants are unchanged (`rag_writer` may `UPDATE`; no delete path). `Checkpoint`
gains `handoff: str | None` and `handoff_at: datetime | None`. Configuration
gains `[continuity] handoff_max_chars` (field `checkpoint_handoff_max_chars`,
default 8000, minimum 400) and `[continuity] context_max_chars` (field
`context_max_chars`, default 9500, maximum 10000, minimum 1000).

`rag status` reports whether the newest open checkpoint carries a handoff and
its age alongside the existing checkpoint fields.

## 6. Failure and recovery policy

- Hooks fail open and never prevent compaction, prompt submission, or
  shutdown. `PreCompact` never exits 2.
- `PreCompact` prints the compact prompt even when persistence fails; the
  failure is logged to `hooks.log` and surfaces at the next `SessionStart` as
  the existing checkpoint warning.
- `PostCompact` with no matching checkpoint (for example hooks installed
  mid-session) is a silent no-op.
- Handoff attachment failure leaves the boundary marked and logs the error;
  the deterministic snapshot and later enrichment remain usable.
- `SessionEnd` overrunning its budget is tolerated by design; the `Stop`
  enqueue is the guaranteed path.
- Output above Claude's 10,000-character limit is trimmed by agentic-rag with
  a visible warning rather than silently by Claude.
- Installation uses staging plus atomic replace with unique backups; restore
  is identity-bound and refuses a backup that has changed since it was taken.

## 7. Testing strategy

Test-driven; required coverage:

1. `client_kind`: argv override, `CLAUDECODE` environment, `turn_id`
   fallback, default.
2. `PreCompact` (Claude) prints the versioned prompt plus checkpoint line on
   success, prints the prompt without the line on database failure, and
   prints nothing for Codex; replay stays idempotent.
3. `PostCompact` (Claude) matches the latest same-trigger checkpoint
   (compacted or not) without `turn_id`, marks it, attaches a bounded secret-stripped
   handoff with an audit row, is idempotent on replay, replaces on a changed
   summary, and no-ops without a checkpoint; Codex matching is unchanged.
4. Handoff validation rejects oversize input by truncation with marker and
   strips secrets; `handoff_max_chars` minimum is enforced.
5. `SessionEnd` (Claude) enqueues for all five reasons and deduplicates with
   `Stop`; Codex keeps `other`-only. A timing test runs the real module
   end-to-end and asserts wall time below one second on the local database,
   recording the measurement.
6. Renderer emits the handoff section with age/applicability labels, drops it
   before mandatory sections, and never exceeds the budget.
7. `build_context` total cap trims in the specified order, warns visibly,
   counts cut pins, and never exceeds 10,000 characters.
8. Settings merge: empty file, idempotent re-run, stale interpreter path
   replaced, foreign hooks and keys preserved, `autoCompactWindow` set,
   corrupt JSON aborts, model/env warnings produced.
9. `rag install --check` writes nothing and registers nothing;
   `rag install` backs up uniquely, writes the rollback record, prints the
   restore command; `--restore` restores a Claude record and rejects a Codex
   record on the Claude path and vice versa.
10. Migration 008 applies on the fixture database; existing checkpoint tests
    pass with the new columns.
11. `rag status` shows handoff presence and age.
12. All existing Codex, Claude mining, MCP, and continuity tests remain green.
13. Documentation consistency tests cover the new What's New and the
    500,000/1M policy wording.
14. Manual smoke test on the maintainer machine: `rag install --check`,
    `rag install`, `/hooks` trust review, `/autocompact` shows 500,000 tokens,
    one manual `/compact`, checkpoint row with `compacted_at` and `handoff`,
    restored context visible, `rag status` healthy. Outcomes recorded in
    `BACKLOG.md`.

## 8. Documentation and discoverability

- `docs/00-whats-new-in-0.4.md` (Claude continuity, managed 500K policy,
  handoff) and handbook index links; the 0.3 page stays.
- `docs/03-quick-start.md`, `05-session-mining-and-curation.md`,
  `06-configuration-reference.md` (managed Claude settings, `[continuity]`
  keys), `07-privacy-and-cost.md` (handoff retention; 1M-context usage cost
  above 200K input tokens must be measured, not assumed neutral),
  `10-architecture.md` (hook table, flow diagram for Claude, migration 008),
  `11-reference-cli-and-mcp.md` (`--check`, `--restore` target awareness),
  `README.md` positioning.
- `CHANGELOG.md` under Unreleased; version bump to 0.4.0 is a separate
  release decision.
- `FEATURES.md` gains a "Claude continuity" section; `BACKLOG.md` gains the
  rollout item under §0 with why-not-done and trigger.

## 9. Rollout and rollback

1. Land migration, store/render changes, hook branches, and tests.
2. Land the Claude settings merge, installer transaction, and tests.
3. Run the full suite.
4. `uv run rag init-db` (migration 008), `rag install --check`, then
   `rag install` on the maintainer machine.
5. Review and trust the changed handlers in `/hooks`; confirm `/autocompact`
   reports 500,000 tokens from settings.
6. Exercise one manual `/compact` in a real session; inspect the checkpoint,
   handoff, and restored context.
7. Observe one automatic compaction during normal long-session use and one
   `SessionEnd` tail capture; record outcomes in `BACKLOG.md`.

Rollback: `rag install --restore <record>` restores the backed-up
`settings.json`. Database rollback is additive: the new columns stay, hooks
stop writing them. Claude auto-memory is unaffected either way.

## 10. Acceptance criteria

- Claude sessions get the six lifecycle hooks and the 500,000-token
  compaction window from one idempotent, previewable, recoverable install.
- Every compaction receives the versioned compact instructions without user
  action; the checkpoint id survives into the summary.
- Manual and automatic compaction both create a checkpoint, mark the boundary,
  store a bounded handoff, and restore concise context before the next model
  request.
- Restored context never exceeds Claude's per-hook limit silently.
- Database, Ollama, provider, and auth failures never block compaction or lose
  the deterministic checkpoint.
- Session end queues the remaining transcript delta without duplicate mining.
- Codex behavior and tests are unchanged.
- Documentation, `CHANGELOG.md`, `FEATURES.md`, and `BACKLOG.md` match live
  behavior; the smoke test outcomes are recorded.

## 11. Key decisions

- Reuse the provider-neutral checkpoint core; add a thin Claude adapter and
  three explicit client branches in the shared hooks.
- Detect the client from the environment and payload, not from installed
  command lines, so trusted Codex hooks stay untouched.
- Use `PreCompact` stdout as the Claude compact prompt channel (the analogue
  of Codex's `experimental_compact_prompt_file`).
- Store Claude's compact summary as a bounded handoff; do not inject it from
  `PostCompact`.
- Manage only `autoCompactWindow = 500000`; report but never rewrite `model`.
- Enqueue the final delta on every Claude session end; accept the 1.5 second
  budget with `Stop` as the guaranteed path.
- Cap the total `SessionStart` output at Claude's limit with a visible warning.
- Extend the existing default `rag install` path rather than adding a
  `--claude` target; make `--restore` target-aware.
