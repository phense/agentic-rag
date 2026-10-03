# Implementation Plan: Evidence-backed entity identities and scoped aliases

## Stable work ID

RAG-5.8, [spec](spec.md), source2a29c50, ignored worktree
`.worktrees/entity-identities`, branch `feature/entity-identities`.
Repository `.engineering-method` and `scripts/project-state` were verified absent.
Git, Issue33 and these artifacts hold continuity; no installed state wrapper is used
and no framework event ledger is claimed.

## Summary and technical context

Python3.13/PostgreSQL17/pgvector. Add018 tables for exact scoped/domain identities,
assertion attachments and directed alias→anchor relations. Preserve original rows. Existing assertion/mining writers stay byte-identical.
UUID identity derives deterministically from exact scope/domain/name; unknown facts
are counted unresolved. Relation evidence is an immutable claim saved by the existing
store gateway, plus an audited relation state. Confirmation is explicit, requires
active complete user support and both names in the quote, and rechecks competing
anchors/cycles under a scope/domain advisory lock. No identity union or transitive
traversal. Explicit backfill persists exact attachments; reads derive the same UUID
for unindexed old/new assertions without writing. No per-call lock is added to
existing multi-assertion transactions. Backfill runs take a dedicated batch lock and use scope/domain locks for
attachments; existing assertion/mining transactions acquire no new locks. Alias
confirmation takes one scope/domain lock before identity/source locks. An anchor may have several direct aliases; aliases cannot also be anchors.

## Project gates

| Gate | Evidence / action | Result |
| --- | --- | --- |
| One store and audited writes | store.py gateways; existing role matrix | preserve |
| Supported existing source | clean2a29c50 and live001–017 inventoried read-only | confirmed |
| Client/config/jobs compatibility | additive tools/tables only, unchanged source contracts | passed with old/new processes |
| Review and evidence | complete independent reviewers and isolated driver | passed; final artifact review before PR |
| Merge and rollout | specific PR approval; separate operational authorization | pending, no live mutation |

## Compatibility boundaries and interfaces

Legacy validity/search/graph functions are unchanged; cross-name selection is an
explicit new entity evidence API. Existing source writes remain unchanged on017/018; explicit backfill indexes their original rows.
Old clients writing after018 are visible through exact name/scope/domain matching,
with missing-index warnings until an audited backfill. Reads use one SQL snapshot,
rollback-safe savepoints and bounded timeouts, fallback on optional index failure.
No new provider calls, installs, hooks or queue kinds. Source/new/source clients
can read017/018 without deployment or service interruption. Retain018 on code rollback.

## Implementation structure and dependencies

- `sql/018_entity_identities.sql`: additive tables and reader/writer/admin grants.
- `agentic_rag/entities.py`: validation, stable IDs, audited gateway internals,
  review and bounded reads. `store.py`: public write gateways; existing validity.py is unchanged.
- `cli.py`, `mcp_server.py`: additive entity/alias contracts; main-only mutation.
- `tests/test_entities.py`: behavior, trust, history, ambiguity, boundaries,
  transactions, concurrency, malformed inputs and missing schema.
- `scripts/verify_entity_identities.py`: populated source seeding, strict backup/
  restore and retry, old/new subprocess clients, paired measurements and read-only
  Trading controls. Reuse owned database and strict snapshot helpers.

## Tests and architecture findings

AF-001: Do not alter assertion_eligible globally: legacy exact-text status semantics
remain compatible. Entity reads calculate cross-name replacement as a disposable
selection, not a rewritten edge/fact. AF-002: Shared roles expose all rows; project
and domain constrain selection, never purport to be new ACLs. AF-003: Trust and
alias state must share the read statement snapshot so withdrawal is immediately
visible. AF-004: Mapping derives current scope/domain/name under a document share lock;
domain repair can move original documents, so readers reject stale attachments.
Existing writers keep all locks/effects unchanged; alias source and batch locks
never interact with a new assertion identity lock. AF-005: relation confirmation locks
scope/domain, avoiding deadlocks and racing competing anchors. AF-006: Distinct
current values without explicit replacement, and equal-time conflicts, produce
review warnings rather than an invented canonical answer.

## Supporting artifacts and playbook obligations

Architecture and tasks are local artifacts. PB-5.8 is required before handoff;
read-only independent playbook review plus executed isolated upgrade/recovery driver.
Executed evidence is recorded in [verification](../../verification/entity-identities.md).
No separate development playbook is needed: owned database helpers already constrain
fault injection/cleanup, and no production operational task is authorized.
