# PB-065-OPS: Upgrade to 0.6.18 and operate pattern synthesis

## Identity and scope

- Class: system.
- Origin: RAG-065 FR-005 and task T065-007 in
  [the specification](../../specs/6-7-pattern-synthesis/spec.md).
- Audience and owner: the operator of a local or central agentic-rag database.
  The maintainer owns production authorization; drafting this playbook
  authorizes no live operation.
- Target: package 0.6.18, migration `030_pattern_synthesis.sql`, from a populated
  0.6.17 installation at schema029 (`main` at `81beaf6`). Earlier sources first
  follow their own upgrade playbooks ([PB-063](rag-063-source-evidence-upgrade.md)).
- Readiness deadline: independent review and isolated rehearsal before the RAG-065
  pull request is handed off.
- Last edited: 2026-10-31.
- Review and rehearsal evidence: [rag-065-pattern-synthesis-review.md](rag-065-pattern-synthesis-review.md).

## When to use / when not to use

Use this procedure to:

- upgrade a 0.6.17 store to schema030 (part A);
- switch pattern synthesis on for one domain and project, watch it and read the
  first patterns (part B);
- request a history backfill, handle a provider outage or a failed run, pause,
  disable and check integrity (part C);
- roll code back or restore a backup (part D).

The upgrade adds tables, functions and redefined eligibility checks. It rewrites
no original row, grant or audit record and creates no policy, so nothing is
generated until part B. Behavior and terms: [pattern synthesis](../../pattern-synthesis.md).

Do not use it when:

- the store reports an unknown version or schema, or several stores need merging;
- writers cannot be stopped for part A, or there is no approved maintenance window;
- the memories of the scope must not reach the configured model provider. Part B
  sends quotes of up to 12 memories per run to that provider.

## Before starting

Inputs you choose:

- `CONFIG`: the operator configuration of the store, for example `/owned/source.toml`.
- `DIR`: a new private directory for proofs, for example `/owned/upgrade/rag065`.
- `DOMAIN` and `PROJECT`: the one scope to switch on. Use `--scope global`
  instead of `--project PROJECT` for global memories.

Checks you can run before changing anything:

1. The code you run has `version = "0.6.18"` in `pyproject.toml`. On the store,
   `SELECT filename FROM schema_migrations ORDER BY 1` ends with
   `029_source_evidence.sql`.
2. `DIR` lies on storage with at least three times the database size free.
3. List every writer: hooks, MCP servers, the hook-started local worker, timers,
   the central API and `rag service worker`. Note how to stop and restart each.
4. For part B, `rag status` shows a healthy model provider, and you know which
   provider and model `[synthesis]` or `[llm]` selects.

An unknown store version is an unresolved fact. It blocks part A.

## Part A: upgrade 0.6.17 to 0.6.18

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| A1 | Operator, store | `rag service --config CONFIG inventory --source-version 0.6.17 --identities --output DIR/inventory.json` | JSON with `"supported": true` | `unsupported_source_schema`: stop, escalate |
| A2 | Operator, store | `rag service --config CONFIG preflight --source-version 0.6.17 --mode local` | `"ready": true`, no blockers | Resolve listed blockers first |
| A3 | Operator, writers | Stop every writer from the list; keep the list with the proofs | No client connections except yours | A4 reports `database_clients_still_active` or `worker_still_active`: stop the named writer, repeat A4 with a new dump name |
| A4 | Operator, store | Authority: approved window. `rag service --config CONFIG upgrade --source-version 0.6.17 --dump DIR/synthesis030.dump --apply --writers-stopped` | `"migrations_applied": ["030_pattern_synthesis.sql"]`, `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/synthesis030.dump.manifest.json` | Any error: the migration rolled back; see *Interruption* |
| A5 | Operator, store | Repeat A4 with `--dump DIR/retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means A4 did not commit |
| A6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Keep writers stopped; escalate with the output |
| A7 | Operator, clients | Restart every writer on 0.6.18 | Services start. A 0.6.18 service on schema029 refuses with `incompatible_service_schema` | Check that it points at the upgraded store |
| A8 | Operator, store | `rag pattern status` | No policies and no runs | Anything else: stop, escalate |

`--source-version 0.6.17` names the version the store came from. The label
`0.6.18` is refused, also after the upgrade. A 0.6.17 process that keeps running
after A4 still reads and writes correctly on schema030, but restart it in A7.

## Part B: switch on one scope

Patterns are written as unreviewed inferences, so no step here changes what
ordinary search returns.

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| B1 | Operator, scope | `rag pattern preview --domain DOMAIN --project PROJECT` | Counts and exclusions; "no provider call, no write" | `insufficient` is normal for a new scope: forward runs wait until 3 independent events arrive |
| B2 | Operator, config | Add `[synthesis]` with `enabled = true` to the configuration of every process that changes pattern state: local CLI, hooks and MCP in standalone mode; the API and `rag service worker` on a central service. Restart the central API and worker | `rag pattern enable` no longer refuses | `synthesis_disabled` (409) or exit 1: a process still runs with the switch off |
| B3 | Operator, scope | Authority: the maintainer approved sending this scope to the provider. `rag pattern enable --domain DOMAIN --project PROJECT --reason "<why>"` | `pattern policy enabled (v1); forward boundary <time>` | `scope_denied`: the caller lacks write scope for this domain and project |
| B4 | Worker | Wait for the next worker tick after 3 independent new memories arrived; the interval is one day unless `--interval-seconds` was given | | |
| B5 | Operator, scope | `rag pattern status --domain DOMAIN --project PROJECT` | Runs with state, code, memories and provider calls; at most one provider call per run | See part C for `pending`, `error` and `withheld` |
| B6 | Operator, scope | `rag pattern list --domain DOMAIN --project PROJECT`, then `rag pattern show <slug>` | Label, "A reviewable hypothesis", support counts, citations with `ev1:` and `src1:` versions | `evidence_unavailable`: the pattern is withheld (part C) |

Before B3, decide whether earlier memories matter. Enabling never reads them;
use C1 if they do.

## Part C: operate

| Step | Situation | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| C1 | Earlier memories should be analyzed | `rag pattern backfill --domain DOMAIN --project PROJECT --start <ISO> --end <ISO> --reason "<why>" --max-batches 1` | `backfill <id> requested`; after the next tick a `backfill` run in `status`, or, if the window holds no qualifying memory, the backfill leaves `status` without a run | Window after the forward boundary or over 366 days: exit 1; choose a smaller window |
| C2 | A run stays `pending` | Check `rag status` for provider health. Nothing else: the worker retries after its provider backoff | The run becomes `applied` or `non_conclusion` with still one provider call | Outage persists: pause (C5) |
| C3 | `non_conclusion` with `invalid_output` | Check provider, model and `max_output_tokens`. No retry happens for this batch | The next batch can succeed | Repeats: pause (C5), escalate |
| C4 | `error` with `apply_failed` and `(recoverable)` in `status` | Fix the cause (for example storage or permissions), then `rag pattern recover <run_id> --reason "<what was fixed>"` | `run <id> re-queued (accepted)`; after the next tick `applied` without a further provider call | `not_recoverable`: another run is open or the run kept no answer. `policy_disabled`: enable first |
| C5 | Pause one scope | `rag pattern disable --domain DOMAIN --project PROJECT --reason "<why>"` | Its patterns disappear from `list`; nothing is deleted | |
| C6 | Pause everything | Set `[synthesis] enabled = false` on the processes from B2 and restart the central API and worker | No new run, provider call or backfill; patterns of enabled policies stay readable | |
| C7 | Resume | `rag pattern enable …` again (after C5) or set the switch back (after C6) | New forward boundary; the patterns of a re-enabled policy show again | Memories created while disabled are not analyzed; use C1 |
| C8 | `error` with `job_failed`, or `withheld` | Nothing to recover: no answer was accepted, or something it rests on changed | The next tick selects the current memories again | |

### Integrity check

Run after A8, after C4 and whenever counts look wrong. It only reads. Connect
with the database owner's `psql` session to the store and run:

```sql
-- PB065-INTEGRITY
SELECT
  (SELECT count(*) FROM synthesis_patterns) AS patterns,
  (SELECT count(*) FROM synthesis_patterns p
    WHERE p.dependency_count <> (SELECT count(*) FROM synthesis_dependencies d
                                 WHERE d.document_id = p.document_id)) AS dependency_mismatch,
  (SELECT count(*) FROM synthesis_patterns p
    WHERE NOT EXISTS (SELECT 1 FROM audit_log a
                      WHERE a.op = 'synthesis_apply' AND a.document_id = p.document_id)) AS pattern_without_audit,
  (SELECT count(*) FROM synthesis_runs r
    WHERE r.state = 'applied'
      AND NOT EXISTS (SELECT 1 FROM synthesis_patterns p WHERE p.run_id = r.id)) AS applied_without_pattern,
  (SELECT count(*) FROM synthesis_dependencies d
    JOIN synthesis_patterns p ON p.document_id = d.original_id) AS pattern_cites_pattern,
  (SELECT count(*) FROM synthesis_runs WHERE state IN ('pending', 'accepted')) AS open_runs;
```

Expected: every column except `patterns` and `open_runs` is 0, and `open_runs`
is at most the number of enabled policies. Any other value: pause (C6), keep the
output and escalate.

## Part D: interruption, rollback and restore

**Interrupted upgrade.** `to_regclass('public.synthesis_patterns')` is null and
`schema_migrations` lacks `030_pattern_synthesis.sql`: nothing committed; repeat
A4 with a new dump name. Both present: the upgrade committed; run A5. A mixed
state is a blocker.

**Code rollback to 0.6.17** keeps every write and needs no database change:

1. Disable every enabled policy (C5) and wait until `status` shows no `pending`
   or `accepted` run. A 0.6.17 worker cannot process queued pattern jobs.
2. Stop the writers, point them at the 0.6.17 code, restart them.
3. Expect: 0.6.17 reads and writes work on schema030 (rehearsed); its search
   stays guarded by the database. Its `memory_get` returns a pattern body when
   asked for the pattern id directly, because the old code lacks the read guard.

**Restore a backup taken after the upgrade.** Make one with
`rag service --config CONFIG verified-backup --source-version 0.6.17 --output DIR/current.dump`,
then follow PB-063 R1–R3 with these substitutions: both executables are 0.6.18,
the label stays `--source-version 0.6.17`, and the dump is `DIR/current.dump`.
Accepted runs restored without a live queue job are parked as `apply_failed` on
the next tick; recover them with C4.

**Restore the pre-upgrade state** discards every write after the A4 backup,
including all patterns. Obtain authorization for that recovery point, keep the
upgraded store intact and follow PB-063 R1–R4 with these substitutions:
`RAG016` is the 0.6.18 executable, `RAG015` the 0.6.17 executable, the label is
`--source-version 0.6.17`, and the dump is `DIR/synthesis030.dump`. A 0.6.18
service refuses the restored schema029 with `incompatible_service_schema`.

There is no schema downgrade.

## Escalation and preserved evidence

Escalate to the maintainer when A1, A2 or A4 report an unsupported store or a
preservation mismatch, when the integrity check is not clean, or when a pattern
cites something a reader of that scope must not see. Keep, without secrets: the
inventory, preflight and A4/A5 output, the dump and its manifest, `rag pattern
status --json` output and the integrity result. Do not attach dumps, quotes or
pattern bodies to public issues.

## Completion

Part A is complete when A4 and A5 succeeded, A6 shows no error, all clients run
0.6.18 and A8 shows no policy. Part B is complete when the policy is enabled,
`status` shows a finished run and the integrity check is clean. Keep the verified
dump until the next verified backup exists.

## Maintenance and sources

Reassess when a migration follows 030, when the `rag pattern` or operator
commands change, or when the pattern contract changes. Sources:
`agentic_rag/synthesis.py`, `agentic_rag/service/upgrade.py`
(`SUPPORTED_VERSIONS` includes 0.6.17), `agentic_rag/service/runner.py`,
`sql/030_pattern_synthesis.sql`, the [pattern-v1 contract](../../specs/6-7-pattern-synthesis/contracts/pattern-v1.md)
and [PB-063](rag-063-source-evidence-upgrade.md).

Change history: 2026-10-31 drafted with the RAG-065 implementation.
