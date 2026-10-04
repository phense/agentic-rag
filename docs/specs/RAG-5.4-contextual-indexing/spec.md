# Feature Specification: Grounded contextual chunk indexing

## Stable work ID

- Feature ID: RAG-5.4; canonical Issue #29, roadmap feature4/10.
- Status: Accepted intent from the maintainer's end-to-end implementation request.
- Source request: bounded document/section/project/time context alongside existing retrieval representations, with original source citations and verified upgrades.

## User scenarios

### US-001: Retrieve a fact whose subject occurs earlier (P1)
A scoped question finds the original service/port, dated numerical fact or later section rather than an introductory chunk. Independent test: hand-labeled fact chunk survives the same k/context budget with contextual retrieval.

### US-002: Safely build or refresh context (P1)
An operator incrementally builds context through the audited save gateway without changing documents, existing chunks/vectors, claims, pins or checkpoints. Independent test: interrupted bounded calls resume and unchanged calls are idempotent.

### US-003: Upgrade a populated installation with mixed clients (P1)
Old clients retain baseline behavior; new clients use current representations and can request baseline ordering. Independent test: actual old module reads/writes during upgrade and code rollback preserves canonical state.

## Acceptance criteria

- AC-001: Context consists only of bounded source excerpts/headings and explicit document/project metadata, with no invented facts or hosted inference.
- AC-002: Returned snippets, offsets and citations resolve to original saved chunk content; prefixes are advisory indexing data only.
- AC-003: Save-only reindex changes derived rows and append-only audit records, preserving all canonical rows and original embeddings/identities.
- AC-004: Bounded retries after interruption, model failure, concurrent correction or scope change cannot use stale context, lose old representations or overwrite newer data.
- AC-005: Source/domain/project/time eligibility precedes all contextual limits; read-only clients cannot build indices.
- AC-006: Missing additive migration retains baseline reads/normal saves; explicit index requests clearly report the missing prerequisite.
- AC-007: Publish three practical attributable comparisons, separate indexing costs from latency/context/source coverage, and report limits. All affected/full Python and Node tests and independent review must pass.

## Functional requirements

- FR-001: Keep versioned derived context beside original representation; ordinary new saves add lexical context without another embedding request.
- FR-002: Audited bounded index-only save can additionally create local contextual embeddings; no new queue kind or worker/provider contract.
- FR-003: Ordinary auto/lexical retrieval can fuse current context with baseline candidates. Forced hybrid, historical baseline and an explicit context-off option retain existing candidate behavior.
- FR-004: Exact IDs/error symbols bypass contextual ranking; inference failures preserve usable baseline/lexical retrieval.

## Compatibility boundaries

Supported source499c656, migrations001–014, Python3.13, PostgreSQL17/pgvector. Additive migration015 creates empty derived objects without rewriting canonical state; functions/columns of previous migrations remain. Apply migration before indexing; new code on014 falls back. Code rollback leaves derived objects inert and original data intact; database restore is only disaster recovery with explicit snapshot loss limits. Client configuration/hooks/jobs/provider/dependency settings stay unchanged. Production deployment remains separately authorized.

## Interface contracts

| Contract | Input | Output | Invariant |
| --- | --- | --- | --- |
| IC-001 search | existing options; additive context auto/off | original SearchHit contract | scope and source checks fresh |
| IC-002 save | normal fields or explicit index-only selector | ordinary SaveResult or bounded index progress | audited transaction; no canonical update in index-only mode |
| IC-003 migration | populated source014 | schema015 | canonical rows/roles/history preserved; transactional retry |

## Edge cases

Fenced fake headings, multiline/oversized headings, hard chunk boundaries, legacy chunk layouts, empty documents, unknown scope, archived/refuted/expired sources, immutable claims, missing vectors/model identity, model replacement, stale source and concurrent edits.

## Assumptions and unresolved decisions

Use deterministic grounded excerpts initially; generated summaries are outside this request. Context can improve ordering but cannot prove a fact's subject/date when those are absent from the returned original span. Consumers can retrieve the original document for full context. No general accuracy or universal speedup is assumed.

## Success measures

SC-001: all source-span assertions pass. SC-002: canonical table fingerprints identical around migration/indexing except legitimate concurrent audited writes. SC-003: three practical examples record source/evidence/context denominators and raw paired timings. SC-004: zero unresolved Critical/High/Medium review findings.

## Playbook obligations

A verified upgrade/recovery procedure is required as a system deliverable (PB-5.4, operator, AC-004/006); rehearse against a populated owned installation before merge. No unrelated infrastructure operation.
