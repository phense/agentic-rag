# PB-5.4: Upgrade and operate contextual chunk indexing

## Identity and scope

- Class: system playbook; Feature 4, [Issue #29](https://github.com/phense/agentic-rag/issues/29).
- Origin: [RAG-5.4 specification](specs/RAG-5.4-contextual-indexing/spec.md), AC-002–007.
- Audience and owner: installation operator; maintainer owns rollout approval.
- Supported source: `499c656d7fcb1cf1d1938f7d2404b4043d9fb0b0`, migrations001–014, package0.5.0, PostgreSQL17/pgvector, Python3.13.
- Target: reviewed Feature 4 code (`feature/contextual-indexing`), additive migration015. The PR identifies the exact target commit; package version remains0.5.0.
- Readiness deadline: before merging; execution additionally requires installation-specific rollout authorization.
- Last edited: 2026-10-03.
- Review/rehearsal state: [evidence record](verification/contextual-indexing.md).

## When to use / when not to use

Use this procedure to add document subject, source headings, opening/section excerpts and an explicit project name to chunk retrieval. Context is deterministic, secret-stripped, at most768 characters and kept in a separate version1 representation. Date/unit information appears only when present in these source excerpts. No hosted generation or additional provider is involved.

Ordinary saves and queued embedding retries create lexical context in their existing audited transaction, with no additional embedding request. Existing documents acquire context through an explicit, bounded `rag save --index-context` operation. This does not rewrite their documents, raw chunks, original embeddings or citation identities.

Auto and lexical search fuse current contextual candidates with the original pool. `rag search QUERY --context off`, MCP `memory_search(...,context="off")`, forced `--strategy hybrid` and historical baseline searches retain previous candidate behavior. Exact identifiers and strong error symbols bypass contextual ranking. The reranker still sees only original source chunks.

Use `rag get SLUG` for complete source context: an indexing prefix is never returned as evidence. A returned original span might lack the subject/date appearing elsewhere in its document. Contextual ranking alone does not resolve that ambiguity.

Do not use this procedure for a model/dimension migration, incompatible schema versions, installing a new provider, or restoring historical state over a live upgraded database. Those operations need separate plans.

## Before starting

The commands below use the default local `agentic_rag` database. Replace that name and PostgreSQL connection options with the installation's verified settings when different. Use its absolute `rag` executable; do not create a second canonical database or change client credentials.

```sh
CONTEXT_CHECKOUT=/absolute/path/to/agentic-rag
CONTEXT_CANDIDATE=/absolute/path/to/reviewed/feature4-checkout
CONTEXT_RAG="$CONTEXT_CHECKOUT/.venv/bin/rag"
git -C "$CONTEXT_CHECKOUT" rev-parse HEAD
"$CONTEXT_RAG" status
psql -d agentic_rag -Atc 'SELECT filename FROM schema_migrations ORDER BY filename'
```

Expect the supported source and001–014 before deployment. Inventory the existing readers, writers, worker, hooks and queued jobs. Preserve current configuration, roles, domains, project scopes, pins, claims, checkpoints, raw knowledge and historical audits. No adapter installation, queue reset or scheduler change belongs to Feature 4.

## Decision paths and actions

| Step | Actor and target | Condition / action | Expected evidence | Failure / next step |
| --- | --- | --- | --- | --- |
| PB-001 | operator, existing installation | Confirm specific rollout authorization, source revision and schema; record target commit. | Source014, approved target, saved before-state inventory. | Stop on a different source/schema or absent rollout approval. |
| PB-002 | operator, backup store | Create and strictly verify the backup with the candidate helper before code/schema changes. | Successful dump and restore verification; canonical counts/history available. | Stop if backup or restore verification fails. |
| PB-003 | operator, code checkout | Deploy only the reviewed Feature 4 commit using the existing dependency environment. | Exact target commit recorded; old clients continue to operate; new code on014 uses baseline. | Revert code to supported source if preflight fails. |
| PB-004 | operator, canonical schema | Run additive migration with bounded lock/statement timeouts. | Only015 added; no canonical data backfill or existing object removal. | On timeout/error, stop and retry after the blocking transaction ends; no reset. |
| PB-005 | operator, clients | Reconnect selected MCP clients to load the new code; verify both privilege levels and scoped citations. | New and existing clients read one canonical store; read-only clients cannot index. | Use context-off or previous code and investigate; do not reinstall adapters. |
| PB-006 | operator, derived index | Execute bounded audited indexing, inspect progress, repeat until accepted. | Derived rows plus `index_context` audits; raw rows and original IDs unchanged. | Stop on warnings; handle model availability or a source/lock conflict before retry. |
| PB-007 | operator, acceptance | Compare practical scoped evidence and source identities; retain baseline controls. | Original citations valid, budgets respected, no scope/domain/time leak; counts/history preserved. | Keep Issue #29 open; revert code or disable context on affected calls. |

Create a private, new dump using the reviewed candidate helper before deploying it.
The helper reads the configured canonical source in a read-only exported snapshot;
its dump and complete inventories share that snapshot while source writers continue.
It restores into an empty, randomly named owned target, requires `pg_restore` exit0,
compares every public table/row (including migration metadata), checks the three
application roles' table privileges, and cleans up only its verified owned target.
It refuses to overwrite an existing dump. Set the two declared artifact paths to
private absolute locations and retain the resulting dump and JSON report:

```sh
PYTHONPATH="$CONTEXT_CANDIDATE" "$CONTEXT_CHECKOUT/.venv/bin/python" \
  "$CONTEXT_CANDIDATE/scripts/verify_contextual_indexing.py" \
  --verified-backup /private/unique/contextual-before.dump \
  --output /private/unique/contextual-backup-report.json
```

Require successful command exit, `strict_restore_exit_zero: true`,
`all_public_table_rows_match: true`, `application_table_privileges_match: true`,
`consistent_exported_snapshot: true`, and `owned_database_cleanup: "verified"` in
the report. Its `tables` inventory and dump SHA256 identify the checked backup.
Stop on any failed or absent field. A failed attempt leaves its dump for inspection;
retry with a new pathname. This exact helper is exercised on the populated014
rehearsal; no production restore or knowledge write is part of backup verification.

The existing `rag backup`/`rag maintenance --no-worker --verify-backup` path remains
available as a coarse smoke check. Maintenance always exits0, ignores restore exit
status and accepts a partial document-count threshold; it cannot replace the strict
gate above. Never infer complete preservation from its `ok` alone. Exclude private
content and credentials from public verification records.

Deploy code before invoking its migration; this order is safe because new code detects an absent015 and falls back. No dependency or service installation is required. Old processes may keep using their prior code until reconnect. Migration may briefly wait for active chunk writers; it does not require a planned service restart:

```sh
env PGOPTIONS='-c lock_timeout=5s -c statement_timeout=60s' "$CONTEXT_RAG" init-db
psql -d agentic_rag -Atc 'SELECT filename FROM schema_migrations ORDER BY filename'
```

Expect015 once; repeating `init-db` is a no-op for applied migrations. Confirm the installation's schema/data inventory after it completes. The operation is transactional; a failed statement leaves015 unapplied. Schedule a maintenance window only if active writer transactions repeatedly prevent the bounded migration.

Start with an existing document UUID or slug, then continue across pending documents:

```sh
"$CONTEXT_RAG" save --index-context DOCUMENT_UUID_OR_SLUG --index-limit 1
"$CONTEXT_RAG" save --index-context pending --index-limit 8
"$CONTEXT_RAG" search 'your scoped question' --project /absolute/project --context auto --json
"$CONTEXT_RAG" search 'your scoped question' --project /absolute/project --context off --json
```

Index selectors are explicit IDs/slugs or reserved `pending` (one document per call). Default chunk limit8, allowed1–32. When a document is selected, output JSON contains `doc_id`, `indexed_chunks`, `remaining_chunks`, `warnings`. `indexed_chunks` counts derived rows changed; `remaining_chunks` counts contextual vectors still needed for that document, including those unavailable because inference failed. `pending` with no remaining documents returns0/0, no warnings and no `doc_id`. A lexical-only representation does not mean contextual vector work is complete. Do not loop indefinitely when warnings persist.

Normal `save` still requires title/domain/type. An index-only save rejects document mutation options and requires the stored fields when called through the Python gateway. CLI resolves those fields itself. Reader roles cannot invoke the writer-only index function or its audit write; writers cannot update the side table directly. Only audited application gateways perform index writes.

## Interruption, recovery and rollback

Each index call commits one bounded batch plus audit atomically. A process interruption before commit leaves no partial batch; a completed batch remains. Repeating the same selector resumes missing work and becomes a no-op after completion. With `commit=False`, an application caller owns the outer transaction and must commit or roll back all effects together.

Inference happens before a `NOWAIT` document lock. A concurrent source/scope correction or held lock aborts safely; retry with current stored fields after the conflicting writer completes. Old writers cascade-remove context attached to their replaced raw chunks. New readers ignore stale source fingerprints. Contextual vectors require a verified model digest, checked across index and query inference; unavailable or changed identity leaves lexical/baseline retrieval usable. Model replacement is not a migration of the retained original vectors.

For a Feature 4 code rollback, restore the exact source checkout/environment and reconnect new clients. **Keep schema015 and all canonical rows.** Actual old reads/writes work with it; derived context becomes inert. Alternatively, context-off restores original candidate behavior for an individual new search. Do not delete chunks, reset queues, replay historical knowledge or restore a database simply to undo this feature.

For disaster recovery, preserve the upgraded installation and restore the verified dump into a **separate empty recovery database** first. A014 dump restored with `--clean` over015 fails because `chunk_contexts` references the old chunk primary key; this was observed in rehearsal. Do not work around it by dropping production objects. Choose and verify a fresh recovery target, then use the installation's PostgreSQL tools:

```sh
createdb CONTEXT_RECOVERY_TARGET
pg_restore --single-transaction -d CONTEXT_RECOVERY_TARGET /absolute/path/to/verified014.dump
psql -d CONTEXT_RECOVERY_TARGET -Atc 'SELECT filename FROM schema_migrations ORDER BY filename'
```

Verify full canonical rows, roles/access behavior, pins, claims/sources, checkpoints, queue and audit history against the backup inventory before considering a cutover. The automated isolated rehearsal compares every canonical table fingerprint and reapplies015 after recovery. Production connection switching and client/service interruption remain separate approved operations. A dump restores only its captured state: writes after its snapshot are not recovered unless an independently tested log/PITR mechanism exists. Keep the current store available for reconciliation; no zero-data-loss disaster-recovery claim is made.

## Escalation and preserved evidence

Stop on invalid citations, any access leak, a canonical-row difference during index-only work, incomplete backup verification, or repeated migration failure. Preserve source/target revisions, schema migration list, aggregate counts, fingerprints, sanitized error class, affected selector IDs in private operator records and the dump. Report the blocker in Issue #29 and to the maintainer before a production cutover.

## Completion

Completion requires an authorized deployed target,015 exactly once, both client privilege levels verified, accepted contextual coverage and original citation identities, retained before-state history and a tested recovery backup. Stop after code/PR readiness if rollout was not authorized. Keep Issue #29 open until its applicable rollout criteria have evidence.

## Maintenance and sources

Reassess when source/schema support, chunking, prefix version, query fusion, model identity, privilege grants or backup tools change. Sources: [gateway](../agentic_rag/store.py), [context builder](../agentic_rag/contextual.py), [015](../sql/015_contextual_chunks.sql), [CLI](../agentic_rag/cli.py), [measurement/rehearsal script](../scripts/verify_contextual_indexing.py), [numerical results](benchmarks/2026-10-03-contextual-indexing/README.md). Initial authoring2026-10-03.
