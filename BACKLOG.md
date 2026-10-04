# agentic-rag — BACKLOG

> **Convention (standing rule for coding-relevant work on this project).**
> [GitHub Issues](https://github.com/phense/agentic-rag/issues) are canonical for open work.
> This file is the complete, numbered local index with stable IDs, Issue links, and historical
> rollout notes. Work **blocker-first**, then by Issue priority; do not renumber IDs. Maintain
> scope, priorities, dependencies, blockers, remaining acceptance criteria, **why-not-done**,
> and **resumption triggers** in the linked Issues; reflect status changes in this index.
> "Open" = anything not *built-tested-merged-and-running*. Revalidate historical versions,
> settings, and observations before acting. PR merges require the maintainer's explicit approval.
>
> **Status legend:** ✅ done · 🔵 in progress · ⬜ open · 🔒 blocked (external/precondition) · ⏸ paused
>
> _(`(kind)` after the marker = decision / design / build / bug / enh / chore. Effort S/M/L/XL.)_

---

## GitHub migration — 2026-10-03

All 13 open or in-progress entries below are tracked in Issues #12–#24. Existing
Issues #3–#9 are closed and remain linked to their completed work. Migration
preserves the original scope and rollout notes; it does not complete implementation
or prove a new live rollout. New Issues distinguish current source inspection from
historical observations and retain dependencies and resumption conditions.

Production compatibility and verified upgrade requirements apply to every change;
see [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), and
[contributing](docs/12-contributing.md#production-compatibility-and-pr-workflow).

## §0 — Continuity rollout blockers (Codex, Claude, and Antigravity)

- ⬜ **0.7** _(security)_ **Triage and remediate existing dependency alerts.** 16 open
  AnyIO/PyJWT alerts verified on 2026-10-03 (2 Critical, 6 High, 8 Medium). The deployed
  stdio/local-HTTP paths were triaged; the reported vulnerable paths are inactive in this
  installation. Patched isolated-environment verification and remediation remain open.
  The triage permits the three-feature rollout; it does not resolve or dismiss alerts.
  → *Issue:* [#37](https://github.com/phense/agentic-rag/issues/37).

- ✅ **0.6** _(enh)_ **OpenCode hooks and DeepSeek rollout.** Implemented, independently reviewed, locally merged and installed from the retained checkout. 800 Python and 7 Node tests pass; real DeepSeek startup/manual-compaction/handoff/restore passed against a synthetic test DB. Canonical startup context and read-only MCP healthy; a real T3 thread on the Mac verified context delivery and a completed DeepSeek Flash RAG search. All 17 Engineering Method skills preserved. Sustained auto-compaction and abrupt-termination limits remain documented in docs/opencode.md. *(M, completed 2026-09-11)*

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
  → *Issue:* [#12](https://github.com/phense/agentic-rag/issues/12).

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
  → *Issue:* [#13](https://github.com/phense/agentic-rag/issues/13).

- ⬜ **0.4** _(chore)_ **Prove Antigravity (agy) continuity end to end.**
  Code, tests, and docs landed on 2026-09-06 (branch `feat/agy-continuity`,
  0.5.0). Research the same day: `agy` 1.1.27 has `/compact` (verified
  headless), server-side automatic summarization without a threshold, hooks
  `PreToolUse`/`PostToolUse`/`PreInvocation`/`PostInvocation`/`Stop` plus an
  undocumented `SessionStart` (fires for new conversations only), camelCase
  payloads, and `injectSteps`/`ephemeralMessage` injection (verified: the
  model repeated two injected facts). Gemini 3.8 Flash and 3.1 Pro:
  1,048,576-token window.
  Rollout on the maintainer machine, 2026-09-06 11:28 local (0.5.0, after the
  release): `rag install --agy --check` then `rag install --agy` wrote the
  hook (rollback record printed); `agy` lists the `agentic-rag` hook with its
  three actions; a headless three-turn smoke in the agentic-rag workspace
  (`--add-dir`) produced a `PreCompact`/`manual` checkpoint at `agy-step-3`
  with `project_root` set, the summary followed the injected prompt structure
  (numbered objective/criteria), Stop stored a 1,475-char handoff and queued
  mining, enrichment completed (`quality=enriched`), the codeword survived
  compaction, and `hooks.log` recorded no error.
  → *Why not done:* no automatic compaction has been observed with the
  installed hooks. The automatic-compaction marker
  (`CHECKPOINT` step / `<CONTEXT_SUMMARY>`) is inferred from binary strings —
  when the detector fires it logs `agy.auto_compaction` in `hooks.log`; if a
  real compaction leaves a different trace, adjust
  `transcript_agy.latest_auto_compaction`. → *Trigger:* the next interactive
  `agy` session in a trusted workspace; record each outcome here.
  → *Dependency:* an `agy` conversation long enough to auto-compact. *(M)*
  → *Issue:* [#14](https://github.com/phense/agentic-rag/issues/14).

- ⬜ **0.5** _(enh)_ **Gemini as a mining/enrichment provider.** `agy -p
  --output-format json --json-schema` can return schema-constrained JSON, so
  `[llm] provider = "agy"` is feasible next to Codex and Claude.
  → *Why not done:* not requested; provider health/backoff semantics for the
  Antigravity quota are unknown. → *Trigger:* a wish to mine with the Gemini
  subscription instead of Codex/Claude. *(M)*
  → *Issue:* [#15](https://github.com/phense/agentic-rag/issues/15).

## §1 — Mining & curation pipeline

- ⬜ **1.1** _(enh)_ **Measure `prompt_recall` firing rate.** The prompt-recall detector's
  signature-matching heuristic was intentionally kept permissive (it also fires on prose that
  merely resembles an exception name or a `host:port` string; actual injection still requires
  a real full-text-search hit). It hasn't been measured against real usage yet. → *Trigger:*
  collect firing-rate stats from `hooks.log` over a representative usage window; tighten the
  signature only if the false-positive rate warrants it. *(S)*
  → *Issue:* [#16](https://github.com/phense/agentic-rag/issues/16).

- ⬜ **1.2** _(bug)_ **Age-gate the post-drain curation pass.** The curation pass currently
  runs on every hook spawn instead of respecting its intended 24h trigger, so the
  `audit_log` table grows one `curation_pass` row per turn instead of per day. → *Trigger:*
  add an age check before running the pass; verify audit-row growth rate drops accordingly.
  *(S)*
  → *Issue:* [#17](https://github.com/phense/agentic-rag/issues/17).

- ⬜ **1.3** _(enh)_ **`curation_pass` audit-row growth.** Depends on 1.2 landing — once the
  age gate is in place, confirm the row-growth rate is back to the intended cadence and add a
  regression test so a future regression is caught automatically. → *Trigger:* after 1.2 ships.
  *(S)*
  → *Issue:* [#18](https://github.com/phense/agentic-rag/issues/18).

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
  → *Issue:* [#19](https://github.com/phense/agentic-rag/issues/19).

- ✅ **2.2** _(chore)_ **Refute/reactivation evidence epoch.** Issue #6 adds an
  explicit reactivation timestamp; old contradiction edges cannot trigger another
  refutation, including across a concurrent model call. New evidence remains
  reviewable. Covered by sequential and two-writer regressions. *(S)*
- ⬜ **2.3** _(chore)_ **Test backlog.** Missing coverage: `memory_path`/`memory_timeline`
  happy-path tests; the SessionStart document-pin branch plus its result-count cap; the
  `duplicate_candidates`/`queue_errors` fields of the review report; worker-level embed-error
  retry behavior. → *Trigger:* pick up alongside the related feature work, or as a dedicated
  coverage pass. *(M)*
  → *Issue:* [#20](https://github.com/phense/agentic-rag/issues/20).

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
  → *Issue:* [#21](https://github.com/phense/agentic-rag/issues/21).

- ⬜ **3.2** _(enh)_ **`memory_save` confidence normalization.** The mining path normalizes
  off-vocabulary confidence values before they reach the database; the interactive
  `memory_save` path does not, so an out-of-vocabulary value currently surfaces as a raw
  database check-constraint violation instead of a clean error. → *Trigger:* reuse the mining
  path's normalization helper in `memory_save`. *(S)*
  → *Issue:* [#22](https://github.com/phense/agentic-rag/issues/22).

- ⬜ **3.3** _(enh)_ **`session_start` context-before-maintenance ordering.** Context is built
  and then maintenance is triggered; if the maintenance enqueue fails, the already-built
  context is discarded in favor of an "unavailable" banner. → *Trigger:* emit the built context
  first, and treat an enqueue failure as a secondary warning rather than a full replacement.
  *(S)*
  → *Issue:* [#23](https://github.com/phense/agentic-rag/issues/23).

- ⬜ **3.4** _(chore)_ **Install path re-resolution.** The generated launchd/cron/systemd unit
  pins an absolute interpreter path at install time; if the virtualenv moves, the installed
  unit silently points at a dead path. → *Trigger:* have the install command re-resolve and
  reinstall the unit rather than requiring a manual fix. *(S)*
  → *Issue:* [#24](https://github.com/phense/agentic-rag/issues/24).

- ⬜ **3.5** _(bug, P1)_ **Reject incomplete maintenance backup restores.** The legacy verifier can accept nonzero restore status/partial document counts. Feature4 uses a strict separate gate; harden the ordinary maintenance path independently. → *Issue:* [#41](https://github.com/phense/agentic-rag/issues/41). → *Trigger:* Add false-positive regressions and complete consistency/restore checks without production mutation.

## §4 — Supermemory-inspired improvement requests (2026-09-05)

Analysis: [`docs/research/supermemory-comparison-2026-09-05.md`](docs/research/supermemory-comparison-2026-09-05.md).
GitHub Issues hold the detailed proposals and acceptance criteria; this local numbered
backlog remains the project work index. P1 = correctness/evaluation foundation;
P2 = subsequent quality improvement. Open §0–§3 work is linked above. Source-loss
work in 1.4/1.5 is completed under Issue #4; historical backfill remains a separate
operation. Estimates are relative, not delivery commitments.

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
- ✅ **4.7** _(enh, P2)_ **Bounded project profiles and selective recall.** Build a source-backed advisory view over the existing store; preserve exact pins/checkpoints and measure ordinary-question recall.
  → *Issue:* [#9](https://github.com/phense/agentic-rag/issues/9). → *Verified:* 757 tests pass; independent review Ready; migration014 activated with a reused verified backup; installed reader/profile checks pass and documents/pins unchanged. Published2c46e02; CI34024173116 success (2026-09-06).
  → *Trigger:* after scope/evidence semantics; extend 1.1 firing-rate measurement. *(M–L)*

## §5 — Sequential quality and speed feature requests (2026-10-03)

Implement in stable ID order 5.1–5.10. Every feature needs full tests, independent review with no open Critical/High/Medium bug, 2–3 measured practical examples, and populated-installation compatibility or a rehearsed upgrade/recovery path. Trading is authorized for read-only measurement; writes and fault injection use isolated test installations. PR merges still require explicit approval.

- ✅ **5.1** _(enh)_ **Adaptive retrieval with exact, lexical and semantic search paths.** → *Issue:* [#26](https://github.com/phense/agentic-rag/issues/26); *PR:* [#36](https://github.com/phense/agentic-rag/pull/36). Merged with explicit approval and adopted locally on 2026-10-03 at`ae4a102`; 930 Python/7 Node tests, restored backup and all16 unchanged production tables verified. Fresh CLI/MCP clients pass; already-running MCP sessions retain old code until reconnect. See [rollout evidence](docs/verification/three-feature-production-adoption.md).
- ✅ **5.2** _(enh)_ **Permission-safe retrieval caches and reusable inference connections.** → *Issue:* [#27](https://github.com/phense/agentic-rag/issues/27); *PR:* [#38](https://github.com/phense/agentic-rag/pull/38). Merged with explicit approval and adopted locally on 2026-10-03 at`ae4a102`; 930 Python/7 Node tests, restored backup and all16 unchanged production tables verified. Fresh CLI/MCP clients pass; already-running MCP sessions retain old code until reconnect. See [rollout evidence](docs/verification/three-feature-production-adoption.md).
- ✅ **5.3** _(enh)_ **Selective local multilingual neural reranking.** → *Issue:* [#28](https://github.com/phense/agentic-rag/issues/28); *PR:* [#39](https://github.com/phense/agentic-rag/pull/39). Merged with explicit approval and adopted locally on 2026-10-03 at`ae4a102`; 930 Python/7 Node tests, restored backup and all16 unchanged production tables verified. Fresh CLI/MCP clients pass; already-running MCP sessions retain old code until reconnect. See [rollout evidence](docs/verification/three-feature-production-adoption.md).
- ✅ **5.4** _(enh)_ **Contextual chunk indexing with source-faithful evidence.** → *Issue:* [#29](https://github.com/phense/agentic-rag/issues/29) CLOSED; *PR:* [#42](https://github.com/phense/agentic-rag/pull/42) MERGED. → *Evidence:* Approved local adoption at99514fe/schema015 on2026-10-03;10432 documents/11822 chunks backfilled,0 retries/warnings; protected knowledge/history retained, strict015 backup restored,960 Python/7 Node. See [rollout record](docs/verification/contextual-indexing.md#production-adoption).
- ✅ **5.5** _(enh)_ **Filter-aware pgvector retrieval with bounded exact fallback.** → *Issue:* [#30](https://github.com/phense/agentic-rag/issues/30); *PR:* [#43](https://github.com/phense/agentic-rag/pull/43). Merged with approval and adopted locally at `19ed09c`, schema016.987 Python/7 Node checks, preserved production state, strict restore and fresh CLI/MCP clients verified; running sessions require reconnect. [Adoption record](https://github.com/phense/agentic-rag/issues/30#issuecomment-5973029391), [measurements](docs/benchmarks/2026-10-03-filter-aware-search/README.md).
- ✅ **5.6** _(enh)_ **Bounded evidence-checking multi-step research retrieval.** → *Issue:* [#31](https://github.com/phense/agentic-rag/issues/31); *PR:* [#44](https://github.com/phense/agentic-rag/pull/44). Merged with specific approval and adopted locally at `bd01d97`, schema016.1039 Python/7 Node checks, strict17-table restore, preserved production state and fresh8/14-tool MCP clients verified. [Adoption record](https://github.com/phense/agentic-rag/issues/31#issuecomment-5973683496), [measurements](docs/benchmarks/2026-10-03-bounded-research/README.md).
- ✅ **5.7** _(enh)_ **Incremental thematic memory summaries linked to original evidence.** → *Issue:* [#32](https://github.com/phense/agentic-rag/issues/32); *PR:* [#45](https://github.com/phense/agentic-rag/pull/45). Merged with specific approval and separately adopted at `2a29c50`, schema017.1076 Python/7 Node checks, strict restore, original state/grants and fresh9/15-tool clients verified. Issue32 is closed. [Canonical adoption record](https://github.com/phense/agentic-rag/issues/32#issuecomment-5974266962), [verification](docs/verification/thematic-summaries.md), [measurements](docs/benchmarks/2026-10-03-thematic-summaries/README.md).
- ✅ **5.8** _(enh)_ **Evidence-backed entity identities and scoped aliases.** → *Issue:* [#33](https://github.com/phense/agentic-rag/issues/33); *PR:* [#46](https://github.com/phense/agentic-rag/pull/46). Merged with specific approval and separately adopted locally at `1294d6c`, schema018.1137 Python/7 Node checks and fresh10/18-tool clients pass. All607 legacy assertions are indexed while their review disposition is preserved; no production aliases were inferred or confirmed. Original evidence/state/grants and strict restore pass. Issue33 is closed. [Canonical adoption record](https://github.com/phense/agentic-rag/issues/33#issuecomment-5975004882), [verification](docs/verification/entity-identities.md), [three paired controlled examples](docs/benchmarks/2026-10-04-entity-identities/README.md).
- 🔵 **5.9** _(enh)_ **Incremental embedding reuse and bounded ingestion preprocessing.** → *Issue:* [#34](https://github.com/phense/agentic-rag/issues/34); *PR:* [#47](https://github.com/phense/agentic-rag/pull/47). Exact input/model cache and bounded pure preprocessing are implemented on an isolated branch; full application tests pass. → *Why not done:* implementation tests and20 paired measurements/populated recovery pass; both independent complete reviews and publication pass; remote CI passes; specific merge approval and production adoption remain pending. → *Trigger:* Finish Feature9 gates, then Feature10; request both specific PR merge approvals together. No Feature9 production adoption is authorized.
- ⬜ **5.10** _(enh)_ **Evaluation-driven retrieval and mining optimization from confirmed failures.** → *Issue:* [#35](https://github.com/phense/agentic-rag/issues/35). → *Why not done:* implementation and measured acceptance remain open. → *Trigger:* Resume after the preceding feature has been implemented, tested, reviewed, and reported.

---

_Completed entries above retain historical rollout evidence and Issue links.
See `CHANGELOG.md` for release history; GitHub Issues track remaining open work._
