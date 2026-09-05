# Atomic facts and valid-time retrieval

`rag assert` and MCP `memory_assert` save one immutable entity/attribute/value
assertion with source evidence. Use an explicit known project (or global scope),
a timezone-aware event time, and evidence containing source_id, role and quote.
A manual write is the caller's source attestation; it is not independent source
verification. Never invent a user quote or label an assistant suggestion as a user fact.

`relation=assertion` introduces a value. `replacement` explicitly replaces older
values of exactly the same scoped entity/attribute from its event time onward.
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
scope/entity/attribute; more than 50 candidates requires review. Entity alias resolution
and comprehensive legacy claim evidence remain separate work in issue #7.

Deployment requires a fresh verified database backup and the worker lock before
migration011/code activation. No legacy content rewrite is required. Restart long-lived
MCP servers for additive tool parameters. Old workers do not enforce validity: use a
forward fix or a controlled restore of the predeployment backup for rollback.

Distinct source attestations of a duplicate fact are appended idempotently to
`assertion_sources` and audited; the canonical assertion is not duplicated.
