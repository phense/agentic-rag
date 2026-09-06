# agentic-rag — BACKLOG

> **Convention (standing rule for coding-relevant work on this project).**
> A single, complete, numbered backlog at the repo root. Work it **top-down**. Keep it
> current: add findings at the right number, re-rank as priorities shift, update the status
> marker. "Open" = anything not *built-tested-merged-and-running*. Every open item carries a
> **why-not-done** and a **resumption trigger** (plus dependencies, where they exist).
>
> **Status legend:** ✅ done · 🔵 in progress · ⬜ open · 🔒 blocked (external/precondition) · ⏸ paused
>
> _(`(kind)` after the marker = decision / design / build / bug / enh / chore. Effort S/M/L/XL.)_

---

## §0 — Continuity rollout blockers (Codex and Claude)

- ✅ **0.0** _(security)_ **Secret-strip provider-bound pin bodies.** Mining
  now strips secret-shaped values from copied global, matching-path, and
  document-reference pin bodies at the provider boundary without mutating
  stored pin text. Regression coverage proves both properties. *(S, completed 2026-09-03)*
- ✅ **0.1** _(chore)_ **Task 9 pre-install whole-diff and security review.**
  The complete specification diff, focused security/preservation checks, full
  suite, isolated wheel install, immutable temporary-home check mode, and final
  code review passed. Verified findings have focused regressions and minimal
  fixes. *(M, completed 2026-09-03)*
- 🔵 **0.2** _(chore)_ **Prove Codex continuity end to end.** A reference
  macOS deployment completed on 2026-09-03: migrations 006/007 were applied;
  the 600000/500000 policy, native memories, compact prompt, and all six merged
  handlers were installed; the post-install check is idempotent; the handler
  hashes were reviewed and trusted; and a fresh Codex session recovered with
  its MCP connections available. `rag status` and host-side `codex doctor`
  report healthy storage, provider connectivity, and configuration. Backups
  and the printed mode-0600 rollback record were retained.
  Ordering check, 2026-09-04 (Codex sources, 0.153.0 line): the compaction
  task awaits `PreCompact`, compacts, persists the `Compacted` rollout item
  and queues `SessionStart(source="compact")`, then awaits `PostCompact`
  before the task ends; the queued SessionStart runs at the next turn start
  or right after a mid-turn automatic compaction. The Claude
  PostCompact/SessionStart race recorded under 0.3 therefore cannot occur on
  Codex, and Codex stores no handoff anyway. Also observed: Codex discovers
  handlers once per session and does not reload `hooks.json`; the four
  compactions after the 2026-09-03 16:30 install all happened in a session
  opened at 08:49, which is why the store still holds no Codex checkpoint.
  Sessions opened after the install do run `SessionStart` (context injected)
  but have not compacted yet.
  Price-aware policy update, 2026-09-04: after the official GPT-5.6 pricing
  boundary was rechecked, the managed and installed Codex policy moved to a
  350000 context window with total-scope compaction at 250000. The installer
  changed only those two config lines; the prior config backup and mode-0600
  rollback record were retained, while hooks and the compact prompt stayed
  byte-identical.
  → *Why not done:* manual/automatic compaction, provider outage/recovery, and
  SessionEnd tail capture have not yet been exercised end to end in sustained
  real sessions. → *Trigger:* run and record those remaining smoke scenarios
  during normal long-session use — in a Codex session started after the
  install. → *Dependency:* interactive Codex sessions long enough to exercise
  lifecycle boundaries. *(L)*
- 🔵 **0.3** _(chore)_ **Prove Claude continuity end to end.** Code, tests, and
  docs landed on 2026-09-03 (branch `feat/claude-compaction-continuity`).
  Measured `SessionEnd` wall time in the suite: 0.121 s (interpreter start +
  import + enqueue against a local database; Claude budget 1.5 s, hook
  timeout 1 s).
  Rollout on the maintainer machine, 2026-09-04: migration 008 applied;
  `rag install --check` reported one change and no policy warning (model
  already `[1m]`); `rag install` wrote the six hooks and
  `autoCompactWindow=500000` (diff against the unique backup shows nothing
  else changed), printed the mode-0600 rollback record, and `rag status`
  stayed healthy.
  Manual `/compact` smoke, 2026-09-04 09:02 local: PreCompact printed the
  versioned instructions plus `agentic-rag checkpoint: 2eae3810-…`;
  PostCompact marked the checkpoint compacted and stored a 7,999-char
  handoff; `rag status` showed `checkpoint handoff: … (26s ago)`; no
  `hooks.log` was written (no hook error). Two defects found and fixed the
  same day: (1) the stored handoff was Claude's raw output, so the
  `<analysis>` scratch block consumed the 8,000-char bound and the actual
  `<summary>` was truncated — `bound_handoff` now keeps only the summary
  block; (2) with a full-length handoff the 9,500-char total cap dropped
  knowledge, domains, and the whole checkpoint on the next startup —
  `fit_context` now shrinks the checkpoint into the remaining budget before
  any section is dropped (609 tests). Observed ordering: Claude Code started
  `SessionStart(compact)` and `PostCompact` concurrently and SessionStart
  finished ~150 ms earlier, so the immediate post-compaction injection
  carried the checkpoint without the handoff; documented as expected (the
  handoff serves the next startup/resume).
  Second manual `/compact` smoke, 2026-09-04 11:51 local (after the 0.4.0
  release): checkpoint `943f9550-…` compacted at 11:52:53, handoff stored
  9 ms later, SessionStart injected 9,180 chars (pins, domains, checkpoint;
  no drop or shorten warning) 121 ms *before* the handoff landed — same
  ordering as before. Two more defects found and fixed the same day: (3) the
  summary extraction matched the first `<summary>`/`</summary>` occurrence,
  and this session's own summary quoted those tags inline, so the stored
  handoff was 6,912 chars of analysis remainder plus a summary fragment
  (Claude Code's own transcript rendering shows the same first-occurrence
  slip) — boundaries are now tags on lines of their own, and the live row was
  re-attached from the transcript's real summary; (4) the 12,599-char summary
  head-truncated at 8,000 lost its pending-work, current-work, and next-step
  sections — bounding now cuts out the middle (612 tests). Also observed:
  enrichment job 4128 failed its first attempt on validation (`processes`
  item lacked digest evidence) and was left pending for the scheduled retry,
  as job 4121 had been before succeeding on its third attempt.
  → *Why not done:* `/hooks` trust review, `/autocompact` = 500000
  confirmation, an automatic compaction, and a `SessionEnd` tail capture are
  still to be exercised in a live session. → *Trigger:* the next interactive
  Claude Code session; record each outcome here. *(M)*

## §1 — Mining & curation pipeline

- ⬜ **1.1** _(enh)_ **Measure `prompt_recall` firing rate.** The prompt-recall detector's
  signature-matching heuristic was intentionally kept permissive (it also fires on prose that
  merely resembles an exception name or a `host:port` string; actual injection still requires
  a real full-text-search hit). It hasn't been measured against real usage yet. → *Trigger:*
  collect firing-rate stats from `hooks.log` over a representative usage window; tighten the
  signature only if the false-positive rate warrants it. *(S)*
- ⬜ **1.2** _(bug)_ **Age-gate the post-drain curation pass.** The curation pass currently
  runs on every hook spawn instead of respecting its intended 24h trigger, so the
  `audit_log` table grows one `curation_pass` row per turn instead of per day. → *Trigger:*
  add an age check before running the pass; verify audit-row growth rate drops accordingly.
  *(S)*
- ⬜ **1.3** _(enh)_ **`curation_pass` audit-row growth.** Depends on 1.2 landing — once the
  age gate is in place, confirm the row-growth rate is back to the intended cadence and add a
  regression test so a future regression is caught automatically. → *Trigger:* after 1.2 ships.
  *(S)*
- ✅ **1.4 / 1.5** **Lossless mining windows and crash-idempotent application.**
  Implemented by [issue #4](https://github.com/phense/agentic-rag/issues/4), commit
  `6958c4b`: accepted extraction batches, atomic effects, source-bound cursors and
  process-death regressions. Integrated locally; migration 009 applied after backup.
  Published on main; issue closed. See [recovery](docs/implementation/issue-4-recovery.md).

## §2 — Housekeeping & test coverage

- ⬜ **2.1** _(chore)_ **Log/audit housekeeping — remaining gap.** `hooks.log`/`worker.log`
  rotation is done (`rag maintenance` size-based rotation, one prior generation kept);
  `curation_pass` audit-row growth (see 1.2/1.3) is the remaining piece. → *Trigger:* close
  once 1.2/1.3 land. *(S)*
- ✅ **2.2** _(chore)_ **Refute/reactivation evidence epoch.** Issue #6 adds an
  explicit reactivation timestamp; old contradiction edges cannot trigger another
  refutation, including across a concurrent model call. New evidence remains
  reviewable. Covered by sequential and two-writer regressions. *(S)*
- ⬜ **2.3** _(chore)_ **Test backlog.** Missing coverage: `memory_path`/`memory_timeline`
  happy-path tests; the SessionStart document-pin branch plus its result-count cap; the
  `duplicate_candidates`/`queue_errors` fields of the review report; worker-level embed-error
  retry behavior. → *Trigger:* pick up alongside the related feature work, or as a dedicated
  coverage pass. *(M)*

## §3 — Operational hardening

- ✅ **3.0** _(bug)_ **Circuit-break provider-wide mining outages.** Added
  Codex/Claude provider adapters, typed outage classification, lossless queue
  restoration without attempt consumption, bounded backoff, atomic health
  state, SessionStart/status visibility, and external ops-health coverage.
  Claude remains the configuration-only rollback. *(M, completed 2026-09-02)*

- ⬜ **3.1** _(enh)_ **`rag review duplicate_candidates` in the wild.** Dedup/retry behavior
  for duplicate candidates has only been exercised in controlled runs, not under sustained
  real-world load. → *Trigger:* observe behavior over a longer live window; adjust
  thresholds/retry policy if duplicates or retries misbehave. *(S)*
- ⬜ **3.2** _(enh)_ **`memory_save` confidence normalization.** The mining path normalizes
  off-vocabulary confidence values before they reach the database; the interactive
  `memory_save` path does not, so an out-of-vocabulary value currently surfaces as a raw
  database check-constraint violation instead of a clean error. → *Trigger:* reuse the mining
  path's normalization helper in `memory_save`. *(S)*
- ⬜ **3.3** _(enh)_ **`session_start` context-before-maintenance ordering.** Context is built
  and then maintenance is triggered; if the maintenance enqueue fails, the already-built
  context is discarded in favor of an "unavailable" banner. → *Trigger:* emit the built context
  first, and treat an enqueue failure as a secondary warning rather than a full replacement.
  *(S)*
- ⬜ **3.4** _(chore)_ **Install path re-resolution.** The generated launchd/cron/systemd unit
  pins an absolute interpreter path at install time; if the virtualenv moves, the installed
  unit silently points at a dead path. → *Trigger:* have the install command re-resolve and
  reinstall the unit rather than requiring a manual fix. *(S)*

## §4 — Supermemory-inspired improvement requests (2026-09-05)

Analysis: [`docs/research/supermemory-comparison-2026-09-05.md`](docs/research/supermemory-comparison-2026-09-05.md).
GitHub Issues hold the detailed proposals and acceptance criteria; this local numbered
backlog remains the project work index. P1 = correctness/evaluation foundation;
P2 = subsequent quality improvement. Existing §0–§3 work remains open. Source-loss work in 1.4/1.5 is locally active; scope and minimal source evidence precede
automated fact replacement. Estimates are relative, not delivery commitments.

- ✅ **4.1** _(enh, P1)_ **Reproducible end-to-end memory evaluation.** Establish an EN/DE held-out corpus and report retrieval/answer quality, stale facts, context cost and latency.
  → *Issue:* [#3](https://github.com/phense/agentic-rag/issues/3). → *Completed:* 60-query retrieval baseline, real eight-query extraction/answer/judge smoke, all eight results inspected, 665-test suite and GitHub offline CI verified. See [model inspection](docs/benchmarks/2026-09-05-memory-model-smoke/inspection.md). *(M)*
- ✅ **4.2** _(enh, P1)_ **Lossless, idempotent source-window ingestion.** Consolidates existing 1.4/1.5: advance only consumed input and replay persisted batches without duplicate logical facts.
  → *Issue:* [#4](https://github.com/phense/agentic-rag/issues/4). → *Completed:* implementation, independent review, deployment after backup and publication verified; issue closed. Historical backfill is separate. *(M–L)*
- ✅ **4.3** _(enh, P1)_ **Consistent project scope for retrieval and curation.** Separate project/global applicability from topic domains; align search, recall pins, graph expansion and duplicate candidates.
  → *Issue:* [#5](https://github.com/phense/agentic-rag/issues/5). → *Completed:* explicit scope across retrieval/recall/curation, 685 tests, independent review and zero-violation scope benchmarks. Migration 010/backfill deployed after fresh verified backup; content/pin invariants and idempotence confirmed. Unknown legacy scope remains reviewable. See [policy](docs/project-scope.md). *(M)*
- ✅ **4.4** _(enh, P1)_ **Temporal fact validity and supersession.** Reuse the graph for current/as-of retrieval, explicit expiry and grounded updates while retaining history; resolve 2.2 semantics.
  → *Issue:* [#6](https://github.com/phense/agentic-rag/issues/6). → *Completed:* implementation, independent review, 703 tests and eight-question
  model comparison verified; migration 011 activated after fresh checked backup,
  legacy/pin invariants preserved, published CI green and issue closed.
  See [verification](specs/RAG-006-fact-validity/verification.md). *(L)*
- ✅ **4.5** _(enh, P2)_ **Claim-level evidence and inference status.** Retain sanitized event references and speaker roles; distinguish stated facts, assistant suggestions and derived inferences.
  → *Issue:* [#7](https://github.com/phense/agentic-rag/issues/7). → *Completed:* 718 tests, independent review and synthetic semantic evaluation
  verified; migration012 activated after explicit approval and fresh checked backup;
  legacy/pin invariants unchanged, published CI green and issue closed. *(M–L)*
- ✅ **4.6** _(enh, P2)_ **Measured retrieval relevance improvements.** Add diverse results and useful evidence spans; evaluate local reranking, abstention and bounded graph expansion.
  → *Issue:* [#8](https://github.com/phense/agentic-rag/issues/8). → *Completed:* 732 regression tests, independent review,
  eleven synthetic comparisons and wheel checks passed; migration013 activated with unchanged document/pin fingerprints.
  Installed reader search and citations verified; published CI green, issue closed.
  See [policy](docs/retrieval-quality.md) and [measurements](docs/benchmarks/2026-09-06-retrieval-quality/README.md). *(M)*
- ⬜ **4.7** _(enh, P2)_ **Bounded project profiles and selective recall.** Build a source-backed advisory view over the existing store; preserve exact pins/checkpoints and measure ordinary-question recall.
  → *Issue:* [#9](https://github.com/phense/agentic-rag/issues/9). → *Why not done:* analysis complete; implementation and rollout pending.
  → *Trigger:* after scope/evidence semantics; extend 1.1 firing-rate measurement. *(M–L)*

---

_Closed items (fixed bugs, shipped features, resolved design questions) are not tracked here —
see `CHANGELOG.md` for what has already shipped._
