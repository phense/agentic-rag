---
id: PB07301
title: Select originals with typed metadata filters
type: task
doc_id: standalone-metadata-filters
readers: [operators, client-authors]
status: reviewed
version: 0.6.30
depends_on: []
assets: []
last_reviewed: 2026-11-04
summary: Register application fields, filter authorized originals, and recover an existing installation.
---

# PB07301: Select originals with typed metadata filters

## Identity and scope

- Class: system operation, including an existing-installation upgrade.
- Origin: [Issue73](https://github.com/phense/agentic-rag/issues/73),
  [requirements](specs/RAG-073-typed-metadata-filters/spec.md).
- Audience: operators configure fields; client authors submit filters.
  The repository maintainer owns adoption and recovery decisions.
- Target: 0.6.30/schema039, upgrading 0.6.29/schema038.
- Readiness deadline: before adopting typed requests on an existing store.
- Last edited: 2026-11-04.
- Status: content reviewed and normal paths rehearsed. Restricted-owner
  emergency recovery stops at an explicit DBA handoff; that emergency operation
  is not certified by the normal upgrade rehearsal.
  This document does not authorize a production change.

## Goal

Retrieve only originals matching an explicit metadata condition while retaining
the current domain, project, access, source and validity checks. Labels describe
an original; confirming a claim still requires the existing evidence workflow.

## Terms

| Term | Meaning |
|---|---|
| Registry | Operator configuration naming the allowed application fields and their types. |
| Application metadata | Registered labels stored alongside an original under `meta.application`. |
| Filter | Versioned JSON condition supplied with one read request. |
| Leaf | One field, operator and value in a filter. |
| Missing | The field is absent from the original. |
| Null | The field is present with JSON `null`. |
| Eligible original | An original passing the request's existing access, trust, time and lifecycle checks. |
| Independent restore | A backup restored into a separate database and checked there. |

## Before starting

Use a disposable store for the examples. The local, authenticated REST and MCP
rehearsal is recorded in [verification](verification/typed-metadata-filters.md).
Use the existing-installation steps only during the authorized maintenance window.

You need the intended `rag` executable, its configuration file, a writable
working directory for JSON inputs, and a domain/project you may access. An
operator must authorize registry changes and any service restart. The examples
use `general` and explicit global scope; replace the domain with an existing,
authorized domain if necessary. A client-mode configuration must point to a
0.6.30 server with the same registry.

For an upgrade, pause writers, retain the previous runtime and configuration,
and obtain verified source and target backups through the existing
[central-service upgrade procedure](13-central-service.md). Never initialize a
new database over the existing store. Deployment does not label old documents,
rewrite originals or regenerate vectors.

### Upgrade an existing store

Record the exact stop/start commands and prior running state for the selected
installation's API, workers, hooks, MCP processes and scheduled work. API reads
also write operational traces, so include the API in the maintenance pause.
Keep the old runtime available. Choose absolute local paths in Bash:

```sh
RAG=/absolute/path/to/0.6.30/.venv/bin/rag
CFG=/absolute/path/to/server.toml
DIR=/absolute/private/metadata-upgrade
umask 077
```

For a deployment owner without extension-creation rights, first prepare the
empty verification template documented under
[restore-verification privileges](15-dashboard.md#restore-verification-privileges).
It requires `vector` in `public` and the documented preload. Add
`--verification-template TEMPLATE` to `upgrade` and `verified-backup` below.
Do not add it to `inventory`.

1. Inspect the source with the new executable:

   ```sh
   "$RAG" service --config "$CFG" preflight --source-version 0.6.29
   ```

   Require `ready: true`, the intended database identity and schema038.
   Stop on a privilege, schema or identity mismatch.

2. Pause the recorded processes and upgrade with a new backup filename:

   ```sh
   mkdir -p "$DIR"
   "$RAG" service --config "$CFG" upgrade --source-version 0.6.29 \
     --dump "$DIR/pre-metadata.dump" --apply --writers-stopped
   ```

   Require `restore_verified: true`, `original_rows_unchanged: true` and
   `migrations_applied: ["039_metadata_filters.sql"]`. Preserve the dump and
   `pre-metadata.dump.manifest.json`. Existing files are refused, never
   overwritten. A retry after an already committed upgrade must report no new
   migrations; inspect the inventory before choosing a fresh backup path.

3. Inspect the target and independently verify its backup:

   ```sh
   "$RAG" service --config "$CFG" inventory --source-version 0.6.30 \
     --output "$DIR/post-metadata-inventory.json"
   "$RAG" service --config "$CFG" verified-backup --source-version 0.6.30 \
     --output "$DIR/with-metadata.dump"
   ```

   Require schema039 and `restore_verified: true`. Use the installation's
   existing allowed and denied read controls before resuming its recorded
   processes. Keep the registry unchanged until the following rehearsal passes.

If any step fails, keep the processes paused and preserve its diagnostics. For
an atomically rolled-back migration, inspect038 before a documented retry. If
the target preservation or restore check fails, choose a separate empty target
with the same database owner, locale and embedding identity; point a distinct
protected `RECOVERY_CFG` at it.

**Restricted deployment owner:** stop here and hand the retained dump, manifest,
source/target identities and diagnostics to the authorized DBA. `restore-target`
has no verification-template option: its plain restore requires rights to create
and own the vector extension and restore its comments. A prepared verification
template for `upgrade` or `verified-backup` does not make this recovery command
usable by that restricted owner. Keep the source processes paused. The DBA must
rehearse an ownership-preserving restore into the separate target and provide
original-row, ACL/owner/sequence and scoped-access verification before the
maintainer considers cutover. Do not change the operator's role privileges or
substitute a superuser-owned restore and assume preservation.

For an existing authorized owner with the required extension-creation and
ownership rights, verify the source dump and restore into that separate target:

```sh
"$RAG" service --config "$RECOVERY_CFG" restore-target \
  --dump "$DIR/pre-metadata.dump" \
  --manifest "$DIR/pre-metadata.dump.manifest.json" --apply
```

Require restored-original preservation and repeat the allowed/denied controls.
A failed restore leaves the source paused; preserve that target and escalate
to the maintainer. Do not reuse it with `--resume` unless its verified inventory
matches the retained manifest. Cutover to a recovery target is a separate
consequential decision; never restore over live knowledge.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
|---|---|---|---|---|
| M1 | Operator, selected configuration | Inspect version and filter schema. | `typed_metadata1`, supported fields and bounds. | Unsupported server: upgrade first; do not remove the filter to retry. |
| M2 | Operator, field registry | Declare only required fields and restart the affected runtime. | Schema inspection reports the declarations. | Invalid configuration: restore the previous file and runtime. |
| M3 | Writer, disposable originals | Save registered metadata through the ordinary gateway. | Returned original IDs and normal audit records. | Validation/audit failure: correct the input; no direct SQL repair. |
| M4 | Reader, original queries | Submit the same filter locally and centrally. | Matching authorized original references only. | Invalid/unsupported/budget error: use the recovery table below. |
| M5 | Operator, existing installation | Upgrade after independently verifying the source backup. | Only039 added; canonical originals and permissions preserved. | Keep writers paused and retain the source runtime and backup. |
| M6 | Maintainer, upgraded store | Verify the target backup and scoped reads before resuming writers. | Independent restore and positive/negative read controls pass. | Stop adoption; use the isolated recovery procedure. |

### Inspect the registry

1. Select the intended configuration in the shell:

   ```sh
   export AGENTIC_RAG_CONFIG=/absolute/path/to/config.toml
   ```

2. Inspect the available command with `rag metadata --help`.
3. Run `rag metadata schema` and retain its value-free result.

The result must report the supported field types, operators, registry and
bounds. Schema inspection does not enumerate stored labels or private values.
If the command or capability is absent, stop typed requests on this runtime.

### Register application fields

Changing a declaration can change which stored labels match. First rehearse the
change against a copy; keep the previous configuration for rollback. An empty
registry is valid and leaves canonical built-in fields available.

1. Back up the selected configuration to a distinct protected path.
2. Add these declarations to its TOML file:

   ```toml
   [metadata.fields]
   environment = "string"
   platform = "string"
   importance = "number"
   labels = "string[]"
   ```

3. Restart the selected local process or central service during its authorized
   maintenance window.
4. Run `rag metadata schema` again using the intended client configuration.

Expect `environment`, `platform`, `importance` and `labels` under
`application_fields`, with their declared types. Filter leaves refer to these
keys as `app.environment`, `app.platform`, `app.importance` and `app.labels`. If the service fails to start, restore the saved
configuration and start the previous runtime. Registry removal retains stored
values; it does not erase or adopt historical metadata.

### Save and query a disposable original

These steps write one original in the selected test store. Use a unique slug;
repeating a save with that slug updates the same original through the gateway.

1. Write `metadata.json` in the working directory:

   ```json
   {"environment":"production","platform":"linux","importance":3,"labels":["operations","storage"]}
   ```

2. Save the example:

   ```sh
   rag save --domain general --dtype memory --scope global --slug metadata-example-linux \
     --title 'Linux storage reference' --body 'Linux storage reference for the metadata example.' \
     --metadata-file metadata.json
   ```

3. Write `filter.json`:

   ```json
   {"version":1,"where":{"and":[
     {"field":"app.environment","op":"eq","value":"production"},
     {"field":"app.platform","op":"eq","value":"linux"},
     {"field":"app.importance","op":"gte","value":3},
     {"field":"updated_at","op":"gte","value":"2026-11-01T00:00:00Z"}
   ]}}
   ```

4. Query the example:

   ```sh
   rag search 'Linux storage reference' --domain general --scope global \
     --strategy lexical --filter-file filter.json --json
   ```

Inspect returned IDs and quotations. Choose the date boundary for the period you
intend to query. Other matching authorized originals may
also appear; a private or otherwise ineligible original must never appear.
Labels do not authorize access or make an unconfirmed claim eligible.

### Use the same filter from a client

1. Inspect the central server schema through its authenticated client
   configuration with `rag metadata schema`.
2. Run the same search and `filter.json` with that configuration.
3. Pass the same JSON object as optional `filter` to Python, MCP or REST tools;
   MCP schema inspection is `memory_filter_schema`.
4. Inspect warnings and original references when using context, research or a
   summary instead of a direct search.

Filtered derived results use matching originals. Unbound session text and
anonymous pins cannot contribute matching source references. A query embedding
may be reused, but the current access and metadata conditions still apply.
An older server must explicitly refuse supplied typed options.

## Filter reference

Each node has one logical key (`and`, `or`, `not`) or the three leaf keys
`field`, `op`, `value`. Logical groups must be nonempty. Fields are the inspected
built-ins or declared `app.NAME` fields. Unknown keys, duplicate JSON keys and
implicit type conversions are rejected.

| Intended condition | Leaf |
|---|---|
| Production or staging | `{"field":"app.environment","op":"in","value":["production","staging"]}` |
| Contains both labels | `{"field":"app.labels","op":"has_all","value":["operations","storage"]}` |
| Field is present, including null | `{"field":"app.environment","op":"exists","value":true}` |
| Field is explicitly null | `{"field":"app.environment","op":"is_null","value":true}` |
| Literal substring | `{"field":"slug","op":"contains","value":"100%"}` |

`ne` and `nin` require a present, nonnull, correctly typed value. They do not
select missing fields. `not` complements its child's boolean result inside the
eligible set, so `not(eq(...))` can select missing fields. Strings compare exact
Unicode text; `%`, `_` and `*` stay literal. Calendar dates and offset-aware
timestamps have different declared types. Boolean `false` is not numeric zero.

The inspected schema is the authority for the operator/type matrix and limits.
The contract bounds encoded filters to 16 KiB, depth 6, 32 leaves/64 nodes and
32 values per list. Membership and list-matching operands require 1–32 values;
a stored list may be empty. Scalar strings are at most 1024 UTF-8 bytes;
substring/prefix patterns are at most 256 bytes. A filtered statement keeps a
shorter caller deadline and has a finite maximum of 5 s. An explicit work bound can refuse a large
scope; narrowing the query is preferable to assuming an empty result is complete.

A filter cannot change which newer assertion supersedes an older one. If the
newer fact fails the metadata condition, the old fact remains superseded.
Graph traversal also requires matching endpoints and bridges.

## Interruption, recovery and rollback

| Observable result | Action and preserved evidence |
|---|---|
| Invalid filter or metadata | Retain the value-free error and schema version. Correct the field/type/operator; retry only after validation. |
| Unsupported server | Stop typed calls and upgrade the intended server, or deliberately return to the documented unfiltered workflow. Never silently strip a supplied filter. |
| Budget or timeout | Retain bounds and error code. Narrow the scope/condition and retry independently. Check the next ordinary read still works. |
| Save fails | Verify the original and audit state before retry. Do not insert metadata or repair audit rows directly. |
| Registry change breaks startup | Restore the saved configuration and previous runtime, then verify ordinary reads. Existing application values remain stored. |
| Upgrade interrupted | Keep writers paused; inspect the migration inventory and verified backup before the documented upgrade retry. |
| Post-upgrade or restore check fails | Keep writers paused. Preserve both backups, inventory and diagnostics; restore into a separate target and verify before an explicitly authorized cutover. |

For a code rollback, stop typed requests, restore the0.6.29 configuration and
runtime, and retain additive039 and stored application values. Verify an old
reader, writer and a negative access control before resuming. Removing a registry
entry or returning to old code does not delete labels. Do not roll back by
dropping039 or restoring an old dump over live knowledge.

## Check that it worked

Completion requires inspected declarations, audited saves, matching local and
central results, explicit refusal tests, and restored ordinary behavior after a
failed request. Existing-install adoption additionally requires preserved
originals and permissions plus independently restored source and target backups.
Record the exact runtime/configuration hashes and expected ID sets from the
rehearsal. A successful exit alone does not prove complete filtered retrieval.

## Maintenance and sources

Rehearse after changes to field declarations, filter grammar, candidate limits,
graph/research propagation, caches, eligibility, schema or client negotiation.
Review the actual plans before claiming an index accelerates a filter. Published
timings apply only to their recorded fixture and authority.

The [verification record](verification/typed-metadata-filters.md) names the
exact implementation, fixture, command, sample sizes and limits. The populated
0.6.29 upgrade was separately exercised with interruption, retry, old readers
and writer, and independently restored source and target backups, including a
non-superuser deployment owner. This supports the procedure; it does not certify
a particular production installation before its own preflight and verification.
