# PB-063-UPGRADE: Upgrade a populated 0.6.15 store to source evidence (schema029)

## Identity and scope

- Class: system.
- Origin: RAG-063 FR-005, US-004 and AC-008/009 in
  [the specification](../../specs/6-5-source-evidence/spec.md); task T063-009.
- Audience and owner: the operator of a local or central agentic-rag database.
  The maintainer owns production authorization.
- Target: package 0.6.16, migration `029_source_evidence.sql`, upgrading a
  populated 0.6.15 installation at schema028 (`main` at `5390a6f`). This playbook rehearses that source only; earlier
  operator-supported versions require their own compatibility rehearsal.
- Readiness deadline: reviewed and rehearsed before the RAG-063 pull request is
  handed off. Merging does not authorize a production migration.
- Last edited: 2026-10-31.
- Review and rehearsal evidence: [rag-063-source-evidence-upgrade-review.md](rag-063-source-evidence-upgrade-review.md).

## When to use / when not to use

Use this procedure to bring an existing 0.6.15 store to the evidence contract:
new tables for source and claim revisions and their decision history, and
triggers that keep them current. The migration adds objects only. It rewrites
no original row, field, grant or audit record, and it backfills no review.

Do not use it when:

- the store reports an unknown version or schema, or several stores need merging;
- writers cannot be stopped, or you have no approval for the maintenance window;
- the verified backup cannot be written to private storage with enough space.

The intended outcome: schema029 installed, every original row and permission
unchanged, a verified pre-upgrade dump kept, and all clients restarted on 0.6.16.

## Before starting

Inputs you choose:

- `CONFIG`: the operator configuration of the store, for example `/owned/source.toml`.
- `DIR`: a new private directory for upgrade proofs, for example `/owned/upgrade/rag063`.
- A dump name that does not exist yet. The framework never overwrites a proof.

Checks you can run before changing anything:

1. Confirm the code and the store. The checkout you run has
   `version = "0.6.16"` in `pyproject.toml`. On the store,
   `SELECT filename FROM schema_migrations ORDER BY 1` ends with
   `028_reranker_settings.sql`.
2. Confirm that `DIR` lies on storage with at least three times the database size
   free. The backup step checks this as well and stops when space is short.
3. List every writer: hooks, MCP servers, workers, timers and the central service.
   Note how to stop and restart each one.

An unknown store version is an unresolved fact. It blocks this procedure.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| U1 | Operator, store | Write a private inventory: `rag service --config CONFIG inventory --source-version 0.6.15 --identities --output DIR/inventory.json` | JSON with `"supported": true` | `unsupported_source_schema` or `unsupported_postgresql_version`: stop, escalate |
| U2 | Operator, store | Run the plan without changes: `rag service --config CONFIG preflight --source-version 0.6.15 --mode local` | `"ready": true`, no blockers | Blockers listed: resolve them first; do not continue |
| U3 | Operator, writers | Stop every writer from the list. Keep the stopped list with the proofs | No client connections except yours | `database_clients_still_active` or `worker_still_active` in U4: stop the named writer, then repeat U4 with a new dump name |
| U4 | Operator, store | Authority: approved maintenance window. Impact: brief read-only fence for returning old writers. Run `rag service --config CONFIG upgrade --source-version 0.6.15 --dump DIR/evidence029.dump --apply --writers-stopped` | `"migrations_applied": ["029_source_evidence.sql"]`, `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/evidence029.dump.manifest.json` | Any error: the migration transaction rolled back; go to *Interruption* below |
| U5 | Operator, store | Repeat U4 with a new dump name, for example `DIR/evidence029-retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means U4 did not commit; compare with the manifest before continuing |
| U6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Error: keep writers stopped; escalate with the output |
| U7 | Operator, clients | Restart every writer, MCP server and the central service on 0.6.16 | The service starts. (A 0.6.16 service started before U4 refuses with `incompatible_service_schema`.) | Startup refusal after U4 succeeded: check that the service points at the upgraded store |
| U8 | Operator, one memory | With the normal client configuration run `rag evidence show <slug> --json` on a known memory | `"contract_version": 1`; untouched existing claims show source and claim `revision` 1 (post-upgrade writes advance it); history pages say `pre_upgrade_history: not_captured` | `migration029_required` or an error: the client still points at an un-upgraded store |

Old 0.6.15 processes that keep running after U4 can still read and write. Their
writes still advance the new revisions, so any version a new client inspected
before such a write becomes stale. History records those writes as `direct`,
without an inspected version, and with the database login instead of the
gateway actor. Restart them in U7 so new writes carry the full actor and mode.

## Interruption, recovery and rollback

How to recognize the state after an interruption:

- `SELECT to_regclass('public.claim_history')` returns null and
  `schema_migrations` has no `029_source_evidence.sql`: nothing committed. The
  migration and its marker commit together. Clear a retained read-only database
  default only as described in the central-service guide (PB-058-01), then repeat
  U4 with a new dump name.
- The table exists and the marker is present: the upgrade committed. Run U5. It
  applies nothing and re-verifies a fresh backup.

There is no schema downgrade. 0.6.15 code keeps working against schema029
(rehearsed), so a code rollback alone needs no database change.

### Restore the pre-upgrade state

This branch discards every write made after the U4 backup, including reviews,
source decisions and history. Obtain authorization for that recovery point and
keep the upgraded database intact for forward recovery. Keep all writers from
U3 stopped throughout R1–R4, including automatic restarts and timers. A returning
client must not write to the old database while other clients use the restore.

Inputs for this branch:

- `RAG016`: absolute path to the retained 0.6.16 `rag` executable used for operator
  checks. It can inspect schema028 without starting the service or migrating it.
- `RAG015`: absolute path to the retained 0.6.15 `rag` executable used by restored
  clients and the service. Confirm its package metadata reports 0.6.15.
- `RESTORED_CONFIG`: a private copy of `CONFIG`. Preserve every setting and secret
  reference; change `[db].name` to a new, empty recovery database. Preserve
  `[db].host` when restoring on the same PostgreSQL server and keep the same
  PostgreSQL login environment/credential mechanism.
- `EMPTY_TARGET`: the connection string for that same empty database, using the
  original database owner and existing PostgreSQL roles. Supply passwords through
  the existing protected credential mechanism, never in command arguments.
- `DIR/restored-inventory.json`: a new output path. Never overwrite earlier proofs.

1. **R1, operator:** On the stopped upgraded store, keep a current verified dump
   if the database is readable:

   ```sh
   "$RAG016" service --config "$CONFIG" verified-backup --source-version 0.6.15 --output "$DIR/current.dump"
   ```

   Here `--source-version 0.6.15` is the operator's supported compatibility label,
   including for a schema029 store. It does not assert that the running package
   or schema is 0.6.15. A new `0.6.16` source label is unsupported by this release.
   Preserve the U4 dump and manifest on private storage. Check their digest before
   restoring; a mismatch stops recovery:

   ```sh
   python3 - "$DIR/evidence029.dump" "$DIR/evidence029.dump.manifest.json" <<'PYVERIFY'
   import hashlib, json, sys
   from pathlib import Path
   manifest = json.loads(Path(sys.argv[2]).read_text())
   with Path(sys.argv[1]).open('rb') as stream:
       digest = hashlib.file_digest(stream, 'sha256').hexdigest()
   if manifest.get('format') != 1 or digest != manifest.get('dump_sha256'):
       raise SystemExit('dump_digest_mismatch')
   print('dump_digest_verified')
   PYVERIFY
   ```

2. **R2, operator:** Confirm `EMPTY_TARGET` is empty and owned by the same owner
   as the U4 inventory. Restore once; if it fails, keep writers stopped and choose
   another empty target for retry. Existing PostgreSQL roles and custom object
   owners must already exist on the server.

   ```sh
   pg_restore --single-transaction --exit-on-error -d "$EMPTY_TARGET" "$DIR/evidence029.dump"
   "$RAG016" service --config "$RESTORED_CONFIG" inventory --source-version 0.6.15 --output "$DIR/restored-inventory.json"
   ```

3. **R3, operator:** Compare the restored inventory with the U4 manifest using
   public operator output. This checks every table's row count and SHA-256,
   grants, object owners, sequence positions and original migration timestamps.
   Database name/OID may differ because this is a separate database. The source
   and target owner, PostgreSQL major version, collation and vector version must
   match. Any mismatch stops the cutover:

   ```sh
   python3 - "$DIR/evidence029.dump.manifest.json" "$DIR/restored-inventory.json" <<'PYVERIFY'
   import json, sys
   from pathlib import Path
   expected, actual = [json.loads(Path(p).read_text()) for p in sys.argv[1:]]
   if actual.get('format') != 1 or actual.get('supported') is not True:
       raise SystemExit('unsupported_restore_inventory')
   for field in ('tables', 'grants', 'owners', 'sequences', 'migrations', 'migration_rows'):
       if actual.get(field) != expected[field]:
           raise SystemExit('restore_mismatch_' + field)
   for field in ('owner', 'collate', 'ctype', 'vector_version'):
       if actual['identity'][field] != expected['identity'][field]:
           raise SystemExit('restore_mismatch_' + field)
   if int(actual['identity']['server_version']) // 10000 != int(expected['identity']['server_version']) // 10000:
       raise SystemExit('restore_mismatch_postgresql_major')
   print('restore_manifest_verified')
   PYVERIFY
   ```

4. **R4, operator and client owners:** While writers remain stopped, select
   0.6.15 code and the restored configuration for every process in the U3 list.
   For local CLI, hooks and local MCP servers, set their launch environment to
   `AGENTIC_RAG_CONFIG=RESTORED_CONFIG` and use the 0.6.15 executable/interpreter.
   An interactive CLI check uses:

   ```sh
   AGENTIC_RAG_CONFIG="$RESTORED_CONFIG" "$RAG015" service status
   AGENTIC_RAG_CONFIG="$RESTORED_CONFIG" "$RAG015" get <known-slug> --json
   ```

   Expect `database.service_ready: true` and the original memory content. For
   a central deployment, set the API and worker launch configuration to
   `RESTORED_CONFIG` and the 0.6.15 executable/interpreter. Preserve their existing
   policy, token paths, endpoint, TLS and spool settings. Restart the API first
   with the recorded U3 service command, verify an authenticated read of that
   known memory, then start its worker and reconnect the remote clients. Their
   service URL and tokens stay the same when the endpoint stays the same.
   Restart local hooks/MCP processes with the updated launch environment. Confirm
   every process points to the recovery database before resuming timers.

Schema028 requires 0.6.15 service code: the 0.6.16 service refuses it with
`incompatible_service_schema`. Do not start the 0.6.16 service or run `upgrade`
on the recovery database during this branch. `restore-target` migrates forward
and is not the pre-upgrade restoration command.

Recovery completes when the digest and manifest checks passed, 0.6.15 reports
`service_ready: true`, the authenticated known-memory read succeeds, and every
listed client uses the recovery database. Keep the original upgraded store
fenced from writers until the recovery decision is accepted. A failed check
leaves all writers stopped; escalate with the private output.

## Escalation and preserved evidence

Escalate to the maintainer when U1, U2 or U4 report an unsupported store, a
preservation mismatch (`source_drift…`, `restore_mismatch…`) or a retained fence
you cannot explain. Keep, without secrets: the inventory, the preflight output,
the U4/U5 JSON, the dump and its `.manifest.json`, and the stopped-writer list.
Do not attach dumps or private inventories to public issues.

## Completion

The procedure is complete when U4 and U5 succeeded, U6 shows no error, all
clients run 0.6.16, and U8 returns contract version 1. Keep the verified dump
until the next verified backup exists. If any step stopped, writers stay stopped
until the maintainer decides the next action.

## Maintenance and sources

Reassess this playbook when a later migration follows 029, when the operator
commands or their JSON fields change, or when the evidence tables gain writers.
Sources: `agentic_rag/service/upgrade.py` (`local_upgrade`, `verified_backup`,
`SUPPORTED_VERSIONS` includes 0.6.15), `agentic_rag/service/operator.py`,
`sql/029_source_evidence.sql`, [claim evidence](../../claim-evidence.md) and the
[central-service guide](../../13-central-service.md).

Change history: 2026-10-31 drafted with the RAG-063 implementation.
