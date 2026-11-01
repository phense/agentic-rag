# PB-067-OPS: Upgrade to 0.6.20 and operate the extraction policy

## Identity and scope

- Class: system.
- Origin: RAG-067 US-002/US-003, AC-005, AC-007 and AC-009, tasks T067-006 and
  T067-007 in [the specification](../../specs/6-9-extraction-instructions/spec.md).
- Audience and owner: the operator of a local or central agentic-rag database.
  The maintainer owns production authorization; drafting this playbook
  authorizes no live operation.
- Target: package 0.6.20, migration `032_extraction_policy.sql`, from a populated
  0.6.19 installation at schema031 (`main` at `01bc13b`). Earlier sources first
  follow their own playbooks ([PB-066](rag-066-memory-lifecycle.md)).
- Readiness deadline: independent review and isolated rehearsal before the RAG-067
  pull request is handed off.
- Last edited: 2026-11-01.
- Review and rehearsal evidence: [rag-067-extraction-policy-review.md](rag-067-extraction-policy-review.md).

## When to use / when not to use

Use this procedure to:

- upgrade a 0.6.19 store to schema032 (part A);
- make sure no process still runs 0.6.19 mining code, then activate a custom
  extraction policy file (part B);
- recover from an invalid policy file, inspect queued work and retry it under
  the policy it was admitted with (part C);
- roll a policy back, return to 0.6.19 code or restore a backup (part D).

The extraction policy is an optional, operator-owned TOML file that narrows what
session mining keeps: which output categories, how many items per category, how
long an item text may be, plus advisory guidance and examples for the provider.
It never changes authorization, evidence checks, pins, auditing or provider
budgets. Every piece of mining work keeps the policy it was admitted with; a file
change only affects new work and never re-mines history. Behavior, file format
and limits: [extraction policy](../../extraction-policy.md).

Do not use it when:

- the store reports an unknown version or schema, or several stores need merging;
- writers cannot be stopped for part A, or there is no approved maintenance window;
- you cannot name every host and environment that opens the database directly
  or runs mining (step B1 needs that list).

## Before starting

Inputs you choose:

- `CONFIG`: the operator configuration of the store, for example `/owned/source.toml`.
- `DIR`: a new private directory for proofs, for example `/owned/upgrade/rag067`.
- `ENV`: each Python environment that runs agentic-rag (a virtual environment,
  `uv tool` or `pipx` directory) on each host in the process list.
- `POLICY`: the absolute path of the policy file on the host that mines. For a
  central service this is a file on the service host; clients never send one.

Checks you can run before changing anything:

1. The code you run has `version = "0.6.20"` in `pyproject.toml`. On the store,
   `SELECT filename FROM schema_migrations ORDER BY 1` ends with
   `031_memory_lifecycle.sql`.
2. `DIR` lies on storage with at least three times the database size free.
3. Write the **process list**: every host and environment whose processes open
   the database directly or admit or run mining work: Stop and SessionEnd hooks of
   every agent client, MCP servers, the hook-started local worker, timers, local
   `rag` CLI use, the central API (`rag service serve`) and `rag service worker`.
   Note how to stop and restart each. Clients in `[service] mode = "client"` reach
   the data only through the central API and need no policy file.

An unknown store version or an incomplete process list is an unresolved fact.
The first blocks part A, the second blocks part B.

## Part A: upgrade 0.6.19 to 0.6.20

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| A1 | Operator, store | `rag service --config CONFIG inventory --source-version 0.6.19 --identities --output DIR/inventory.json` | JSON with `"supported": true` | `unsupported_source_schema`: stop, escalate |
| A2 | Operator, store | `rag service --config CONFIG preflight --source-version 0.6.19 --mode local` | `"ready": true`, no blockers | Resolve listed blockers first |
| A3 | Operator, process list | Stop every process on the list; keep the list with the proofs | No client connections except yours | A4 reports `database_clients_still_active` or `worker_still_active`: stop the named process, repeat A4 with a new dump name |
| A4 | Operator, store | Authority: approved window. `rag service --config CONFIG upgrade --source-version 0.6.19 --dump DIR/policy032.dump --apply --writers-stopped`. Note the time | `"migrations_applied": ["032_extraction_policy.sql"]`, `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/policy032.dump.manifest.json` | Any error: the migration rolled back; see *Interrupted upgrade* in part D |
| A5 | Operator, store | Repeat A4 with `--dump DIR/retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means A4 did not commit |
| A6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Keep the processes stopped; escalate with the output |
| A7 | Operator, process list | Upgrade every environment on the list to 0.6.20, then start each process. Do **not** set `[mining] policy_file` yet | Services start. A 0.6.20 service on schema031 refuses with `incompatible_service_schema` | Check that it points at the upgraded store |
| A8 | Operator, store | Run the integrity check below | `bindings` 0 and every other column 0 | Anything else: stop, escalate |

The migration needs no provider and changes no stored row: every original row,
grant, owner, sequence, queued job, accepted mining batch and source window stays
the same, and every `ev1:` document version and `src1:` source version is
unchanged (rehearsed). It adds one empty table, `extraction_policy_bindings`.
Keep `DIR/policy032.dump` and its manifest until you decide never to return to
the pre-upgrade state (part D).

Without a policy file 0.6.20 uses the 0.6.19 prompt, schema and retained output,
while adding builtin binding/audit, batch policy metadata and provenance.
Work queued before the upgrade, or admitted while no file
is configured, always uses these builtin rules, even after you add a file.

`--source-version 0.6.19` names the version the store came from. The label
`0.6.21` is refused. The current0.6.20 label is supported for post-upgrade inventories and backups.

## Part B: activate a custom policy

### B1: mining gate

A 0.6.19 process works on schema032 for ordinary reads and writes. Its mining
does not: it ignores the captured policy, keeps every category and sends no
preferences to the provider (rehearsed). So every process that admits or runs
mining must run 0.6.20 before step B3. Run B1 on every host of the process list.

1. For each `ENV`, check what a freshly started process imports:

   ```bash
   ENV/bin/python -I - <<'PYFRESH'
   import importlib.metadata as m
   import agentic_rag.extraction_policy
   d = m.distribution('agentic-rag')
   print(d.version, next(f for f in d.files if f.name == 'METADATA').locate())
   PYFRESH
   ```

   Expected: `0.6.20` and the path of the installed `METADATA` file. Stop if the
   import fails or the version is lower: reinstall that environment.
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
   -- PB067-CLIENTS
   SELECT pid, usename, client_addr, application_name, backend_start
     FROM pg_stat_activity
    WHERE datname = current_database() AND backend_type = 'client backend'
      AND pid <> pg_backend_pid()
    ORDER BY backend_start;
   ```

   Expected: every `client_addr` belongs to a host on the process list (local
   socket connections show an empty address). Stop at an address you cannot name.

Limit: B1 sees the hosts you list and the clients connected right now. There is
no fallback setting that makes 0.6.19 mining honor a policy.

### B2–B5: validate, inspect, activate

For editable installs or a wall-clock step since boot, restart every listed
process unconditionally; the timestamp check alone is insufficient. Policy and
sample paths must be regular files. Check sample size (at most 64 KiB) before
reading it; devices, FIFOs and oversized transcripts are not supported.

| Step | Actor and target | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| B2 | Operator, draft file | Write the draft next to `POLICY` (same directory), for example `POLICY.new`. `rag extraction validate --file POLICY.new` | `"valid": true`, an `identity` starting with `xf1:`, the rule count and the caps. No provider call, no write | `"valid": false` lists `code` and `location` per error, never the value: fix that place and repeat. Codes: [extraction policy](../../extraction-policy.md#error-codes) |
| B3 | Operator, draft file | `rag extraction inspect --file POLICY.new --project PROJECT` for each project you care about | Per domain: `scopes` in precedence order, `digest`, enabled `categories`, effective `limits`, guidance; plus `domainless` | Unexpected scopes: a project rule overrides a domain rule, an exact rule overrides both. Adjust and go back to B2 |
| B4 | Operator, sample | Optional. Write a sample `{"events": [{"source_id": "e1", "role": "user", "text": "..."}]}` without private data. `rag extraction dry-run --file POLICY.new --project PROJECT --sample SAMPLE` | `provider_calls` 0, `writes` 0, `would_call_provider`, the rendered preferences, `sample_redactions` | Add `--evaluate` only if you accept one provider call on the sample with the configured provider; it still writes nothing. Its result shows retained items and rejected counts, not whether an item is true |
| B5 | Operator, every mining host | Authority: B1 passed on every host. Keep the current file as `POLICY.prev` (if one exists), then replace atomically: `mv POLICY.new POLICY`. If `[mining] policy_file = "POLICY"` is not yet in the configuration, add it and restart `rag service serve` and `rag service worker` (they read the configuration at start); hooks read it on each run | `rag extraction validate` (no `--file`) prints `"configured": true` and the same `identity` as B2 | `"valid": false`: part C1 |

When the change takes effect: the file *content* is read once per new admission,
so a replaced file applies to the next admitted job or window without a restart.
A changed `policy_file` *path* applies after the process rereads its
configuration. Work already admitted keeps its policy (part C3).

## Part C: invalid files, queued work and retries

| Step | Situation | Action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| C1 | Invalid file in use. Local hooks log `invalid extraction policy: <code> at <location>` and admit no new job; a central service answers new windows with `extraction_policy_invalid` (HTTP 503), clients keep them in their spool and retry | `mv POLICY.prev POLICY` (or fix the file), then `rag extraction validate` | `"valid": true`. Nothing was lost: a refused admission consumes no cursor; the next hook run or client retry admits the window | Already admitted work is unaffected; it never reads the file again |
| C2 | You want to know which policy pending work will use | `rag extraction inspect --queued` on the database host (refused in client mode) | Per job or window: `admitted` digest, or `legacy-builtin` for work admitted without metadata, and `bound` once an attempt started. Equal digests identify the policy used | A new admission with a different digest or bound project fails with `extraction_policy_conflict` in local `mining_queue.last_error`; no provider call, batch or cursor movement. Follow the conflict decision below |
| C3 | A job or window failed after admission (provider outage, crash, blocked authority) | Retry it as usual: the local worker retries automatically; a central owner uses `rag service job-retry RECEIPT` | The retry uses the admitted and bound policy, even if the file changed or is invalid meanwhile; a result that was already accepted is applied without a second provider call (rehearsed) | A malformed stored snapshot stops the job and moves no cursor (local job `last_error` `policy_snapshot_invalid`; central receipt state `error`, code `processing_failed`): keep the job, escalate |
| C4 | A domain was removed from a principal after admission | Nothing to do | The retry writes only domains that are both admitted and currently writable; with none left the window is blocked (`authorization_or_predecessor_blocked`) | Restore the authority and use C3 |
| C5 | Every category disabled on purpose | Nothing to do | Mining accepts an empty batch, makes no provider call and advances the cursor (`skipped: extraction disabled by policy`) | |

### Conflict decision (C2)

Keep the conflicting job and binding. Do not edit snapshots, delete bindings,
advance cursors or replay the transcript under a new session ID. If the original
policy and project remain acceptable, restore that exact policy file and resume
the session in its original project. After the conflicting job exhausts its
normal retry budget, the next ordinary Stop/SessionEnd admission can finish the
original cursor under that binding. This path is covered by the queue regression
test. Only subsequent cursors can use the changed policy. The old conflict job
remains an error for inspection. If the original policy is no longer authorized,
leave the work stopped and escalate; this release provides no rebind command.
A direct retry in another project also reports extraction_policy_conflict. A
validly hashed admitted snapshot naming the wrong project instead reports
policy_snapshot_invalid. Neither case is repaired by changing the current file
for an already admitted job.

### Integrity check

Run after A8 and whenever binding counts look wrong. The check only reads.
Connect with the database owner's `psql` session to the store and run:

```sql
-- PB067-INTEGRITY
SELECT
  (SELECT count(*) FROM extraction_policy_bindings) AS bindings,
  (SELECT count(*) FROM extraction_policy_bindings
    WHERE digest !~ '^xb1:[0-9a-f]{64}$') AS malformed_digests,
  (SELECT count(*) FROM extraction_policy_bindings) - (SELECT count(*) FROM audit_log
    WHERE op = 'extraction_policy_bind') AS bindings_minus_audit,
  (SELECT count(*) FROM mining_batches b JOIN extraction_policy_bindings p
    ON p.session_id = b.session_id AND p.input_cursor = b.input_cursor
    WHERE b.extraction ? '_policy' AND b.extraction->'_policy'->>'digest' <> p.digest) AS batch_policy_mismatch;
```

Expected: every column except `bindings` is 0. Any other value: stop activating
policies, keep the output and escalate. `bindings_minus_audit` assumes the
`audit_log` has not been pruned; a negative value is not an error.

## Part D: rollback, interruption and restore

**Policy rollback (prospective).** Put the previous valid file back
(`mv POLICY.prev POLICY`), or remove `[mining] policy_file` to return to builtin
rules. Only new admissions change. Admitted and accepted work keeps its policy,
nothing already stored is rewritten or filtered again, and nothing is re-mined.
There is no command that re-mines history; that would need a separate,
explicitly authorized run.

**Interrupted upgrade.** `to_regclass('public.extraction_policy_bindings')` is
null and `schema_migrations` lacks `032_extraction_policy.sql`: nothing
committed; repeat A4 with a new dump name. Both present: the upgrade committed;
run A5. A mixed state is a blocker.

**Return to 0.6.19 code without restoring.** Ordinary 0.6.19 reads, `get`,
evidence history and writes work on schema032, also with bindings present
(rehearsed). 0.6.19 mining ignores captured policies (B1). Before you switch:

1. Remove `[mining] policy_file` on every host and wait until
   `rag extraction inspect --queued` lists no job or window with an `xb1:`
   `admitted` digest that is still pending; or accept in writing that those will
   be mined by 0.6.19 with builtin rules.
2. Stop the processes on the list, point them at the 0.6.19 code, restart them.

**Restore a backup taken after the upgrade.** Make one with
`rag service --config CONFIG verified-backup --source-version 0.6.20 --output DIR/current.dump`.
The label records the actual0.6.20 release and the dump includes the bindings.
Then follow PB-063 R1–R3 with these substitutions: both executables are0.6.20,
the label is `--source-version 0.6.20`, and the dump is `DIR/current.dump`. Bindings and
their immutability trigger come back with the restore (rehearsed); run the
integrity check on the restored store. The policy file is not in the database:
back it up with your configuration.

**Restore the pre-upgrade state** discards every write after the A4 backup,
including all bindings and every memory mined since. Obtain authorization for
that recovery point, keep the upgraded store intact and export the post-backup
writes first:

```sql
SELECT at, actor, op, document_id FROM audit_log WHERE at > '<A4 time>' ORDER BY at;
```

Then follow PB-063 R1–R4 with these substitutions: `RAG016` is the 0.6.20
executable, `RAG015` the 0.6.19 executable, the label is `--source-version
0.6.19`, and the dump is `DIR/policy032.dump`. A 0.6.20 service refuses the
restored schema031 with `incompatible_service_schema`. There is no schema
downgrade.

## Escalation and preserved evidence

Escalate to the maintainer when A1, A2 or A4 report an unsupported store or a
preservation mismatch, when B1 finds an unknown direct client, when C2 reports an unresolved
`extraction_policy_conflict`, when C3 reports `policy_snapshot_invalid` or when the integrity check is not clean. Keep, without
secrets: the process list, the B1 outputs, the inventory, preflight and A4/A5
output, the dump and its manifest, each validated policy identity with the file
and the integrity result. Do not attach dumps, policy files with internal
guidance or memory texts to public issues.

## Completion

Part A is complete when A4 and A5 succeeded, A6 shows no error, all processes on
the list run 0.6.20 and the integrity check is clean. Part B is complete when B1
passed on every listed host, B5 shows the validated identity, C2 reports no
unresolved conflict, and the next mined batch names its admitted policy
(`rag extraction inspect --queued` or the batch's
`_policy` digest). Keep the verified pre-upgrade dump until you decide never to
return to the pre-upgrade state.

## Maintenance and sources

Reassess when a migration follows 032, when `rag extraction` or the operator
commands change, when the process types that admit or run mining change, or when
the policy file version changes. Sources: `agentic_rag/extraction_policy.py`,
`agentic_rag/extraction_cli.py`, `agentic_rag/mining.py` (`bind_policy`,
`prepare_extraction`), `agentic_rag/jobs.py`, `agentic_rag/service/ingest.py`,
`agentic_rag/service/upgrade.py` (`SUPPORTED_VERSIONS` covers 0.6.0–0.6.20),
`sql/032_extraction_policy.sql` and [PB-063](rag-063-source-evidence-upgrade.md).

Change history: 2026-11-01 drafted with the RAG-067 implementation.
