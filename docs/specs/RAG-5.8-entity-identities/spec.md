# Feature Specification: Evidence-backed entity identities and scoped aliases

## Stable work ID

- Feature ID: RAG-5.8 (backlog5.8, feature8/10).
- Status: Implementation authorized by the maintainer; merge and deployment require separate approval.
- Source: [Issue33](https://github.com/phense/agentic-rag/issues/33).

## User scenarios

### US-001: Alternate names of one service (P1)

An operator records original assertions under two names and explicitly confirms a
source-backed alias. An entity query returns eligible facts under both names with
original citations and stable identity IDs. Revoking the link restores separate reads.

### US-002: Historical rename followed by current status (P1)

A current question under the old name finds the explicit replacement under the new
name. An as-of query before the rename returns the earlier fact. History preserves
both original assertions and never changes the legacy entity/attribute strings.

### US-003: Identical names in independent projects (P1)

Two operators use the same host name in different projects or topic domains.
Resolution never traverses another project's or domain's relation. This installation
has shared database roles, not per-user row ACLs; actor attribution is not access control.

## Acceptance criteria

- AC-001: Stable exact-name identities and their assertion attachments are additive;
  every legacy row, key, source, pin, audit, checkpoint and queued job survives.
- AC-002: Aliases require explicit operator confirmation and active complete user
  evidence containing both names. Unconfirmed/ambiguous suggestions remain inspectable.
  No embedding or provider participates in identity linking.
- AC-003: Resolution binds one exact known project scope and one domain. Explicit
  global resolution is separate. Unknown applicability is unresolved, never merged.
- AC-004: Revocation and source withdrawal immediately remove alias expansion;
  source evidence and historical facts remain inspectable. No transitive merge.
- AC-005: Current resolution respects explicit replacements across accepted aliases,
  event time, expiry, source trust and disposition. Conflicts are disclosed and withheld
  from the answer context. History is a currently trusted historical view.
- AC-006: Rehearse populated017→018 with strict backup/restore, interrupted DDL,
  interrupted bounded backfill, retry/no-op, concurrent clients and source/new/source
  CLI/MCP. Old writes during rollout remain readable without background rewrites.
- AC-007: All new index/relation writes pass audited store gateways with atomic
  caller-owned transactions; read-only MCP cannot write and DB grants enforce it.
- AC-008: Publish three paired controlled examples, identical selectors/budgets,
  original citations, literal quality denominators, first/warm times and raw samples.
  Trading remains read-only; private data never enters public artifacts/provider calls.

## Functional requirements

FR-001: Read entity evidence independently of legacy search, which preserves its
contracts. FR-002: Expose additive CLI/MCP read and main-only write tools.
FR-003: Bound result/context/link/backfill work and disclose truncation/fallback.
FR-004: Keep mistaken links reversible with reasoned audit history.

## Compatibility boundaries

Supported source: 2a29c50a2fa435d2caeb3354da9dbce92e85e6bb, schema001–017,
package0.5.0. No config, hooks, scheduler, provider, embedding or dependency change.
Old/new clients share the same store; unindexed old/new assertions derive stable
IDs without a read-side write until explicit audited backfill persists attachments; original exact-key validity/search remain.
Code rollback retains018 and original knowledge. Full restore may lose later writes
and is a separately authorized operation. Production rollout is outside this request.

## Interface contracts

| Contract | Inputs | Outputs / constraints |
| --- | --- | --- |
| Entity read | exact name, required domain, project or explicit global, optional attribute/as-of/history, context budget | stable IDs, original citations, accepted relations, review suggestions, bounded context, warnings |
| Alias save | canonical target name, alternate name, domain/scope, source evidence, effective time, optional confirmation | immutable evidence document, accepted/review relation; reason; duplicate/no-op |
| Alias review | relation evidence document ID, accepted/revoked state, reason | audited state transition after boundary/support/conflict recheck |
| Backfill | batch limit | mapped/unresolved counts, remaining work; safely repeat until done |

## Edge cases

Missing018 leaves legacy reads/writes working. Empty/oversized/NUL names, missing
scope/domain, invalid timestamps and budgets fail before writes. Global/project,
unknown and domain bridges cannot be linked. Alias cycles, competing anchors and
transitive chains require review. Expired replacement never revives an older fact.
Alias writes/reviews serialize per scope/domain; explicit backfill runs serialize
with each other. Existing assertion/mining transactions acquire no new locks. No unbounded output is implied.

## Assumptions and unresolved decisions

Manual confirmation is an operator attestation, not independent verification of a
quote's truth. Existing claim trust is reused; no new per-user ACL is claimed.

## Success measures

SC-001: Hand-labeled eligible facts in each controlled scenario are recovered with
zero foreign facts and valid original citations. SC-002: Protected table fingerprints
and old privileges match after rehearsal; repeat backfill produces no new audit.
SC-003: Full Python/Node suites and independent complete diff reviews pass.

## Playbook obligations

PB-5.8, system deliverable `docs/playbooks/entity-identities.md`: operator alias
review/revocation, supported upgrade and recovery, with executed isolated rehearsal.
