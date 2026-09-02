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
- ⬜ **1.4** _(enh)_ **Cap-aware `last_uuid` for over-cap deltas.** When a mined transcript
  delta exceeds the per-run size cap, the text is truncated to `max_chars` but `last_uuid`
  still advances to end-of-file — so the untruncated remainder of that delta is silently
  skipped rather than picked up on the next run. → *Trigger:* rework the cursor so an
  over-cap delta is only consumed as far as it was actually mined, and the remainder is
  retried on the next pass. *(M)*
- ⬜ **1.5** _(chore)_ **Job-completion idempotency under worker death.** `save_document`
  commits per-document, but `last_uuid` only advances at job completion — if a worker dies
  mid-job, a requeue re-mines the same delta (bounded by retry count, dedup depends on the
  embedding backend being deterministic enough to catch it). → *Trigger:* either wrap the job
  in one transaction, or persist progress in the job payload so a requeue resumes rather than
  restarts. *(M)*

## §2 — Housekeeping & test coverage

- ⬜ **2.1** _(chore)_ **Log/audit housekeeping — remaining gap.** `hooks.log`/`worker.log`
  rotation is done (`rag maintenance` size-based rotation, one prior generation kept);
  `curation_pass` audit-row growth (see 1.2/1.3) is the remaining piece. → *Trigger:* close
  once 1.2/1.3 land. *(S)*
- ⬜ **2.2** _(chore)_ **Refute-trigger checks existence, not recency.** The refute trigger
  checks whether an edge/audit row exists rather than whether it's current — only matters once
  a previously-refuted document is reactivated by later curation work. → *Trigger:* document
  the intended semantics, then decide whether a recency check is worth adding. *(S)*
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

---

_Closed items (fixed bugs, shipped features, resolved design questions) are not tracked here —
see `CHANGELOG.md` for what has already shipped._
