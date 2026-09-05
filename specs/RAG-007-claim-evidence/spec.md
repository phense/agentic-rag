# Feature Specification: Claim evidence and inference status

## Stable work ID

Feature `RAG-007`; source GitHub #7 and user's instruction to implement the next issue.
Status: accepted under the end-to-end instruction. Builds on deployed #5/#6.

## User scenarios

- US-001 (P1): A reader distinguishes a user statement, assistant proposal,
  hypothetical, inference and later correction, and inspects bounded source evidence.
- US-002 (P1): Repeated extraction or assistant paraphrase cannot manufacture
  independent user corroboration. Distinct source events remain traceable.
- US-003 (P1): An operator withdraws/refutes a source with a reason; dependent
  claims are reconsidered without erasing other active evidence or history.

## Acceptance criteria

- AC-001: Controlled user/proposal/hypothetical/correction fixtures yield distinct
  classifications and sanitized role/event/time/span evidence through mining/get.
- AC-002: Nonexistent source IDs, quotes outside consumed spans, clipped context and
  secret-shaped content cannot promote claims. Structural grounding is not truth or
  semantic entailment; a separate synthetic semantic check measures the distinction.
- AC-003: Same-event replay and changed span from that event count once; assistant
  repetition counts zero independent user sources; separate user sources are retained.
- AC-004: Source withdrawal/refutation immediately affects current eligibility;
  surviving independent support keeps an eligible statement available, loss of all
  support requires review. No source/claim history is erased.
- AC-005: Retrieval exposes compact kind/review/provenance/source-count metadata.
  Unreviewed proposals, hypotheticals and inferences are available explicitly through
  history/get/review, not presented as confirmed facts by automatic retrieval.
- AC-006: Legacy documents remain available and explicitly provenance-incomplete;
  no fabricated evidence or claim-level verification is inferred from verified_at.
- AC-007: Batch replay/failure and concurrent source changes preserve atomicity;
  scope, temporal validity, pins, privilege levels and source redaction remain intact.

## Functional requirements

- FR-001: Each newly mined ordinary item describes one claim, with bounded evidence
  references and a stated/proposal/hypothetical/inference kind. Unsupported items are
  retained as incomplete review records for compatibility with accepted old batches.
- FR-002: Derive speaker/time/event identity from consumed source records. Namespace
  identity by session, never accept a model-supplied role. Exact source membership
  does not verify a paraphrase; unreviewed summaries remain inferences.
- FR-003: Count distinct active user source events rather than spans, repeated mining
  or assistant echoes. Source state changes and claim review are audited gateway writes.
- FR-004: Preserve evidence on exact claim reuse within a known project; never merge
  by semantic similarity or across projects. Distinct interpretations retain separate
  records. Managed claims are immutable; corrections create new claims.
- FR-005: Add evidence source/refutation and explicit claim review CLI/MCP tools;
  read-only MCP remains unable to call mutations. Confirmation requires active evidence
  and an operator reason; it does not forge new source truth.

## Compatibility boundaries

One shared database, audited redaction, exact pins and additive client configuration.
Migration adds metadata structures; legacy text/provenance/timestamps remain unchanged.
Legacy manual saves remain available with incomplete provenance. Ordinary evidence
claims and temporal assertions share source lifecycle handling for new writes;
legacy temporal evidence remains inspectable without invented event identity.
History/get preserve all dispositions; as-of uses current source trust plus known
valid time, not a reconstruction of past trust decisions. No private corpus processing.
Backup-gated production rollout follows successful review/tests and explicit deployment
approval where the automatic reviewer requires it.

## Interface contracts

| ID | Boundary | Input/output | Invariant |
|---|---|---|---|
| IC-001 | Mining -> accepted batch | kind and grounded source spans | bounded, redacted, source-derived role/time |
| IC-002 | Gateway -> evidence registry | immutable claim and source links | stable source identity and atomic audit |
| IC-003 | Retrieval -> reader | compact evidence summary, full get sources | no silent inference promotion |
| IC-004 | Operator -> source/claim lifecycle | state and reason | audited, reversible trust changes, no deletion |

## Edge cases and assumptions

Mixed paragraphs are not automatically split from the legacy corpus. New extraction
is instructed to emit one independently assessable statement per item. Exact full
source text can be classified stated; summaries require inference review. Questions,
quoted hypotheticals and incomplete source fragments cannot become stated facts.
Source identity proves distinct events, not independence of their authors or real-world
truth. Repeated same-text user confirmations from distinct events are separate sources;
assistant events never add to independent user count.

## Success measures

Zero fabricated/promoted evidence in boundary fixtures; idempotent source counts;
all source lifecycle, mining recovery and existing scope/time regression tests pass.
A synthetic entailment fixture is inspected separately from substring validation.
