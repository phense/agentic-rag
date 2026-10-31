# Feature Specification: Consistent source evidence and review state

## Stable work ID

- Feature ID: `6.5`; work ID: `RAG-063`; GitHub Issue: #63; roadmap #58 step 5/15.
- Artifact path: `docs/specs/6-5-source-evidence/spec.md`
- Status: Accepted for implementation under the maintainer's end-to-end authorization.
- Source request: expose the existing original-evidence and review model consistently in REST, MCP, CLI and the dashboard, preserving all existing production knowledge.

## User scenarios

### US-001: Inspect the actual support for a memory (Priority: P1)

A reader can inspect original sanitized quotes, stable source/span references, source event time, speaker role, completeness and stated/inferred kind. Source trust, claim review, document lifecycle and temporal fact validity remain distinct. Legacy unknown provenance is explicitly unknown. An operator attestation does not become independent verification.

Independent test: the same synthetic memory yields the same versioned evidence representation through local and central clients, with byte-identical stored quotes and no invented historical provenance.

### US-002: Review the evidence that was actually inspected (Priority: P1)

An authorized operator can review a claim or withdraw/reinstate a source, give a reason, and inspect the resulting history. A concurrent source/attachment/review change must reject a stale new-contract action without partial state or audit changes.

Independent test: inspect, attach another span or withdraw/reinstate a source, then attempt an old-version confirmation; it fails and a fresh inspection permits a new audited decision.

### US-003: Understand why a result is unavailable (Priority: P1)

Readers see pending/reviewed/withdrawn/unsupported and explicit exclusion reasons derived from the existing eligibility rules. Withdrawn, expired, superseded or inaccessible evidence cannot remain accepted through derived views, caches or generated patterns.

Independent test: loss of the last source removes the current result and its derived acceptance; authorized history retains the original evidence. Superseded values do not resurrect.

### US-004: Upgrade a populated installation safely (Priority: P1)

Operators can migrate the currently deployed 0.6.15/schema028 installation, preserving original rows, accounts, grants, quotes, reviews, checkpoints and audit history; interruption and restore paths are tested on isolated copies.

## Acceptance criteria

- AC-001 — Each client exposes contract version 1, opaque stable source/span identity, a review version, exact bounded quote, source event time or explicit unknown, role, completeness, kind, source trust, claim review, fact lifecycle and exclusion reasons.
- AC-002 — Partial/truncated support, assistant paraphrase, manual attestation and legacy provenance never imply independent verification. Existing SQL eligibility remains authoritative.
- AC-003 — New-contract review and source-state actions require an inspected version. A stale version, including an active→withdrawn→active cycle, causes a conflict with zero state/history/audit changes.
- AC-004 — Successful decisions atomically retain actor, time, reason, resulting state and the inspected evidence version; failed transactions leave none. Existing historical audits remain intact and are not fabricated into new events.
- AC-005 — Every source/history access is anchored to a readable document and current authority. Guessed IDs, foreign attachments, counts, pagination and error messages disclose no inaccessible data. Source-wide writes retain the existing all-dependent-document write rule. Read-only clients cannot mutate.
- AC-006 — Original evidence is inspectable through finite pages and stable cross-VM references. Technical host-local file locators are not exposed as source navigation. Paths within original quoted knowledge remain original content.
- AC-007 — Withdrawal/correction, expiry, supersession and access revocation invalidate dependent acceptance before limits and graph hops; existing summary/profile/pattern paths are checked with real components rather than assuming the contract fixes them.
- AC-008 — A representative populated source-version rehearsal proves backup restoration, preservation of all original fields, idempotent migration retry, old-client reads and explicit rollback limits.
- AC-009 — Existing local and central CLI/MCP/REST contracts remain callable. Additive strict/versioned operations are used by the new dashboard; legacy writers' changes still invalidate new tokens and are auditable.

## Functional requirements

- FR-001: Produce one inspectable evidence contract from the existing source/claim/assertion registry, not a second truth store.
- FR-002: Separate lifecycle, review, trust, completeness and verification origin; explain exclusion without weakening validity.
- FR-003: Provide bounded authorized evidence and history drilldown across all four clients.
- FR-004: Bind review decisions to inspected evidence with atomic concurrency and audit handling.
- FR-005: Preserve production state and provide a verified upgrade and recovery procedure.

## Compatibility boundaries

- Source: 0.6.15/schema028; target patch: 0.6.16; additive metadata only where needed. No global rereview, source rewriting or synthetic verification.
- Preserve legacy tool names/required arguments and response fields, RO/RW separation, source trust, valid-time rules, original audits and immutable assertions.
- No new provider calls, re-embedding, source-file opener or host filesystem access. Test fixtures are synthetic; migrations and destructive recovery tests run only on owned isolated PostgreSQL.
- New source versions must survive dump/restore; PostgreSQL transaction IDs are not portable evidence versions.
- Schema downgrade is unsupported after new writes. Recovery is verified pre-upgrade restoration with explicit post-backup write-loss limits.

## Interface contracts

| Contract ID | Boundary | Inputs | Outputs | Errors or invariants |
|---|---|---|---|---|
| IC-001 | Evidence inspection | Document ID/slug, optional source key, bounded page | Version 1 evidence envelope | Same authorization and representation in all clients |
| IC-002 | History inspection | Readable document anchor, optional linked source, bounded cursor | Decision events and finite continuation | No guessed-source bypass or fabricated pre-upgrade events |
| IC-003 | Strict review | Anchor, target state, reason, inspected version | New state/version | Atomic conflict on changed evidence |
| IC-004 | Legacy compatibility | Existing get/search/review/source-state arguments | Preserved existing fields and behavior | Legacy changes invalidate new strict versions |

## Edge cases

- Empty source sets; historical claims; unknown timestamps; missing source provenance; secret-redacted stored quotes; Unicode exactness; repeated spans versus distinct source events.
- New spans after confirmation do not inherit approval. Reinstatement does not erase withdrawal history or temporal supersession.
- Shared sources across readable and unreadable documents permit only scoped reads; source-wide mutation requires authority over all dependents.
- Concurrent attach/review/withdrawal, audit failure and policy revocation at commit must roll back safely.
- Evidence pages and histories have explicit limits, stable cursors and documented truncation, never unbounded aggregates.

## Assumptions and unresolved decisions

The current source/claim/assertion gates are the authority. Reviewed means an operator decision, not independently verified truth. No material product ambiguity remains; exact technical fields are specified in the contract and may be refined with evidence while preserving these outcomes.

## Success measures

- SC-001: Four client surfaces return the same inspected version and source/span state for each synthetic fixture.
- SC-002: Zero stale decisions commit in tested attachment, withdrawal/reinstatement and concurrent-review cases.
- SC-003: Original populated-copy field hashes and restored backup manifests match; migration retry performs no duplicate work.
- SC-004: Report two or three measured before/after examples, actual sample sizes and exact source revisions; no unsupported accuracy or performance claims.

## Playbook obligations

PB-063-UPGRADE (system): operators upgrading a populated 0.6.15 installation; canonical path `docs/playbooks/system/rag-063-source-evidence-upgrade.md`; origin FR-005/US-004. Deliver preflight, verified backup, restart/migration order, retry, validation and restoration limits. Independently review and rehearse on an isolated representative copy before PR handoff.

Ordinary inspect/review UI is self-contained; a separate review playbook is unnecessary when conflicts explain refresh/reinspection and the contract documentation explains the trust model.
