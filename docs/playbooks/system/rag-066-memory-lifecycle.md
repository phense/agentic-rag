# PB-066-OPS: Upgrade to 0.6.19 and operate memory lifecycle decisions

## Identity and scope

- Class: system.
- Origin: RAG-066 FR-005 and tasks T066-008 and T066-011 in
  [the specification](../../specs/6-8-memory-lifecycle/spec.md).
- Audience and owner: the operator of a local or central agentic-rag database.
  The maintainer owns production authorization; drafting this playbook
  authorizes no live operation.
- Target: package 0.6.19, migration `031_memory_lifecycle.sql`, from a populated
  0.6.18 installation at schema030 (`main` at `d4d2372`). Earlier sources first
  follow their own playbooks ([PB-065](rag-065-pattern-synthesis.md)).
- Readiness deadline: independent review and isolated rehearsal before the RAG-066
  pull request is handed off.
- Last edited: 2026-11-01.
- Review and rehearsal evidence: [rag-066-memory-lifecycle-review.md](rag-066-memory-lifecycle-review.md).

## When to use / when not to use

Use this procedure to:

- upgrade a 0.6.18 store to schema031 (part A);
- make sure no process still runs the 0.6.18 automatic curation unguarded
  (part B0), then record the first lifecycle decisions (part B);
- handle refused, stale, contested or wrong decisions (part C);
- recover from an interrupted upgrade, restore a backup or return to 0.6.18
  (part D).

A lifecycle decision says that one memory (the *member*) is a duplicate, an
extension, a replaced version or a contradiction of another (the *target*). The
decision is a separate audited record. It never edits, archives or deletes either
memory, its evidence, links or pins; correcting it makes the member visible again.
The upgrade adds tables, functions and a redefined eligibility check and creates
no decision. Behavior and terms: [memory lifecycle](../../memory-lifecycle.md).

Do not use it when:

- the store reports an unknown version or schema, or several stores need merging;
- writers cannot be stopped for part A, or there is no approved maintenance window;
- you cannot name every host and environment that opens the database directly
  (step B0 needs that list).

## Before starting

Inputs you choose:

- `CONFIG`: the operator configuration of the store, for example `/owned/source.toml`.
- `DIR`: a new private directory for proofs, for example `/owned/upgrade/rag066`.
- `ENV`: each Python environment that runs agentic-rag (a virtual environment,
  `uv tool` or `pipx` directory) on each host in the process list.

Checks you can run before changing anything:

1. The code you run has `version = "0.6.19"` in `pyproject.toml`. On the store,
   `SELECT filename FROM schema_migrations ORDER BY 1` ends with
   `030_pattern_synthesis.sql`.
2. `DIR` lies on storage with at least three times the database size free.
3. Write the **process list**: every host and environment whose processes open
   the database directly: hooks, MCP servers of every agent client, the
   hook-started local worker, timers, local CLI use, the central API and
   `rag service worker`. Note how to stop and restart each. Clients in
   `[service] mode = "client"` reach the data only through the central API.

An unknown store version or an incomplete process list is an unresolved fact.
The first blocks part A, the second blocks part B.

## Part A: upgrade 0.6.18 to 0.6.19

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| A1 | Operator, store | `rag service --config CONFIG inventory --source-version 0.6.18 --identities --output DIR/inventory.json` | JSON with `"supported": true` | `unsupported_source_schema`: stop, escalate |
| A2 | Operator, store | `rag service --config CONFIG preflight --source-version 0.6.18 --mode local` | `"ready": true`, no blockers | Resolve listed blockers first |
| A3 | Operator, process list | Stop every process on the list; keep the list with the proofs | No client connections except yours | A4 reports `database_clients_still_active` or `worker_still_active`: stop the named process, repeat A4 with a new dump name |
| A4 | Operator, store | Authority: approved window. `rag service --config CONFIG upgrade --source-version 0.6.18 --dump DIR/lifecycle031.dump --apply --writers-stopped`. Note the time | `"migrations_applied": ["031_memory_lifecycle.sql"]`, `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/lifecycle031.dump.manifest.json` | Any error: the migration rolled back; see *Interrupted upgrade* |
| A5 | Operator, store | Repeat A4 with `--dump DIR/retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means A4 did not commit |
| A6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Keep the processes stopped; escalate with the output |
| A7 | Operator, process list | Upgrade every environment on the list to 0.6.19, then start each process | Services start. A 0.6.19 service on schema030 refuses with `incompatible_service_schema` | Check that it points at the upgraded store |
| A8 | Operator, store | Run the integrity check below | `decisions` 0 and every other column 0 | Anything else: stop, escalate |

The migration needs no provider and changes no stored version: every `ev1:`
document version and `src1:` source version stays the same (rehearsed). Keep
`DIR/lifecycle031.dump` and its manifest until you decide never to return to
the pre-upgrade state (part D).

`--source-version 0.6.18` names the version the store came from. The label
`0.6.19` is refused, also after the upgrade.

## Part B: record decisions

### B0: curation gate

A 0.6.18 process works on schema031: its searches already hide decided members,
because the hiding happens in the database. One 0.6.18 behavior stays unsafe.
Its automatic curation archives a memory whose body equals another one even when
the titles differ (for example "Build server alpha port" and "Build server beta
port"); 0.6.19 requires the same title and type. Old curation runs in the
hook-started worker and in `rag service worker`. Run B0 on every host of the
process list, after A7 and before relying on automatic curation.

1. For each `ENV`, check what a freshly started process imports:

   ```bash
   ENV/bin/python -I - <<'PYFRESH'
   import importlib.metadata as m
   import agentic_rag.lifecycle
   d = m.distribution('agentic-rag')
   print(d.version, next(f for f in d.files if f.name == 'METADATA').locate())
   PYFRESH
   ```

   Expected: `0.6.19` and the path of the installed `METADATA` file. Stop if the
   import fails or the version is lower: reinstall that environment, or use the
   fallback in step 4.
2. For each `ENV`, use its `METADATA` path to list processes that started before
   the installation:

   ```bash
   python3 - METADATA_PATH <<'PYGATE'
   import os, re, subprocess, sys, time
   metadata = os.stat(sys.argv[1])
   installed = max(metadata.st_mtime, metadata.st_ctime)
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
   it, including agent sessions that host an MCP server, and repeat. Pass a
   second argument if your process names differ from the default pattern.
3. On the store, list every direct database client:

   ```sql
   -- PB066-CLIENTS
   SELECT pid, usename, client_addr, application_name, backend_start
     FROM pg_stat_activity
    WHERE datname = current_database() AND backend_type = 'client backend'
      AND pid <> pg_backend_pid()
    ORDER BY backend_start;
   ```

   Expected: every `client_addr` belongs to a host on the process list (local
   socket connections show an empty address). Stop at an address you cannot name.
4. Fallback for a process that must stay on 0.6.18 for a while: add

   ```toml
   [curation]
   budget = 0
   ```

   to its configuration and restart it. With budget 0 the old worker archives
   nothing (rehearsed). Remove the setting after that process runs 0.6.19.

Limit: B0 sees the hosts you list and the clients connected right now.

### B1–B5

Commands work the same locally and on a central client (`[service] mode =
"client"`). A central caller needs read scope for preview and show, and write
scope for the domain and project of both memories for apply and correct.

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| B1 | Operator, store | `rag review`, then decide which pair to look at. Its *duplicate candidates* are old `duplicate_of` links; *lifecycle review* lists contested and stale decisions | The pair you want to decide, as two ids or slugs | Nothing listed: choose pairs from ordinary search results |
| B2 | Operator, pair | `rag lifecycle preview MEMBER TARGET` for an exact copy, or `rag lifecycle preview MEMBER TARGET --operation OP` with `OP` one of `semantic_duplicate`, `extension`, `replacement`, `contradiction`. Add `--json` to copy the versions | Classification, proof, each operation `allowed` or with a code, and both `lv1:` versions. "No write, no provider call." | A code instead of a classification, or the wanted operation not `allowed`: C5 |
| B3 | Operator, pair | Authority: you checked both texts. `rag lifecycle apply MEMBER TARGET --operation OP --member-version V1 --target-version V2 --reason "<why>"`. Add `--reviewed` for `semantic_duplicate`, `extension` and `replacement`, which are your judgement, not a proof. Optionally `--request-key KEY` to make a retry safe | `decision <id>: OP active` (`contested` for a contradiction) | `stale_version`: C1. Any other code: C2–C5 |
| B4 | Operator, pair | `rag lifecycle show MEMBER`, then `rag search "<query>" --view current` and `--view include_merged`, and `rag get MEMBER --view current` | `show`: relationship `hiding`, `replaced` or `contested`. The member is absent from the current search and present with `include_merged` (duplicates and extensions only). `get --view current` answers with the target and `resolution: canonical` | The member still appears in current search: `show` names the relationship; `stale` means C7 |
| B5 | Operator, decision | Record the decision id from B3 with your change notes | The id and its revision (1) | |

A plain `rag search` without `--view` uses the current view. `rag get MEMBER`
without `--view` still shows the member itself, so nothing is lost from sight.

## Part C: refusals, stale decisions and correction

Every refusal writes nothing: no decision, event or audit row.

| Step | Situation | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| C1 | `stale_version` | One of the memories, its evidence or its decisions changed after your preview. Repeat B2, check the texts again, apply with the new versions | A new `decision … active` | `stale_version` again: someone keeps editing; wait and repeat |
| C2 | `replay_mismatch` | The request key was already used for a different request. Use a new key, or run `rag lifecycle show MEMBER` to see what the first request did | The first decision is listed once | |
| C3 | `already_active` or `chain_conflict` | The member already has an active decision, or one of the two is a member or target in another decision. Decisions stay one step deep. Use `rag lifecycle show` on both, then decide against the existing target, or correct the old decision first (C6) | A single flat decision | |
| C4 | `busy` | Another writer held one of the memories for more than 2 seconds. Repeat B3 | `decision … active` | Repeats: find the long transaction in `pg_stat_activity` |
| C5 | `proof_failed`, `review_required`, `event_order_unproven`, `scope_mismatch`, `unknown_scope`, `assertion_managed`, `not_current`, `not_found`, `scope_denied` | Read the code: `proof_failed` the copies are not identical; `review_required` add `--reviewed` after checking; `event_order_unproven` the sources do not prove which is newer; `scope_mismatch`/`unknown_scope` different or unknown domain or project; `assertion_managed` the memory is a fact assertion, use `memory_assert`; `not_current` a refuted, withdrawn or unqualified memory; `not_found`/`scope_denied` wrong id or missing scope | No decision. Choose another operation, another target or leave both | |
| C6 | Wrong decision | `rag lifecycle correct DECISION --revision N --reason "<why>"` with `N` from `show` (1 for a new decision) | `decision <id>: OP corrected`; the member is in current search again; `rag lifecycle history MEMBER` shows both events | `stale_version`: the revision changed, run `show` again. Correction never revives a memory that was refuted or whose source was withdrawn in the meantime |
| C7 | `rag review` or `show` lists `stale` | Member or target changed after the decision, or the target is no longer current: a duplicate or extension stops hiding by itself. To merge again: C6 on the stale decision, then B2–B3 | The member is visible until you decide again | |
| C8 | `show` lists `canonical_unavailable` | The target of a replacement was refuted or deleted. The member stays hidden because it was replaced. Correct the decision (C6) if the member should answer again | | |
| C9 | Apply fails without a code (database permission, audit write) | Nothing was written. Fix the permission and repeat B3 | `decision … active` | Escalate with the error text |

### Integrity check

Run after A8 and whenever counts look wrong. The check only reads. Connect with
the database owner's `psql` session to the store and run:

```sql
-- PB066-INTEGRITY
SELECT
  (SELECT count(*) FROM lifecycle_decisions) AS decisions,
  (SELECT count(*) FROM lifecycle_decisions d
    WHERE NOT EXISTS (SELECT 1 FROM lifecycle_events e WHERE e.decision_id = d.id
                      AND e.event IN ('applied', 'recorded'))) AS decision_without_event,
  (SELECT count(*) FROM lifecycle_decisions d
    WHERE d.state = 'corrected'
      AND NOT EXISTS (SELECT 1 FROM lifecycle_events e WHERE e.decision_id = d.id
                      AND e.event = 'corrected')) AS correction_without_event,
  (SELECT count(*) FROM lifecycle_events) - (SELECT count(*) FROM audit_log
    WHERE op IN ('lifecycle_apply', 'lifecycle_correct')) AS events_minus_audit,
  (SELECT count(*) FROM lifecycle_decisions a JOIN lifecycle_decisions b
    ON b.target_id = a.member_id
    WHERE a.state = 'active' AND b.state = 'active') AS chains;
```

Expected: every column except `decisions` is 0. Any other value: stop recording
decisions, keep the output and escalate.
Only active hiding decisions count as chains; a contested contradiction never
forms a hiding chain. A nonzero `decision_without_event` is escalation-only:
the ordinary correction command requires an existing event revision. Preserve
the store and its audit evidence for maintainer-led repair; do not invent a
revision or delete the decision directly.

## Part D: interruption, rollback and restore

**Interrupted upgrade.** `to_regclass('public.lifecycle_decisions')` is null and
`schema_migrations` lacks `031_memory_lifecycle.sql`: nothing committed; repeat
A4 with a new dump name. Both present: the upgrade committed; run A5. A mixed
state is a blocker.

**Return to 0.6.18 code without restoring.** Supported, also after decisions
exist (rehearsed): 0.6.18 reads, `get`, evidence history and ordinary writes work
on schema031, and its searches keep hiding decided members. Before you switch:

1. Correct (C6) every decision you do not want to keep; 0.6.18 has no lifecycle
   commands, so decisions can only be corrected with 0.6.19.
2. Set `[curation] budget = 0` (B0 step 4) on every 0.6.18 process.
3. Stop the processes on the list, point them at the 0.6.18 code, restart them.

An edit made by 0.6.18 to a decided memory makes a duplicate or extension stale
(C7), so the member answers again; replacements stay in force.

**Restore a backup taken after the upgrade.** Make one with
`rag service --config CONFIG verified-backup --source-version 0.6.18 --output DIR/current.dump`.
The label stays `0.6.18` because the operator tools accept only supported source
releases (0.6.0 to 0.6.18). The dump and its manifest are read from the actual
store, lifecycle tables included. Then follow PB-063 R1–R3 with these
substitutions: both executables are 0.6.19, the label is `--source-version
0.6.18`, and the dump is `DIR/current.dump`. Decisions, events and their guard
triggers come back with the restore (rehearsed); run the integrity check on the
restored store.

**Restore the pre-upgrade state** discards every write after the A4 backup,
including all decisions. There is no way to keep those writes in a restore of the
older dump. Obtain authorization for that recovery point, keep the upgraded store
intact and export the post-backup writes first:

```sql
SELECT at, actor, op, document_id FROM audit_log WHERE at > '<A4 time>' ORDER BY at;
```

Then follow PB-063 R1–R4 with these substitutions: `RAG016` is the 0.6.19
executable, `RAG015` the 0.6.18 executable, the label is `--source-version
0.6.18`, and the dump is `DIR/lifecycle031.dump`. Re-enter each needed memory on
0.6.18 after the restore; decisions are not carried over. A 0.6.19 service
refuses the restored schema030 with `incompatible_service_schema`.

There is no schema downgrade.

## Escalation and preserved evidence

Escalate to the maintainer when A1, A2 or A4 report an unsupported store or a
preservation mismatch, when B0 finds an unknown direct client, or when the
integrity check is not clean. Keep, without secrets: the process list, the B0
outputs, the inventory, preflight and A4/A5 output, the dump and its manifest,
the decision ids with their reasons and the integrity result. Do not attach
dumps or memory texts to public issues.

## Completion

Part A is complete when A4 and A5 succeeded, A6 shows no error, all processes on
the list run 0.6.19 and the integrity check is clean. Part B is complete when B0
passed on every listed host (or step 4 is in place for each 0.6.18 process),
each recorded decision shows the expected relationship in B4 and the integrity
check is clean. Keep the verified pre-upgrade dump until you decide never to
return to the pre-upgrade state.

## Maintenance and sources

Reassess when a migration follows 031, when the `rag lifecycle` or operator
commands change, when the process types that open the database change, or when
the lifecycle contract changes. Sources: `agentic_rag/lifecycle.py`,
`agentic_rag/curation.py`, `agentic_rag/service/upgrade.py` (`SUPPORTED_VERSIONS`
covers 0.6.0–0.6.18), `sql/031_memory_lifecycle.sql`, the
[lifecycle-v1 contract](../../specs/6-8-memory-lifecycle/contracts/lifecycle-v1.md)
and [PB-063](rag-063-source-evidence-upgrade.md).

Change history: 2026-11-01 drafted with the RAG-066 implementation.
