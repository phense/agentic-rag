# Implementation Plan: Consistent source evidence and review state

## Stable work ID

- Feature ID: `6.5`; work ID: `RAG-063`; specification: [spec.md](spec.md).
- Artifact path: `docs/specs/6-5-source-evidence/plan.md`.
- Accepted under existing end-to-end implementation authorization; no production rollout of #63 is authorized by this plan.

## Summary

Extend the existing `knowledge_sources`, `claim_records` and `claim_evidence` model. Add portable storage revisions and append-only decision history without modifying original fields. Derive a single versioned presentation in `agentic_rag/evidence.py` or a focused `evidence_contract.py`. Wire the same gateway into local/central MCP, REST, CLI and dashboard. Keep existing validity predicates authoritative.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Read existing architecture and compatibility | AGENTS.md, docs/claim-evidence.md, docs/fact-validity.md; two read-only inventories | Complete |
| Safe baseline | main5390a6f/0.6.15/schema028; 38 targeted tests, exit0,54.72s | Passed; one existing Starlette warning |
| Upgrade | Current deployed version 0.6.15; existing upgrade framework | Add source version 0.6.15; schema029 only additive |
| Independent review | AGENTS.md and architecture gate | Required after complete bounded implementation; fixes re-reviewed |
| PR lifecycle | Issue63 open; step5/15 | Create PR after gates; wait for NEW weiter; never merge this PR yet |
| Recovery state | Helper rejects legacy BACKLOG task IDs | Manual reconciliation in .engineering-method/inputs/RAG-063/manual-recovery.md; no reset/rewrite |

## Technical context

Python >=3.11, current env3.13; PostgreSQL17/pgvector; vanilla JS dashboard. Relevant paths: evidence.py, store.py, validity.py, mcp_server.py, cli.py, service/engine.py, service/dashboard_views.py, service/dashboard_assets/app.js, service/read_limits.py, sql/012/020/021/023/028, profiles.py, thematic.py and generated-pattern eligibility consumers.

Owned isolated PostgreSQL: localhost55460, data `/dev/shm/agentic-rag-issue60-20261030/pgdata`; root filesystem has <0.5GiB free, so test scratch under `/dev/shm/rag63-20261031-tests`. Never production5432 or another session's55458. No live providers needed; mock only provider boundaries.

## Compatibility boundaries

- Add schema029 revisions/history with grants and RLS following service021. Revisions start at storage baseline1, not an invented original source revision. History starts at upgrade; existing audit history remains separate and untouched.
- Persist monotonic revisions; do not use xmin or state-only hashes because restore changes xmin and withdrawal/reinstatement creates ABA collisions.
- Preserve legacy gateways; add optional expected-version behavior or strict additive operations. New dashboard/CLI strict actions require a token. Even legacy writes advance versions.
- Sources and quotes remain immutable through public write gateways. Existing attachments retain reviewed flags and source-event identity. New attachments never inherit reviewed status.
- Current deployed source0.6.15→0.6.16 and029 with verified backup/restore and idempotent retry. Old processes must restart at cutover; preserve old read signatures. No schema downgrade after writes.
- Keep original quoted content exact. New contract omits raw host namespace/path locators, using source_key/span_hash. Review legacy presentation metadata for remote path disclosure and document a compatibility-safe resolution; do not corrupt project authorization keys or original content to redact locators.

## Interface contracts

Formal fields and bounds are in [contracts/evidence-v1.md](contracts/evidence-v1.md) (as built). One read representation (`agentic_rag/evidence_contract.py`) and one scoped history producer feed every transport. Final names: read tools `memory_evidence` and `memory_evidence_history`; the existing `memory_review_claim(..., expected_version=None)` and `memory_source_state(..., expected_version=None, id_or_slug=None)` gain optional strict parameters instead of separate strict tools; CLI `rag evidence show|history` plus `--expected-version`/`--document`. Strict callers (dashboard always) supply the version.

A document evidence token includes portable claim revision, evidence membership/quotes/completeness/reviewed flags, all linked source revisions, lifecycle/temporal metadata and scope/domain relevant to the decision. Read-only source selection and history remain anchored to the requested visible document. Tokens must not encode foreign document IDs/counts.

Lock order for strict claim review: SHARE-lock the writable document lifecycle, lock claim record, then all linked sources in deterministic key order, read and compare the whole evidence version, then update flags/claim review/history/audit atomically. Attach already locks claim then source. Source trust changes lock only the source, compare its inspected version, then update source/history/audit; they never lock dependent claims, avoiding a cycle. Source-state versions bind to portable source revision; strict claim versions also change on source-state transitions. Test the actual lock interactions.

Revision tracking should catch legacy gateway changes and direct supported SQL updates; database triggers are preferred over incomplete per-caller increments. Any trigger touching claims follows the same lock order as attachment/review. Do not make source updates acquire claim locks.

## Dependencies

Existing SQL eligibility gates, audited store gateway, service RLS, credential revalidation at commit, bounded read helper and upgrade harness remain dependencies. No new external dependency or provider is required.

## Tests

- TDD regression/contract tests: portable references, exact quote fidelity, explicit legacy/manual/assistant/partial labels; restore-stable tokens; stale attachment/source/ABA/review rejection; audit rollback and concurrent lock behavior.
- Cross-client contract parity: CLI JSON/plain, local MCP, central dispatcher/REST and real dashboard preview/apply/drilldown. Test RO rejection, foreign source IDs, shared-source all-dependent write denial, revoked credentials, bounds and non-oracular errors.
- Invalidation integration: live search/context/profile/thematic/generated-pattern reads after withdrawal, expiry and supersession; verify no resurrection and current authority before accepted output.
- Upgrade: populated synthetic multi-user/multi-domain source028 fixture, verified backup restore, original-field hashes, migration029 retry, pre-upgrade client reads. Use existing executable upgrade framework rather than a prose-only claim.
- Fresh full pytest suite at final frozen tree, node syntax, wheel packaging including migration, actual test exit artifact. Broaden only at integration or for a new relevant failure.
- After as-built reconciliation a strong independent system architect derives at least one real cross-component success test and one rollback/recovery test; execute both before convergence.

## Architecture findings

See `docs/uml/findings.md`, entries AF-063-001..004. All require implementation/test evidence; none is waived by existing unit passes.

## Supporting artifacts

`contracts/evidence-v1.md`: formal external representation and concurrency behavior. A separate research/data-model file adds no value beyond this plan and contract, so omitted. One sequence model answers lock/authorization/rollback ordering.

## Implementation structure

One cohesive implementation owner handles schema, core, transports, dashboard and tests sequentially, preventing shared-file conflicts. The coordinator integrates evidence, independently reviews through a separate reviewer and publishes. No other agent may revert unrelated workspace edits. Existing inventory agents are complete and own no writes.

## Playbook obligations

PB-063-UPGRADE (system): `docs/playbooks/system/rag-063-source-evidence-upgrade.md`; implementer owns authoring and synthetic rehearsal; independent review owns content validation. Deadline: before final delivery (FR-005/T063-009). Reuse existing automated upgrade framework; demonstrate interrupted/retry/restoration limits.

Development: none in this PR. All migration/recovery tests use disposable isolated databases; no production cutover or coordinated live actors occurs. Reassess if live deployment scope is later added by the maintainer.

As-built correction: advisory-only source locking failed against old0.6.15-style SQL. Strict review now also SHARE-locks source rows via the no-data `rag_lock_claim_source` helper, which explicitly authorizes the readable/writable anchor and membership. This avoids broad source UPDATE RLS while granting no source mutation. Document SHARE locking protects lifecycle/scope; source-only writes still acquire no claim locks. See coordinator regression evidence and the reconciled sequence.
