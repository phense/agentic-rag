# PB-063-UPGRADE: Upgrade a populated 0.6.15 store to source evidence (schema029)

## Identity and scope

- Class: system.
- Origin: RAG-063 FR-005, US-004 and AC-008/009 in
  [the specification](../../specs/6-5-source-evidence/spec.md); task T063-009.
- Audience and owner: the operator of a local or central agentic-rag database.
  The maintainer owns production authorization.
- Target: package 0.6.16, migration `029_source_evidence.sql`, upgrading a
  populated 0.6.15 installation at schema028 (`main` at `5390a6f`). Other
  supported 0.6.x sources take the same path and apply every pending migration.
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
| U4 | Operator, store | Authority: approved maintenance window. Impact: brief read-only fence for returning old writers. Run `rag service --config CONFIG upgrade --source-version 0.6.15 --dump DIR/evidence029.dump --apply --writers-stopped` | `"migrations_applied": ["029_source_evidence.sql"]` (plus earlier pending files for older sources), `"restore_verified": true`, `"original_rows_unchanged": true`, and `DIR/evidence029.dump.manifest.json` | Any error: the migration transaction rolled back; go to *Interruption* below |
| U5 | Operator, store | Repeat U4 with a new dump name, for example `DIR/evidence029-retry.dump` | `"migrations_applied": []`, `"restore_verified": true` | A non-empty list means U4 did not commit; compare with the manifest before continuing |
| U6 | Operator, store | `rag service --config CONFIG status` | Status JSON without error | Error: keep writers stopped; escalate with the output |
| U7 | Operator, clients | Restart every writer, MCP server and the central service on 0.6.16 | The service starts. (A 0.6.16 service started before U4 refuses with `incompatible_service_schema`.) | Startup refusal after U4 succeeded: check that the service points at the upgraded store |
| U8 | Operator, one memory | With the normal client configuration run `rag evidence show <slug> --json` on a known memory | `"contract_version": 1`; existing claims show source and claim `revision` 1; history pages say `pre_upgrade_history: not_captured` | `migration029_required` or an error: the client still points at an un-upgraded store |

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
(rehearsed), so a code rollback alone needs no database change. To return the
data to its pre-upgrade state, restore `DIR/evidence029.dump` into an empty
database with the database owner, then verify it against its manifest:

```sh
pg_restore --no-owner --single-transaction --exit-on-error -d <empty-target> DIR/evidence029.dump
```

Restoring the pre-upgrade dump discards every write made after the backup,
including new reviews, source decisions and their history. Prefer recovering
forward: take `rag service --config CONFIG verified-backup --source-version 0.6.15
--output DIR/current.dump` of the upgraded store and keep it.

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
