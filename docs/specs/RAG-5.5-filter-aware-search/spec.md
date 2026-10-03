# Feature Specification: Filter-aware vector retrieval

## Stable work ID

- Feature ID: RAG-5.5; canonical [Issue30](https://github.com/phense/agentic-rag/issues/30), feature5/10.
- Status: Accepted intent from the maintainer's sequential end-to-end request.
- Source:99514fe, populated migrations001–015; no production mutation authorized for this feature.

## User scenarios

### US-001: Retrieve within a small project (P1)
Search the eligible project/global subset rather than losing useful neighbors in a shared ANN index. Independently compare the vector candidates against an exact eligible-set oracle.

### US-002: Retrieve a rare domain or historical source (P1)
Current/as-of/source validity, domain, project and active status govern every representation before a result is accepted. Compare filtered recall and latency separately.

### US-003: Discover a second document (P1)
One long document cannot consume the entire small-set vector candidate budget. Independently demonstrate two eligible original sources rather than hundreds of chunks from one source.

## Acceptance criteria

- AC-001: Detect installed iterative-scan capabilities. Older pgvector versions retain a working bounded ANN/exact path without an extension upgrade.
- AC-002: Small eligible vector sets use exact distance ordering; returned diverse candidates match an independently computed exact eligible-set oracle, including stable ties.
- AC-003: Large sets use bounded candidate pools, scan/memory settings and cancellation budgets; no infinite widening or unbounded exact fallback.
- AC-004: All status/domain/project/source/time and contextual source/model checks precede acceptance; original snippets, offsets and citation identities remain valid.
- AC-005: Per-call planner settings restore on success, timeout and cancellation; caller transactions and stricter caller budgets survive. External cancellation is not swallowed.
- AC-006: New code without016 retains Feature4 behavior. Actual old code works with016. Populated migration interruption/retry, code rollback, strict backup restoration and canonical row preservation pass on owned isolated copies.
- AC-007: Three practical before/after comparisons publish raw samples, repetitions, source revisions, exact-oracle recall, latency and limits. Trading remains read-only; synthetic adversarial data is labeled as such.
- AC-008: Affected/full Python and Node checks pass; independent complete-diff review leaves no Critical/High/Medium bug. Low findings are fixed or separately linked.

## Functional requirements

- FR-001: Select a route from a bounded eligible-set probe, not a corpus-wide count or a provider call.
- FR-002: Apply the same planning policy to raw and current contextual vectors; keep bilingual lexical fusion, document diversity and original-source presentation.
- FR-003: Exact selectors, context-off, forced hybrid and historical baseline retain their existing behavior. Default auto/context-auto adopts planning when016 exists.
- FR-004: No content/index rewrite, new provider, scheduler, adapter, dependency or service installation.

## Compatibility boundaries

Additive016 installs read-only functions only; existing015 objects and all canonical rows/contexts stay intact. New code on015 falls back. Roll back code while retaining016. Database restoration is rehearsed only on owned empty targets. PostgreSQL17 and pgvector>=0.7 remain supported; installed production0.8.4 is verified.

## Interface contracts

| ID | Boundary | Preserved contract |
| --- | --- | --- |
| IC-001 | Python/CLI/MCP search | Existing arguments, hits, warnings, original evidence and privilege levels |
| IC-002 | SQL planned candidates | Same candidate fields; invoker privileges; bounded vector helper |
| IC-003 | transaction ownership | Planner savepoint cannot commit/rollback caller writes or leave settings changed |
| IC-004 | upgrade |015→016 additive, interrupted/repeated migration safe, old/new readers compatible |

## Edge cases

No vectors; empty/unknown scopes; stale/null contextual models; many foreign/expired/refuted/archived neighbors; one oversized document; zero vectors; deterministic equal distances; unsupported iterative GUCs; held locks; concurrent source edits; autocommit and caller transactions; statement timeout and explicit user cancellation.

## Assumptions and unresolved decisions

Bounded ANN remains approximate and can omit neighbors after its stated scan/pool caps. Exact-oracle recall does not establish answer accuracy. Thresholds require measured calibration before acceptance; no universal speedup is assumed.

## Success measures

SC-001: eligible small-set diverse vector recall1.0 against the oracle. SC-002: source and setting-preservation assertions all pass. SC-003: three attributable comparisons report improvements or costs honestly. SC-004: zero blocking review findings.

## Playbook obligations

PB-5.5, operator, AC-005/006: verified deployment/cancellation/rollback procedure; rehearse populated upgrades before merge. No infrastructure replacement.
