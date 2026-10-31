# PB-065-OPS: Upgrade to 0.6.18 and operate pattern synthesis

## Identity and scope

- Class: system.
- Origin: RAG-065 FR-005 and tasks T065-007 and T065-013 in
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
- prove that every process with direct database access runs 0.6.18, then switch
  pattern synthesis on for one domain and project and read the first patterns
  (part B);
- request a history backfill, handle a provider outage, a budget block or a
  failed run, pause, disable and check integrity (part C);
- recover from an interrupted upgrade, restore a backup or return to 0.6.17
  (part D).

The upgrade adds tables, functions and redefined eligibility checks. It rewrites
no original row, grant or audit record and creates no policy, so nothing is
generated until part B. Behavior and terms: [pattern synthesis](../../pattern-synthesis.md).

Do not use it when:

- the store reports an unknown version or schema, or several stores need merging;
- writers cannot be stopped for part A, or there is no approved maintenance window;
- the memories of the scope must not reach the configured model provider. Part B
  sends quotes of up to 12 memories per run to that provider;
- you cannot name every host and environment that opens the database directly
  (step B0 needs that list).

## Before starting

Inputs you choose:

- `CONFIG`: the operator configuration of the store, for example `/owned/source.toml`.
- `DIR`: a new private directory for proofs, for example `/owned/upgrade/rag065`.
- `DOMAIN` and `PROJECT`: the one scope to switch on. Use `--scope global`
  instead of `--project PROJECT` for global memories.
- `ENV`: each Python environment that runs agentic-rag (a virtual environment,
  `uv tool` or `pipx` directory) on each host in the process list.

Checks you can run before changing anything:

1. The code you run has `version = "0.6.18"` in `pyproject.toml`. On the store,
   `SELECT filename FROM schema_migrations ORDER BY 1` ends with
   `029_source_evidence.sql`.
2. `DIR` lies on storage with at least three times the database size free.
3. Write the **process list**: every host and environment whose processes open
   the database directly: hooks, MCP servers of every agent client, the
   hook-started local worker, timers, local CLI use, the central API and
   `rag service worker`. Note how to stop and restart each. Clients in
   `[service] mode = "client"` reach the data only through the central API; they
   belong on the list only if they also hold a direct database configuration.
4. For part B, `rag status` shows a healthy model provider, and you know which
   provider and model `[synthesis]` or `[llm]` selects.

An unknown store version or an incomplete process list is an unresolved fact.
The first blocks part A, the second blocks step B3.

## Part A: upgrade 0.6.17 to 0.6.18

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| A1 | Operator, store | `rag service --config CONFIG inventory --source-version 0.6.17 --identities --output DIR/inventory.json` | JSON with `"supported": true` | `unsupported_source_schema`: stop, escalate |
| A2 | Operator, store | `rag service --config CONFIG preflight --source-version 0.6.17 --mode local` | `"ready": true`, no blockers | Resolve listed blockers first |
| A3 | Operator, process list | Stop every process on the list; keep the list with the proofs | No client connections except yours | A4 reports `database_clients_still_active` or `worker_still_active`: stop the named process, repeat A4 with a new dump name |
| A4 | Operator, store | Authority: approved window. `rag service --config CONFIG upgrade --source-version 0.6.17 --dump DIR/synthesis030.dump --apply --writers-stopped`. Note the time | `"migrations_applied": ["030_pattern_synthesis.sql"]`, `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/synthesis030.dump.manifest.json` | Any error: the migration rolled back; see *Interrupted upgrade* |
| A5 | Operator, store | Repeat A4 with `--dump DIR/retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means A4 did not commit |
| A6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Keep the processes stopped; escalate with the output |
| A7 | Operator, process list | Upgrade every environment on the list to 0.6.18, then start each process | Services start. A 0.6.18 service on schema029 refuses with `incompatible_service_schema` | Check that it points at the upgraded store |
| A8 | Operator, store | `rag pattern status` | No policies and no runs | Anything else: stop, escalate |

Keep `DIR/synthesis030.dump` and its manifest: it is the only way back to
0.6.17 once a pattern exists (part D).

`--source-version 0.6.17` names the version the store came from. The label
`0.6.18` is refused, also after the upgrade. Until the first pattern exists, a
0.6.17 process still reads and writes correctly on schema030 (rehearsed), but
step B0 must find none before synthesis is switched on.

## Part B: switch on one scope

Patterns are written as unreviewed inferences, so no step here changes what
ordinary search returns.

### B0: all-reader gate

A 0.6.17 process lacks the read guard for patterns. Its direct `memory_get`,
`memory_evidence`, `memory_evidence_history` and graph lookups by id
(`memory_neighbors`, `memory_path`) would serve a disabled or stale pattern. The
installed version alone does not prove what a running process loaded: an MCP
server started before the upgrade keeps 0.6.17 code in memory. Run B0 on every
host of the process list, after A7 and immediately before B3.

1. For each `ENV`, check what a freshly started process imports:

   ```bash
   ENV/bin/python -I - <<'PYFRESH'
   import importlib.metadata as m
   import agentic_rag.synthesis
   d = m.distribution('agentic-rag')
   print(d.version, next(f for f in d.files if f.name == 'METADATA').locate())
   PYFRESH
   ```

   Expected: `0.6.18` and the path of the installed `METADATA` file. Stop if the
   import fails or the version is lower: reinstall that environment.
2. With that `METADATA` path, list processes that started before the installation:

   ```bash
   python3 - METADATA_PATH <<'PYGATE'
   import os, re, subprocess, sys, time
   installed = os.stat(sys.argv[1]).st_mtime
   pattern = sys.argv[2] if len(sys.argv) > 2 else r'agentic[_-]rag|(^|/)rag( |$)'
   table = subprocess.run(['ps', '-eo', 'pid=,lstart=,args='], capture_output=True, text=True, check=True,
                          env={**os.environ, 'LC_ALL': 'C'}).stdout
   stale = []
   for line in table.splitlines():
       pid, rest = line.strip().split(None, 1)
       started, args = rest[:24], rest[24:].strip()
       if int(pid) in (os.getpid(), os.getppid()) or not re.search(pattern, args):
           continue
       if time.mktime(time.strptime(started, '%a %b %d %H:%M:%S %Y')) <= installed:
           stale.append(f'{pid} {started} {args[:160]}')
   print('\n'.join(stale) or 'no_stale_processes')
   sys.exit(1 if stale else 0)
   PYGATE
   ```

   Expected: `no_stale_processes`, exit 0. Exit 1 lists each process (pid, start
   time, command) that still runs code loaded before the installation: restart
   it, including agent sessions that host an MCP server, and repeat. The default
   pattern matches `agentic_rag`, `agentic-rag` and a `rag` command; pass a second
   argument if your process names differ.
3. On the store, list every direct database client:

   ```sql
   -- PB065-CLIENTS
   SELECT pid, usename, client_addr, application_name, backend_start
     FROM pg_stat_activity
    WHERE datname = current_database() AND backend_type = 'client backend'
      AND pid <> pg_backend_pid()
    ORDER BY backend_start;
   ```

   Expected: every `client_addr` belongs to a host on the process list (local
   socket connections show an empty address). Stop at an address you cannot
   name: an unknown direct client is not covered by steps 1 and 2.

Limit: B0 sees the hosts you list and the clients connected right now. A host
that is offline, or connects only later, is outside any check here. Keep the
process list complete and do not start 0.6.17 against this store again.

### B1–B6

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| B1 | Operator, scope | `rag pattern preview --domain DOMAIN --project PROJECT` | Counts and exclusions; "no provider call, no write" | `insufficient` is normal for a new scope: forward runs wait until 3 independent events arrive |
| B2 | Operator, config | Add `[synthesis]` with `enabled = true` to the configuration of every process that changes pattern state: local CLI, hooks and MCP in standalone mode; the API and `rag service worker` on a central service. Restart the central API and worker | `rag pattern enable` no longer refuses | `synthesis_disabled` (409) or exit 1: a process still runs with the switch off |
| B3 | Operator, scope | Preconditions: B0 passed on every listed host, and the maintainer approved sending this scope to the provider. `rag pattern enable --domain DOMAIN --project PROJECT --reason "<why>"` | `pattern policy enabled (v1); forward boundary <time>` | `scope_denied`: the caller lacks write scope for this domain and project |
| B4 | Worker | Wait for the next worker tick. Central: `rag service worker` ticks every few seconds. Standalone: ticks happen only while the hook-started worker runs, that is while an agent session is active. A forward run starts once the new memories, together with recent context, contain 3 independent events; the next forward run of the same scope waits for the interval (one day unless `--interval-seconds` was given), unless memories were left over | `rag pattern status` shows `pending N` falling to 0 and a run | `pending N (insufficient_independent_support)`: wait for more memories. `(input_budget_below_floor)` or `oversized N`: C9 |
| B5 | Operator, scope | `rag pattern status --domain DOMAIN --project PROJECT` | Runs with state, code, memories (new and context) and provider calls; at most one provider call per run | See part C for `pending`, `error` and `withheld` |
| B6 | Operator, scope | `rag pattern list --domain DOMAIN --project PROJECT`, then `rag pattern show <slug>` | Label, "A reviewable hypothesis", support counts, citations with `ev1:` and `src1:` versions | `evidence_unavailable`: the pattern is withheld (part C) |

Before B3, decide whether earlier memories matter. Enabling never reads them;
use C1 if they do.

## Part C: operate

`pending N` in `status` counts the eligible memories after the forward boundary
that no finished run has analysed yet. A memory saved by a long transaction is
counted once it commits, whatever its creation time. A run records its new
memories as analysed only when it ends `applied` or `non_conclusion`.

| Step | Situation | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| C1 | Earlier memories should be analysed | `rag pattern backfill --domain DOMAIN --project PROJECT --start <ISO> --end <ISO> --reason "<why>" --max-batches 1` | `backfill <id> requested`; after the next tick a `backfill` run in `status`, or, if the window holds no qualifying memory, the backfill leaves `status` without a run | Window after the forward boundary or over 366 days: exit 1; choose a smaller window |
| C2 | A run stays `pending` | Check `rag status` for provider health. Nothing else: the worker retries after its provider backoff | The run becomes `applied` or `non_conclusion` with still one provider call | Outage persists past the worker's finite attempts: the run becomes `error job_failed` (C8). Pause (C5) if it repeats |
| C3 | `non_conclusion` with `invalid_output` | Check provider, model and `max_output_tokens`. No automatic retry: the run's new memories count as analysed | Forward runs offer them again only as context when new memories arrive | To analyse them as new again: C5, C7, then C1 with a window that covers them. A repeat over unchanged evidence cannot apply a duplicate pattern |
| C4 | `error` with `apply_failed` and `(recoverable)` in `status`; its memories show as `held for recovery` | Fix the cause (for example storage or permissions), then `rag pattern recover <run_id> --reason "<what was fixed>"`. Standalone: the operator's local CLI. Central: a writer of that scope with the client CLI (it calls the API), or the server operator's local CLI | `run <id> re-queued (accepted)`; after the next tick `applied` without a further provider call | `not_recoverable`: another run is open or the run kept no answer. `policy_disabled`: enable first. `scope_denied`: the caller lacks write scope |
| C5 | Pause one scope | `rag pattern disable --domain DOMAIN --project PROJECT --reason "<why>"` | Its patterns disappear from `list`; nothing is deleted | |
| C6 | Pause everything | Set `[synthesis] enabled = false` on the processes from B2 and restart the central API and worker | No new run, provider call or backfill; patterns of enabled policies stay readable | |
| C7 | Resume | `rag pattern enable …` again (after C5) or set the switch back (after C6) | New forward boundary; the patterns of a re-enabled policy show again | Memories created while disabled are not analysed; use C1 |
| C8 | `error` with `job_failed`, or `withheld` | Nothing to recover: no answer was accepted, or something it rests on changed. Its memories were not recorded as analysed | The next forward tick plans the still eligible memories again | |
| C9 | `pending N (input_budget_below_floor)` or `oversized N` | The memories, or one memory alone, do not fit the provider input. Nothing was sent or consumed, and no run retries by itself. Raise `max_input_chars` in `[synthesis]` (at most 24000) on the worker's configuration; the effective limit is the smaller of `[synthesis]` and `[llm]` `max_input_chars`. Restart the worker | After the next tick: a run, and `pending`/`oversized` fall | A memory whose spans exceed 24000 characters stays `oversized`; this release has no route to analyse it |

### Integrity check

Run after A8, after C4 and whenever counts look wrong. After C5, run it only
after the next worker tick: a run that was open when its policy was disabled is
closed (`withheld policy_disabled`) by that tick. The check only reads. Connect
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
  (SELECT count(*) FROM synthesis_processed m JOIN synthesis_runs r ON r.id = m.run_id
    WHERE r.state NOT IN ('applied', 'non_conclusion')) AS processed_without_terminal_run,
  (SELECT count(*) FROM synthesis_runs r JOIN synthesis_policies p ON p.id = r.policy_id
    WHERE r.state IN ('pending', 'accepted') AND NOT p.enabled) AS open_runs_of_disabled_policies;
```

Expected: every column except `patterns` is 0. Any other value after the next
tick: pause (C6), keep the output and escalate.

## Part D: interruption, rollback and restore

**Interrupted upgrade.** `to_regclass('public.synthesis_patterns')` is null and
`schema_migrations` lacks `030_pattern_synthesis.sql`: nothing committed; repeat
A4 with a new dump name. Both present: the upgrade committed; run A5. A mixed
state is a blocker.

**Decide the way back by one fact:** `SELECT count(*) FROM synthesis_patterns`.

*No pattern exists (0).* A code-only return to 0.6.17 is supported and keeps
every write:

1. Disable every enabled policy (C5) and wait until `status` shows no `pending`
   or `accepted` run. A 0.6.17 worker cannot process queued pattern jobs.
2. Stop the processes on the list, point them at the 0.6.17 code, restart them.
3. Expect: 0.6.17 reads and writes work on schema030 (rehearsed). Before
   enabling synthesis again, repeat B0.

*A pattern exists (1 or more).* A code-only return to 0.6.17 is **not
supported**, also with every policy disabled: old `memory_get`,
`memory_evidence` and `memory_evidence_history` return a disabled or stale
pattern (rehearsed), and old graph lookups by id lack the guard as well. Choose
one:

1. Stay on 0.6.18 and repair forward: disable the scope (C5), fix the cause,
   recover (C4) or enable again (C7).
2. Restore the verified pre-upgrade dump for retained 0.6.17 code (below). This
   discards every write after A4. Before the restore, export the list of those
   writes from the upgraded store, which you keep intact:

   ```sql
   SELECT at, actor, op, document_id FROM audit_log WHERE at > '<A4 time>' ORDER BY at;
   ```

   Re-enter each needed memory on 0.6.17 through `rag save` or `memory_save`
   after the restore; patterns and policies are not carried over.

**Restore a backup taken after the upgrade.** Make one with
`rag service --config CONFIG verified-backup --source-version 0.6.17 --output DIR/current.dump`.
The label stays `0.6.17` because the operator tools accept only supported source
releases (0.6.0 to 0.6.17), and 0.6.18 is the running target, not a source
(`unsupported_source_version`). The dump and its manifest are read from the
actual store, schema030 and pattern tables included; the label does not change
what is saved. Then follow PB-063 R1–R3 with these substitutions: both
executables are 0.6.18, the label stays `--source-version 0.6.17`, and the dump
is `DIR/current.dump`. Accepted runs restored without a live queue job are
parked as `apply_failed` on the next tick; recover them with C4.

**Restore the pre-upgrade state** discards every write after the A4 backup,
including all patterns. Obtain authorization for that recovery point, keep the
upgraded store intact, export the post-backup writes as above, and follow PB-063
R1–R4 with these substitutions: `RAG016` is the 0.6.18 executable, `RAG015` the
0.6.17 executable, the label is `--source-version 0.6.17`, and the dump is
`DIR/synthesis030.dump`. A 0.6.18 service refuses the restored schema029 with
`incompatible_service_schema`.

There is no schema downgrade.

## Escalation and preserved evidence

Escalate to the maintainer when A1, A2 or A4 report an unsupported store or a
preservation mismatch, when B0 finds an unknown direct client, when the
integrity check is not clean, or when a pattern cites something a reader of that
scope must not see. Keep, without secrets: the process list, the B0 outputs, the
inventory, preflight and A4/A5 output, the dump and its manifest, `rag pattern
status --json` output and the integrity result. Do not attach dumps, quotes or
pattern bodies to public issues.

## Completion

Part A is complete when A4 and A5 succeeded, A6 shows no error, all processes on
the list run 0.6.18 and A8 shows no policy. Part B is complete when B0 passed on
every listed host, the policy is enabled, `status` shows a finished run and the
integrity check is clean. Keep the verified pre-upgrade dump until you decide
never to return to 0.6.17.

## Maintenance and sources

Reassess when a migration follows 030, when the `rag pattern` or operator
commands change, when the process types that open the database change, or when
the pattern contract changes. Sources: `agentic_rag/synthesis.py`,
`agentic_rag/service/upgrade.py` (`SUPPORTED_VERSIONS` covers 0.6.0–0.6.17),
`agentic_rag/service/runner.py`, `sql/030_pattern_synthesis.sql`, the
[pattern-v1 contract](../../specs/6-7-pattern-synthesis/contracts/pattern-v1.md)
and [PB-063](rag-063-source-evidence-upgrade.md).

Change history: 2026-10-31 drafted with the RAG-065 implementation; 2026-10-31
revised for review findings PB065-R01..R06 and R65-04 (B0 all-reader gate,
forbidden code-only rollback after patterns, central C4, budget block C9,
processed-membership semantics, integrity after the next tick).
