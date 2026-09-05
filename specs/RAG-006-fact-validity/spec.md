# Feature Specification: Evidence-backed fact validity

## Stable work ID

- Feature ID: `RAG-006`
- Artifact path: `specs/RAG-006-fact-validity/spec.md`
- Status: Accepted under the user's end-to-end issue instruction
- Source request: GitHub issue #6; next issue after completed #5.

## User scenarios

### US-001: Retrieve the applicable configuration (Priority: P1)

A user asks for a setting now or at a specified past time. Explicitly replaced or
expired assertions are omitted from current results; historical queries recover
the assertion that applied then, regardless of import order.
Independent test: import February before January, then query both dates.

### US-002: Preserve unrelated knowledge and uncertain evidence (Priority: P1)

A changed setting does not invalidate a second setting, another project's entity,
or a user-owned pin. Extensions coexist. Uncertain dates, suggestions and conflicting
same-time assertions are reviewable without silently replacing knowledge.
Independent test: overlapping entity names, two attributes and an ambiguous update.

### US-003: Audit and recover updates (Priority: P1)

An operator can inspect the source quote, role, event identity, validity and typed
links for every assertion. A failed or replayed mining batch has no partial or
duplicate temporal effects. Existing manual document browsing remains available.

## Acceptance criteria

- AC-001: Configuration replacement, extension, expiry, separate-project entities
  and as-of queries produce the fixture's expected assertions.
- AC-002: An older event imported later cannot supersede a newer event by arrival
  order. Equal-time conflicts and unsupported temporal evidence require review.
- AC-003: Replacement affects one atomic assertion key only. Source documents,
  unrelated assertions, pin bodies/scopes and historical evidence remain intact.
- AC-004: Current eligibility is applied before retrieval limits and at each
  selected graph hop; startup and prompt recall use the same current policy.
- AC-005: Accepted assertions retain sanitized source event references, speaker,
  quote, explicit time and audit/typed edges through expiration and replacement.
- AC-006: Transaction failure rolls back documents, evidence, edges and batch
  effects; replay after acceptance applies exactly once.
- AC-007: Refutation/reactivation policy cannot let an old reviewed contradiction
  silently re-refute an explicitly reactivated document; newer evidence is reviewable.
- AC-008: A versioned fixture reports stale-result rate and current/historical
  recall with identical search mode/budget against the prior eligibility baseline.

## Functional requirements

- FR-001: Represent mutable knowledge as atomic assertions alongside ordinary
  documents; never infer historical validity for the legacy corpus.
- FR-002: Separate event/validity time from ingestion and verification time.
  Validity intervals are half-open; times require an explicit timezone.
- FR-003: Before saving a mined assertion, inspect bounded same-known-project,
  same-entity/attribute candidates. Duplicate, extension, replacement and conflict
  decisions retain their evidence; similarity alone has no replacement authority.
- FR-004: Only explicit grounded replacement may close an earlier assertion.
  Uncertain timestamps, assistant suggestions and ambiguous conflicts go to review.
- FR-005: Expose current, as-of and deliberate history selection through CLI/MCP;
  get/timeline continue exposing preserved history. Current is the search default.
- FR-006: Keep mutation and publication under the existing audited gateway and
  backup-gated deployment process; no new provider processing is needed for tests.

## Compatibility boundaries

Ordinary documents retain their status-based behavior. Existing scope selectors,
read-only MCP roles, shared database, exact pins and continuity checkpoints remain.
The minimal source-evidence subset of #7 is included only for these assertions;
full claim extraction/classification for the existing corpus remains #7.
As-of means known assertions valid at that event time, not reconstruction of every
past edit to an ordinary document or what the system knew at ingestion time.
Migration is additive, with no automatic legacy rewrite. Old clients remain able
to browse but old workers must not run after temporal activation; use forward fix
or the verified predeployment backup.

## Interface contracts

| Contract ID | Boundary | Inputs | Outputs | Errors or invariants |
|---|---|---|---|---|
| IC-001 | Assertion write | entity, attribute, value, relation, explicit event time, source evidence, known scope | immutable assertion document and disposition | invalid evidence cannot replace a fact |
| IC-002 | Retrieval | query, scope, optional as-of/history | eligible evidence | history and as-of mutually exclusive |
| IC-003 | Mining | bounded source records and extracted assertions | accepted replayable batch | no extra provider call; quote grounded against identified record |
| IC-004 | Review | unresolved temporal assertions | bounded worklist with reasons | preserves evidence and existing accepted facts |

## Edge cases

Expiration does not revive an explicitly replaced old value. Future changes leave
today's value eligible until their start. Late older replacement fits before later
replacement. Same-time different values are unresolved, never last-write-wins.
Unknown project is insufficient for automatic entity matching. Candidate overflow
requires review rather than comparing an incomplete history. Invalid timestamps
cannot default to now. Atomic assertions cannot be edited in place or moved between
projects; create a corrective assertion to preserve their evidence history.

## Assumptions and unresolved decisions

Entity/attribute keys are explicitly extracted identities, not a new entity resolver.
A genuine extension uses a distinct attribute or an explicitly additive relation;
replacement authority requires a user statement and exact source evidence.
The existing mining provider may emit the additional structured fields during its
normal authorized workflow; development uses synthetic fixtures only.
No blocking scope decisions remain.

## Success measures

- SC-001: Zero stale or foreign assertion results in the controlled fixture.
- SC-002: All labeled current/as-of assertions are recovered within the fixed budget.
- SC-003: Failure/replay tests preserve atomicity and all existing scope regressions pass.
