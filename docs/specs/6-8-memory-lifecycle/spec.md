# Feature Specification: Source-preserving consolidation and lifecycle views

## Stable work ID

- Feature ID: `6.8` / `RAG-066`, [Issue66](https://github.com/phense/agentic-rag/issues/66), roadmap8/15.
- Artifact path: `docs/specs/6-8-memory-lifecycle/spec.md`.
- Status: Accepted for technical planning; implementation and acceptance remain pending.
- Source request: complete all remaining6.x issues sequentially. Every PR needs a tested existing-installation upgrade path. The maintainer explicitly permits autonomous merge after green tests, independent review and verified upgrade; production rollout remains separate.

## User scenarios

### US-001: Consolidate repeated or richer knowledge without losing its sources (P1)

An operator can inspect two memories, distinguish exact duplicate, semantic duplicate,
information extension, explicit replacement and unresolved contradiction, then make
an auditable decision. Exact duplicates can follow a narrowly justified deterministic
policy. Semantic similarity or a later import alone never authorizes a truth change.
Independent test: sources and originals survive; distinct entities/scopes do not merge.

### US-002: Understand current knowledge and its history (P1)

A caller can ask for the current canonical result, merged originals or historical
results and inspect the reason, source links and supersession chain. Merged and
superseded are different from archived, refuted and review-needed. Existing API
calls retain documented defaults; current views never treat ingestion time as truth.
Independent test: the same scoped corpus yields the specified, labelled views.

### US-003: Correct a consolidation safely (P1)

An authorized operator can reverse a mistaken decision through the gateway without
rewriting old evidence, reviving an invalid fact, duplicating an action or making a
cycle. Readers and derived outputs observe a coherent committed state.
Independent test: concurrent replay/correction and injected audit failure are atomic.

### US-004: Upgrade a populated deployment (P1)

Upgrade0.6.18/schema030 to0.6.19 and use the capability without re-extraction,
re-embedding, model downloads or automatic new consolidation during migration.
Independent test: full original-row/source/privilege inventories survive upgrade,
retry and independently verified restore; actual0.6.18 consumers are exercised.

## Acceptance criteria

- AC-001 — Given two visible memories, preview classifies all five operation types, states what is proved versus operator judgement, reports bounded source/version references and performs zero writes/provider calls. Missing/foreign anchors are non-oracular.
- AC-002 — Given a consolidation request, only justified exact duplicates can be applied by an automatic policy. Semantic duplicate/extension/replacement need explicit, version-bound authorization and evidence/reason; contradiction stays reviewable and does not silently hide either side. Different domains/projects, unknown applicability, different supported entities, future/equal/unknown event order and weak support fail closed or remain review-needed as applicable.
- AC-003 — Applying a decision preserves original document IDs/content, source spans, assertions/claims, additional independent sources, pins and previous audit/history. Canonical links never move immutable assertions across scope or manufacture evidence. Drill-down can reach every retained authorized original, with limits and continuation.
- AC-004 — Explicit current/latest, include-merged and historical reads have published selection semantics across service, CLI and MCP. Current/latest means justified canonical current knowledge, never maximum ingestion time. Merge and supersession are labelled separately from archive/refutation/review. No new decision means existing default calls and evidence versions remain unchanged.
- AC-005 — Repeated applications, replay with a different transport request ID, concurrent clients and process failure cannot create multiple active decisions or cycles. Canonical resolution and pagination have finite bounds and visible overflow; missing or invisible targets do not disclose foreign identifiers/counts.
- AC-006 — Audited correction/unmerge is version-bound, atomic and idempotent, releases only the intended decision, and never clears an independent refutation, expiry, withdrawal, scope restriction or later decision. A source change after preview conflicts or makes the relationship visibly stale; it is not silently accepted.
- AC-007 — Applying/correcting/changing an anchor coherently invalidates affected current retrieval, profiles, thematic summaries, aliases, patterns and cached derived outputs. No path re-exposes a withheld/invalid inference. Event consumers can observe a stable, committed audit/history record; this issue does not add the webhook delivery engine from6.14.
- AC-008 — Reader/writer separation and current principal/domain/project authority hold for preview, apply, correction, details, history, search, graph, derived views, errors and counts. Privilege revocation before commit aborts all changes. Local and central transports agree.
- AC-009 — Populated0.6.18→0.6.19 upgrade, empty retry, old-code reads/writes and documented recovery are rehearsed on owned multi-user/multi-domain copies. All original rows/evidence/grants/owners and relationships are preserved. Unsupported or unsafe downgrade is refused or explicitly fenced; restoring a pre-upgrade backup does not claim to preserve later writes.
- AC-010 — Freeze known expected outcomes before product changes. Publish2–3 human-inspected scenarios, false-merge/non-merge counts, source retention, retrieval changes, timings, concurrency/replay outcomes and exact source revisions/sample sizes. Synthetic deterministic results are not actual-model accuracy; #21 sustained-use work stays open.

## Functional requirements

- FR-001: Extend existing duplicate curation and temporal assertion/evidence rules; do not add a parallel knowledge engine, another worker or a model requirement.
- FR-002: All durable changes pass through audited gateway operations; retained originals remain addressable as originals. Canonical membership does not confer independent corroboration or confirm truth.
- FR-003: Optional consolidation beyond the existing exact-duplicate baseline is opt-in. Migration performs no provider call, automatic merge or historical backfill.
- FR-004: Each operation has bounded input/output, page, chain, candidate and lock/time budgets. Ambiguous or excessive work returns an actionable review/conflict/budget result rather than partial truth.
- FR-005: Ship user/config/tool documentation, a system upgrade/operate/correct/recover playbook and exactly one patch bump to0.6.19 relative to target main.

## Compatibility boundaries

- Baseline: merged `d4d2372`,0.6.18/schema030. Preserve existing `as_of/history`, source-evidence and graph-default contracts unless an explicit new view is requested or a caller applies a documented lifecycle decision.
- Existing `memory_get` remains original-record inspection when no view is supplied; explicit current resolution must identify requested versus canonical original. Historical citations never silently redirect to another source.
- No data deletion, source/evidence transplantation or forced re-embedding. New lifecycle state is additive and starts empty.
- The upgrade path must define old/new direct-reader and writer combinations both before and after first use, including stale loaded processes. Do not infer compatibility from startup alone.
- All destructive/failure/recovery/load tests use isolated owned synthetic stores, never5432 or production. No external-provider/private-corpus work is implied.

## Interface contracts

| ID | Boundary | Input | Observable output/invariant |
|---|---|---|---|
| IC-001 | Operator/client → preview | scoped anchors and requested operation | five-way classification, exact versions, support and required approval; no writes/provider |
| IC-002 | Writer → audited gateway | inspected versions, operation/reason, stable action identity | one atomic decision/history/audit effect or conflict; current authority rechecked |
| IC-003 | Reader → lifecycle-aware retrieval | optional explicit view/as_of and bounded anchor/page | labelled canonical/current/merged/historical originals; no scope or evidence weakening |
| IC-004 | Upgrade/recovery → populated store | supported source inventory and verified backup | additive data-preserving migration, empty retry, explicit old-code and post-write recovery limits |

## Edge cases

Equal-time contradictions; old event imported late; richer text about a different entity;
same body in another domain/project; legacy/unmanaged evidence; source ABA; target edit,
withdrawal, expiry or scope move; chains and attempted cycles; concurrent opposing merges;
correcting an earlier link after a later one; source deletion; conflicting replay payloads;
RO/future-revoked callers; budget/chain exhaustion; interrupted commit and backup restore.

## Assumptions and decisions

- Operator review authorizes a decision; it does not mathematically prove semantic equivalence. Structural validation must say so. No unmeasured semantic classifier is introduced.
- Current/latest are aliases for the justified canonical present, not alternative recency heuristics.
- Existing raw original/evidence inspection and explicitly labelled history are distinct from current factual retrieval.
- Scope and compatibility policy may be strengthened by the design gate before task generation; no product behavior is implemented in this phase.

## Success measures

- SC-001: zero false automatic merges in frozen cross-entity/cross-scope/contradiction fixtures; report rejected legitimate cases separately.
- SC-002:100% original-row/source retention in the declared upgrade and operation corpus; zero duplicate applications/cycles in declared concurrent/replay tests.
- SC-003: current and historical view labels/selection exactly match frozen expectations, including delayed imports and source invalidation.
- SC-004: collaborating-component success and rollback/recovery probes plus full relevant tests pass on a frozen revision; no open C/H/M finding before PR/merge.

## Playbook obligations

PB-066-OPS, system deliverable at `docs/playbooks/system/rag-066-memory-lifecycle.md`.
Audience: standalone/central operator. Origin: US-003/004, AC-006/009, IC-004.
Must cover populated upgrade, direct-client compatibility/restarts, preview/approve,
canonical/current/history inspection, correction, stale/budget failures and verified
recovery with post-backup-write limits. Content review and isolated executable
rehearsal are both delivery gates, not substitutes for live rollout evidence.
