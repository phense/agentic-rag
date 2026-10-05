# Atomic facts and valid-time retrieval

`rag assert` and MCP `memory_assert` save one immutable entity/attribute/value
assertion with source evidence. Use an explicit known project (or global scope),
a timezone-aware event time, and evidence containing source_id, role and quote.
A manual write is the caller's source attestation; it is not independent source
verification. Never invent a user quote or label an assistant suggestion as a user fact.

`relation=assertion` introduces a value. `replacement` explicitly replaces older
values of exactly the same project/domain/entity/attribute from its event time onward.
`extension` adds information without replacing prior values. A later import of an
older event fits its historical position. Expiry is exclusive; expired replacements
do not resurrect the old value. Equal-time conflicting values and uncertain evidence
remain in `rag review` and history without archiving accepted facts.

Search defaults to current eligibility. `rag search QUERY --as-of TIMESTAMP` selects
known assertions valid at that time; `--history` exposes every temporal disposition.
MCP search/neighbors/path accept `as_of` and `history` (mutually exclusive). Get shows
full assertion evidence, timeline retains typed edges. This is valid-time history,
not a reconstruction of arbitrary past document edits or what was known at ingestion.

Legacy documents retain their status semantics. No migration invents times, splits
legacy paragraphs, or alters pins. Atomic assertions cannot be edited in place or
moved to another project; create a corrective assertion. Ordinary curation excludes
them. Reactivating an ordinary archived/refuted document establishes a fresh evidence
epoch: old contradiction edges do not trigger refutation again, but new edges can.

Unselected graph browsing preserves its historical default; pass a project or an
explicit `history=false` for current traversal.

Mining adds atomic assertions to its existing structured call. Each lossless window
contains at most 64 nonempty source fragments to bound metadata overhead. It binds quotes to
consumed source fragments, derives role and source time from the transcript, and
requires complete, untruncated source prose and conservative whole-fragment EN/DE declarations such as `server port is now
8000` for automatic acceptance, and persists normalized evidence in the accepted batch before applying effects. Questions, proposals, historical narrative, uncertain
or assistant-sourced assertions are review-only. Matching is bounded by explicit
project/domain/entity/attribute; more than 50 candidates requires review. Entity alias resolution
and comprehensive legacy claim evidence remain separate work in issue #7.

Deployment requires a fresh verified database backup and the worker lock before
migration011/code activation. No legacy content rewrite is required. Restart long-lived
MCP servers for additive tool parameters. Old workers do not enforce validity: use a
forward fix or a controlled restore of the predeployment backup for rollback.

Distinct source attestations of a duplicate fact are appended idempotently to
`assertion_sources` and audited; the canonical assertion is not duplicated.

## Domain boundaries in 0.6.5

Atomic assertion comparison and deduplication use exact project scope, domain,
entity and attribute. Equal values and event times in `general` and `programming`
produce separate originals and source attachments. Equal-time conflicts are
reviewed only within that boundary. Current/as-of SQL selection and entity
resolution retain each domain's own replacements and expiry behavior.

Migration020 replaces `assertion_eligible` with the same signature and privileges;
it changes no stored rows. Existing cross-domain `supersedes`/`extends` edges and
source attachments remain historical evidence. Previously collapsed duplicates
cannot always be attributed to their requested domain because source evidence
may not contain that domain. The upgrade does not infer a missing assertion,
change a review disposition or detach any historical source.

The local command `uv run python scripts/diagnose_domain_assertions.py` uses
`rag_reader` and a read-only snapshot to report only the aggregate count of
cross-domain assertion edges. It prints no entity keys, IDs, quotes or bodies.
Use `AGENTIC_RAG_CONFIG` to select a representative owned copy or the intended
read-only source. Diagnosis does not authorize repair: any later correction
requires reviewed source evidence and an audited `rag assert`/`memory_assert` write.

### Existing-installation upgrade and recovery

Supported source schemas are 018 and 019; the target is 020 at version 0.6.5. An 018
source also applies additive019 before020. The measured source gateway is pinned
in `tests/fixtures/domain_assertions_source_019.py` from revision `9071693`.
Full row fingerprints, role grants, pins, checkpoints, queue, original assertions,
claim/source attachments and existing cross-domain graph/audit history are preserved
in the [owned upgrade rehearsals](verification/domain-assertions.md).

Production adoption requires separate approval. Use this order after approval:

1. Retain the source checkout, environment, launcher configuration and an owned
   backup destination. Quiesce every writer: wait for active mining batches,
   hooks and CLI writes to finish; hold the existing worker lock at
   `~/.agentic-rag/state/worker.lock` for the migration and caller cutover.
2. Capture a strict same-snapshot backup with the existing
   `scripts.verify_contextual_indexing.verified_backup` helper. It exports a
   read-only source snapshot, restores to a marker-owned fresh database with
   `--single-transaction --exit-on-error`, and compares all source table rows
   plus application-role privileges. Retain its dump, checksum and inventory
   privately. The ordinary maintenance smoke report does not prove full fidelity.
3. From the approved permanent candidate checkout and configuration, run
   `uv run rag init-db` as the database owner. It applies pending migrations
   transactionally;020 uses `CREATE OR REPLACE FUNCTION`, keeping ownership,
   existing execute privileges and function signature. Repeating the command
   after interruption is safe. An aborted transaction leaves the old function.
4. Switch only RAG-owned launcher executable fields to the approved environment,
   reconnect every writable MCP session and ensure old workers/hooks have exited.
   Check both MCP privilege levels and perform the domain scenarios on the owned
   copy. Existing old readers use the corrected shared SQL function; old writers
   retain the domain-free gateway and must not resume alongside new writers.
5. Compare the retained source inventory and grants with the upgraded store,
   allowing only recorded migration-ledger additions and 019's new cache table.
   Run the aggregate diagnosis, verify current/as-of/history domain reads and
   release the worker lock only after all writable callers use 0.6.5.

Recovery before resuming writes can keep020 and restore source code for read-only
access while repairing the candidate or launcher bindings. All writers remain
paused: source code reintroduces the domain-free comparison and a different lock
key, so a mixed old/new writer fleet is unsupported. Readers require no outage
for the function replacement; the writer cutover requires a maintenance window.
Prefer a forward code fix. Restoring a pre-upgrade dump is a separate confirmed
recovery into an owned target first; it loses writes after the captured snapshot
if deliberately used to replace production. No automatic schema downgrade or
historical repair is included.

Concurrent same-title assertions can allocate the same global slug. The gateway
now retries only `documents_slug_key` violations up to three attempts, inside
savepoints, without committing or rolling back the caller's outer batch. Slugs
and existing document identifiers keep their previous format. Sustained conflict
beyond that bound remains a visible failed write with no partial assertion.
