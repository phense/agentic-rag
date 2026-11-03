# Feature Specification: Scoped retrieval feedback

## Stable work ID

- Feature ID: RAG-071; roadmap6.13; [Issue71](https://github.com/phense/agentic-rag/issues/71).
- Status: Approved execution scope under the maintainer's autonomous-continuation instruction.
- Source request: capture useful/not-useful/wrong-source/missing-evidence signals,
  reproduce approved failures privately, and preserve factual evidence and access.

## User scenarios

### US-001: Give feedback on a particular retrieval (Priority: P1)

A writer explicitly requests a feedback-enabled search, then records a typed
signal for that event and an optional returned or expected memory. They can
inspect, revise or retract their own feedback without changing the memory.
Independent test: search, submit twice with the same key, update with the current
revision and retract; one logical signal remains and all memory/evidence hashes
stay unchanged.

### US-002: Understand an unsuccessful search privately (Priority: P1)

An operator inspects an authorized signal, supplies a bounded sanitized query
matching the original query digest, and explicitly approves its expected source.
They export a private evaluation case and reproduce the failure without sending
content to a provider or mixing it into the public synthetic benchmark.
Independent test: wrong-source and missing-evidence cases traverse the same
workflow; withdrawn or changed expected evidence is withheld, never treated as
an incorrect memory or a successful reproduction.

### US-003: Count independent signals (Priority: P2)

An operator sees deduplicated feedback counts by authenticated actor and source
family. Retries and multiple machines belonging to one actor cannot inflate
independent support. Independent test: duplicate submissions and two clients of
one user count once; a second user counts separately; no ranking changes.

## Acceptance criteria

- AC-001: Explicit feedback-search returns ordinary scoped search results plus
  an immutable event identifier. The event binds actor/client, request origin
  when available, timestamp, query digest, exact selectors, retrieval settings,
  software/config/model identity and bounded result/source versions. Ordinary
  search and read-only MCP operation retain their current behavior.
- AC-002: Submit accepts useful, not_useful, wrong_source or missing_evidence,
  a UUID idempotency key, a comment of at most1000 characters and optional
  result/expected-document IDs. Identical retries return the same record;
  conflicting key reuse and stale update revisions return explicit conflicts.
  Retraction preserves versioned history and invalidates any prior approval.
- AC-003: Mutations require existing write authority on the explicit event
  domain/project. They cannot elevate a read-only principal or edit another
  actor/client's record. Every referenced document must be currently visible;
  result IDs must belong to the event. Foreign/missing IDs have the same outcome.
  Current permission revocation is rechecked at commit.
- AC-004: No feedback path changes documents, source trust, evidence, claim
  review, validity, vectors or rank. Feedback is a separate audited signal,
  never confirmation, refutation or deletion of knowledge.
- AC-005: Raw queries/prompts and result bodies are not retained in event records
  or operational logs. Comments are secret-stripped before storage. Query
  material used for evaluation requires explicit local operator approval,
  matching the captured digest and passing secret screening. Exports stay in
  bounded private files outside Git; no cloud or model calls occur.
- AC-006: Storage, event/result/source sizes and mutation frequency are bounded.
  Quota exhaustion fails explicitly without dropping acknowledged records.
  Aggregation collapses repeated signals per user/source family, independent
  of machine or retry count. Existing service rate/control limits do not change.
- AC-007: Only current explicitly approved negative feedback with an eligible,
  unchanged expected source enters private evaluation. Connected source families
  remain wholly in dev or held-out test. The existing confirmed-failure workflow
  accepts the separate feedback format without changing existing formats,
  synthetic corpora, automatic ranking or training.
- AC-008: Populated0.6.27/schema036 upgrades preserve original rows, scopes,
  vectors, pins and queued jobs. Retry and interrupted migration are atomic;
  independent source/target restores work. Old0.6.27 readers remain usable with
  feedback disabled. Code rollback retains feedback tables and explains the
  old operator's newer-schema refusal.
- AC-009: Demonstrate useful/retraction, wrong-source and missing-evidence
  workflows over local CLI, REST and MCP. Include anonymous/foreign callers,
  stale/withdrawn evidence, secret-shaped comments, idempotency races, forced
  audit rollback and whole-knowledge hash preservation. Report actual counts and
  limits; a vote does not itself prove a retrieval defect.

## Functional requirements

- FR-001: Feedback capture is explicit and off by default. The first release
  supports feedback-enabled search; it does not silently log every ordinary
  search/context/research prompt. A dashboard action is optional and deferred.
- FR-002: Derive actor and client identity from trusted request authority or
  the local operating-system identity, never a user-supplied actor parameter.
  The first release uses existing writer permissions rather than broadening
  read-only credentials. An operator is needed for cross-actor aggregation and
  evaluation approval/export.
- FR-003: Store immutable event/result snapshots and a bounded revision history
  for feedback. Updates and retraction are optimistic and transactional with
  audit. Source visibility/version is rechecked for read, approval and export.
- FR-004: Approval is an evaluation label only. It requires explicit query
  reconstruction and a visible eligible expected source. Updating/retracting
  feedback or changing its evidence invalidates approval.
- FR-005: Preserve held-out separation by source family, not actor or vote
  count. Report stale/withheld/unreproduced denominators; never count them as
  successful reproductions or silently tune on held-out results.

## Compatibility boundaries

Source is0.6.27/schema036 on both production hosts. Additive migration037 must
leave001..036 byte-identical. The next PR is0.6.28 unless main advances. Existing
knowledge writes still use the audited gateway; feedback metadata uses its own
audited gateway and never claims to be knowledge. Existing search signatures,
response fields, jobs, reader privileges and public diagnostics are preserved.
No production backfill, feedback enablement, automatic query retention or
feedback-driven ranking occurs during upgrade. Deployment uses verified backups
and a representative populated rehearsal before any production cutover.

## Interface contracts

| ID | Boundary | Inputs | Outputs | Invariants |
|---|---|---|---|---|
| IC-001 | Feedback search | Explicit query, domain/project, bounded search settings, idempotency key | Search results and event ID | Same retrieval engine; no raw query retained |
| IC-002 | Feedback mutation | Event, typed signal, IDs, comment, idempotency/expected revision | Record/revision or uniform unavailable/conflict | Own authorized event; audit atomicity |
| IC-003 | Feedback inspection | Own record/event ID | Redacted metadata, versions and current/stale state | No result bodies or foreign identity oracle |
| IC-004 | Operator approval/export | Explicit signal, matching safe query, current expected source | Approval and private sealed cases | No evidence review or ranking mutation |
| IC-005 | Offline evaluation | Private feedback cases | Reproduced/unreproduced/stale counts by split | No providers, writes, public-corpus mixing or tuning |

## Edge cases

Empty results, shared global results, revoked scopes, expired events, guessed
UUIDs, changed claims or source versions, withdrawn sources, erased images,
duplicate clients, concurrent conflicting updates, retry after lost ACK, secret
comments/queries, malformed selectors and full storage fail explicitly or are
withheld. A failure to capture an explicitly requested event is not reported as
successful capture. Read-only tools never gain mutation capability.

## Assumptions and unresolved decisions

No material scope question is pending. Safe defaults are no query retention,
writer-only capture/mutation, local operator-only approval/export and no
automatic rank/truth effects. These are reversible choices within Issue71's
acceptance. General-purpose analytics, a dashboard voting UI and automated
optimization require separate work.

## Success measures

- SC-001: Zero cross-actor edits, unauthorized source disclosures or changes to
  canonical knowledge/evidence from feedback operations.
- SC-002: Duplicate retries produce one signal; stale writes conflict; actor
  independence survives multiple clients and retraction.
- SC-003: Three measured workflows include at least two independently approved
  private retrieval cases, with preserved held-out families and explicit stale
  denominators. No model or cloud calls are needed.

## Playbook obligations

PB07101: operators/writers need one system playbook at
`docs/retrieval-feedback.md`, originating in AC-003/005/007/008/009. It must cover
opt-in, capture/update/retract, private approval/export/evaluation, quotas,
withdrawal/changed-evidence handling and populated upgrade/rollback. Require
independent content review and executable local/HTTP examples plus restore
rehearsal; a prose-only procedure is insufficient.
