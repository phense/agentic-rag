# Codex-backed session mining with auth circuit breaking

**Date:** 2026-09-02
**Status:** Approved in chat; implementation pending
**Owner:** Project maintainer
**Scope:** `agentic-rag` mining and curation LLM seam, worker failure policy,
unattended health signalling, documentation, and migration of existing error jobs

## 1. Problem

Session mining currently calls `claude -p` through one hard-coded adapter. Two
independent failures accumulated 60 terminal queue errors:

1. Interactive workers found `~/.local/bin/claude`, but an expired Claude OAuth
   session made the CLI exit 1, often with empty stderr.
2. The daily launchd maintenance worker inherits
   `/usr/bin:/bin:/usr/sbin:/sbin`, so it could not find the same CLI at all.

The worker treated provider unavailability like a transcript-specific failure.
It therefore spent the three-attempt budget separately on every queued session,
marked each one `error`, continued trying more sessions against the same broken
provider, and exposed the incident only through `rag status` and SessionStart.
The queue did not technically deadlock, but durable session knowledge stopped
being produced until a human noticed and repaired authentication.

## 2. Goals and non-goals

### Goals

- Run mining and LLM-assisted curation with Codex using `gpt-5.6-luna` at
  `high` reasoning effort and the operator's existing ChatGPT login.
- Keep the single audited knowledge store and existing schema-constrained output
  contract.
- Distinguish provider-wide/authentication failures from bad individual jobs.
- Pause losslessly after one provider-wide failure instead of exhausting every
  job's retry budget.
- Resume automatically on a later worker run after authentication becomes valid.
- Make sustained provider/queue failure reach the operator without mail storms.
- Preserve Claude as an explicit rollback provider; do not keep it active in
  parallel.
- Requeue and drain the existing 60 failed mining jobs only after the new path is
  verified.

### Non-goals

- No OpenAI API key or direct Responses API integration.
- No automatic or scripted interactive login.
- No second queue, database, scheduler, or parallel mining pipeline.
- No changes to transcript digesting, secret stripping, deduplication, document
  routing, or the audited save gateway.
- No hard deletion of existing queue rows or documents.

## 3. Selected architecture

### 3.1 Provider-neutral structured-output seam

Replace the Claude-specific implementation behind `run_structured` with a small
provider interface while retaining `run_structured` as the sole application
chokepoint. Configuration gains an explicit provider and reasoning effort:

```toml
[llm]
provider = "codex"
bin = "/Users/example/.local/bin/codex"
model = "gpt-5.6-luna"
reasoning_effort = "high"
timeout = 300
```

The Codex adapter invokes a short-lived, non-interactive transform:

- `codex exec`
- `--model gpt-5.6-luna`
- `-c model_reasoning_effort="high"`
- `--ephemeral`
- `--sandbox read-only`
- `--skip-git-repo-check`
- `--ignore-user-config`
- `--ignore-rules`
- `--output-schema <temporary-schema-file>`
- `--output-last-message <temporary-output-file>`

The system instruction and task prompt are combined into one explicit mining
prompt because `codex exec` has no Claude-style `--system-prompt` argument. The
adapter reads only the last-message file as the structured result, parses it as
JSON, verifies that it is an object, and always removes temporary files.

The subprocess working directory is an empty temporary directory, not a source
repository. It ignores user configuration and project rules/plugins/hooks while
retaining Codex authentication from `CODEX_HOME`; it also receives the existing
hook-disabling environment marker and Codex-specific recursion guards as needed.
Read-only sandboxing and an instruction that this is a pure JSON transform
prevent the miner from modifying a repository or invoking the knowledge gateway
itself. The application remains the only writer after it validates the returned
candidates.

The existing Claude adapter remains supported behind `provider = "claude"` for
rollback. Its existing command contract and tests remain intact. There is never
automatic cross-provider fallback: silently switching providers would obscure
outages and make behavior/cost unpredictable.

### 3.2 Authentication and provider-health classification

Provider exceptions become typed:

- `LLMJobError`: output/schema/content failure attributable to one invocation;
  uses the ordinary bounded per-job retry policy.
- `LLMUnavailableError`: missing binary, invalid/expired login, transport/service
  unavailability, account/usage availability, or provider-wide timeout evidence;
  opens the circuit breaker.

Before draining LLM jobs, the Codex adapter performs a cheap local preflight with
`codex login status`. This catches missing login without sending a transcript.
Because a locally present credential can still fail during refresh, the first
real Codex invocation remains authoritative and may also open the circuit.

Error classification uses exit status plus normalized stderr/stdout patterns and
must retain a redacted diagnostic. Empty exit-1 output is classified as provider
unavailable, not job-invalid, because there is no evidence that the transcript
caused it. Invalid JSON after a successful invocation remains a job error.

No code attempts `codex login`, device authentication, browser automation, or
credential refresh directly. Codex owns token refresh. When user interaction is
truly required, the system tells the operator to run `codex login`.

### 3.3 Circuit-breaker queue semantics

The worker continues to claim jobs one at a time, but provider unavailability has
different completion behavior:

1. Restore the claimed job to `pending`.
2. Undo the attempt increment for that claim, so an auth outage cannot consume the
   job's three content-processing attempts.
3. Set `next_attempt_at` to a bounded provider retry interval (initially one hour;
   configurable).
4. Stop the entire drain immediately. Do not claim another LLM-backed job against
   the same unavailable provider.
5. Leave non-LLM maintenance isolated; backup and deterministic housekeeping may
   still run.

Circuit state is represented by a small atomic JSON health artifact under
`~/.agentic-rag/state/`, not a new database or sticky enable flag. It records
provider, first/last failure time, sanitized reason, notification time, and last
success. A successful preflight plus successful invocation closes the circuit and
updates the artifact. The artifact never authorizes or vetoes work independently
of current provider evidence; it exists for backoff, observability, and alert
deduplication.

The worker retains its existing single-process lock, 50-job drain cap, subprocess
timeout, and three-attempt ordinary job cap. The Codex subprocess remains bounded
by the LLM timeout. No child session is persisted because `--ephemeral` is used.

### 3.4 Loud failure without alert storms

Provider unavailability is a fail-open condition for interactive sessions but
must not be fail-silent:

- The first provider outage writes the health artifact and worker log immediately.
- The existing SessionStart status continues to display queue errors and gains a
  provider-unavailable summary with the exact remediation command.
- Trading's existing ops-health sentinel gains a read-only check of the artifact
  and queue age/count. It emits an ISSUE only when the provider has remained
  unavailable beyond a grace period or pending/error mining exceeds policy.
- Notification state in the artifact deduplicates repeated fires. Recovery is
  also visible once, then the condition clears.

This reuses the existing ops-health email path rather than creating an
agentic-rag-specific mail transport. Benign tests cover: empty queue, logged-in
provider with no work, weekend/quiet day, one transient failure inside the grace
period, and recovery. The sentinel must not report old legacy errors after they
have been deliberately requeued.

### 3.5 Output contract and data safety

Codex receives the same JSON Schema already used by mining and curation. The
adapter additionally checks:

- subprocess success;
- last-message output exists and is non-empty;
- JSON parses to an object;
- existing downstream mining validation accepts only known domains, document
  kinds, and edge predicates.

Transcript digesting remains local, delta-only, capped, and secret-stripped
before the LLM call. Tool inputs and tool results remain excluded. All accepted
items still pass through `save_document`; Codex never writes directly to
PostgreSQL or agentic-rag MCP tools.

## 4. Migration and retirement sweep

This change supersedes the active Claude-backed mining provider but does not
remove the Claude adapter.

- **Scheduler:** keep the single `com.agentic-rag.maintenance` launchd job; update
  its generated/runtime environment only as needed for the absolute Codex path.
  Do not add a Codex schedule.
- **Watchdogs/alerts:** update SessionStart and the Trading ops-health sentinel to
  understand provider health and queue age; no Claude-auth watcher survives.
- **Writers/consumers:** all mining and curation calls route through the selected
  provider adapter; grep must find no bypassing `claude -p` production call.
- **Tests:** run the full `agentic-rag` suite and the affected Trading pipeline/
  ops-health tests. A full Trading root suite is required because the retirement
  changes a monitored automated component.
- **Docs/registry:** update README, configuration, mining/curation documentation,
  architecture, FEATURES, CHANGELOG as appropriate, Trading `CLAUDE.md`'s OAuth
  exception for this shared engine, and the `active-crons` knowledge document.
- **Knowledge:** save a durable migration memory through `rag save` with the
  rollback pointer.
- **Rollback:** set `[llm] provider = "claude"`, restore the prior model/bin, and
  revert to the pre-migration commit if necessary. No data migration is required.

The 60 existing terminal `mine` jobs are not modified during code deployment.
After unit/integration verification and one harmless real Codex structured-output
probe, explicitly requeue only the known provider-failure jobs, preserving their
session ids, transcript paths, cursors, and audit history. Drain them under the
normal 50-job cap, inspect output counts/contracts, then drain the remainder.

## 5. Testing strategy

Implementation is test-driven. Required coverage:

1. Codex argv contains Luna, high effort, ephemeral mode, read-only sandbox,
   ignored user/rule configuration, schema file, output file, and absolute
   configured binary; cwd is an empty temporary directory.
2. Prompt composition preserves system and user content without shell quoting.
3. Valid JSON object output passes; missing/empty/non-JSON/non-object output fails.
4. Temporary files are removed after success, non-zero exit, and timeout.
5. `codex login status` success/failure classification.
6. Auth/provider failure restores the job to pending, preserves its attempt budget,
   applies bounded backoff, and stops the drain after one claim.
7. Ordinary job failure retains the existing exponential retry and terminal-error
   behavior.
8. A later successful run closes the circuit and drains the preserved job.
9. Health artifact writes are atomic, sanitized, and notification-deduplicated.
10. Ops-health benign-state tests and sustained-outage/recovery tests do not send
    real mail.
11. Claude-provider rollback adapter regression tests continue to pass.
12. Real smoke probe returns schema-valid JSON without repository/store mutation.

## 6. Operational acceptance criteria

The migration is complete only when:

- Codex reports a valid ChatGPT login and the real Luna/high smoke probe passes.
- The installed 04:00 launchd path can resolve and execute the configured absolute
  Codex binary under launchd's minimal environment.
- A simulated expired login leaves a mine job pending with its attempt budget
  intact, stops further LLM claims, and produces the sentinel-visible artifact.
- Recovery drains that same job automatically without manual queue surgery.
- All 60 legacy provider-failure jobs have either completed or have a distinct,
  evidence-backed non-provider error requiring review.
- The queue has no unexplained `processing` rows and no provider-failure `error`
  rows.
- Documentation, FEATURES/BACKLOG, active-crons knowledge, Learnings, and rollback
  pointers match the deployed state.

## 7. Key decisions

- Use the ChatGPT-authenticated Codex CLI, not a metered OpenAI API key.
- Use `gpt-5.6-luna` with `high` reasoning, as explicitly selected for the reference deployment.
- Preserve provider choice in configuration, but never silently fall back.
- Treat missing/expired provider authentication as infrastructure unavailability,
  not as 60 independent bad transcripts.
- Automate recovery after re-authentication; do not automate authentication itself.
- Reuse the existing ops-health mail channel and existing worker/scheduler rather
  than creating parallel automation.
