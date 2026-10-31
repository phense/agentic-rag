# Feature Specification: Opt-in source-linked pattern suggestions

## Stable work ID

- Feature ID `6.7`; work ID `RAG-065`; [Issue65](https://github.com/phense/agentic-rag/issues/65), roadmap58 step7/15.
- Artifact: `docs/specs/6-7-pattern-synthesis/spec.md`.
- Status: Accepted under the maintainer's existing end-to-end implementation authority. Specific PR merge and production activation remain separate.
- Source request: discover recurring patterns across eligible original memories as explicitly inferred, reviewable suggestions, retaining original support and bounded operation.

## User scenarios

### US-001: Preview a scoped synthesis before enabling it (Priority: P1)

A scope writer can inspect eligible original support and budgets without a provider call or canonical mutation. Synthesis is off in an existing or fresh installation until explicitly enabled for a concrete domain/project scope. Enablement records a forward boundary; historical analysis is a separately requested, bounded operation.

Independent test: migration and ordinary maintenance on a populated installation neither call a provider nor create a pattern. Preview excludes inaccessible or unsupported originals and leaves table hashes unchanged.

### US-002: Receive a reviewable hypothesis with original support (Priority: P1)

Bounded scheduled work can suggest a recurring configuration cause from several independent original observations. Each part links to exact, versioned source spans. The suggestion remains inference rather than a new user statement, independent confirmation, or automatically accepted operational truth. Ambiguity, insufficient evidence and conflict may produce a recorded non-conclusion.

Independent test: a known-pattern fixture produces one explicitly inferred suggestion with exact support; repeated assistant paraphrases, duplicate imports and prior patterns cannot satisfy independent corroboration.

### US-003: Retry and stop safely (Priority: P1)

Worker death, provider failure, duplicate submission and disable/re-enable do not duplicate canonical patterns or lose accepted results. Disabling a policy stops generation and withholds its current suggestions without removing originals. Ordinary retrieval and previously installed clients continue to work.

Independent test: a paid-for accepted provider result survives an injected apply failure, is reused on retry, and creates at most one pattern and one application audit. Disabled or revoked work cannot commit.

### US-004: Follow a pattern to current evidence (Priority: P1)

A reader can inspect a pattern and drill down through the source-evidence contract from63, only while all required support remains visible and current. Source correction, withdrawal/reinstatement, expiry, supersession, document editing and scope loss immediately withhold affected suggestions. No stale body, graph route, direct lookup or cache may bypass that rule.

Independent test: mutate or revoke one required original, then inspect the pattern through local and central surfaces. The suggestion is withheld and no inaccessible support, count or locator is disclosed. Originals and history remain intact.

## Acceptance criteria

- AC-001 — Default-off configuration plus an explicit domain/project policy controls generation. Preview is provider-free and read-only. Enabling records an unambiguous forward cutoff; backfill needs explicit bounded parameters. No global cross-scope join is implicit.
- AC-002 — Candidate originals satisfy existing claim/assertion/source eligibility and source-evidence version rules. Incomplete, assistant-only, manually attested, legacy-unknown or derived support does not count as independent original corroboration. Default minimum: three distinct qualifying original user events across at least three original memories, also deduplicated by normalized exact-quote content across imports. Conservative rejection is preferable to invented independence.
- AC-003 — Every generated supported part cites exact known source/span/version references. Unknown, missing, edited or injected citations cause rejection/non-conclusion. Evidence references are verifiable support, not an automated proof of the model's reasoning; operational conclusions remain reviewable hypotheses.
- AC-004 — Inference confidence, evidence review and factual status are independent fields. Patterns cannot become stated user evidence, cannot feed synthesis again, and cannot automatically confirm themselves. Conflicting/insufficient fixtures produce explicit non-conclusions rather than false certainty.
- AC-005 — Stable application identity binds policy version, canonical scope and sorted original evidence versions. Retry, concurrency and worker recovery create no repeated pattern. Accepted provider output is durable before canonical application and reusable without a second provider call. Originals and existing audits remain unchanged.
- AC-006 — Eligibility and source versions are revalidated before application and on every exposed read, including after time-only expiry and withdrawal/reinstatement. Scope revocation and policy disable fail closed. No recursive dependency cycles are permitted.
- AC-007 — Use the existing local/central singleton worker and provider/authorization fences, finite candidate/span/input/output/time/batch/retry/concurrency limits, visible status and bounded error output. No new client-side model/worker, unbounded scheduler, or implicit provider call from retrieval.
- AC-008 — Authorized local CLI/MCP and shared REST/remote-MCP contracts provide preview, enable/disable, bounded status/list and original drill-down. Read-only clients may inspect/preview but cannot enable, backfill, enqueue or apply. No host-local transcript paths become navigation.
- AC-009 — A populated0.6.17/schema029 source upgrades additively without running synthesis, re-embedding or altering original data. Independently restored backup, migration retry, actual old-code reads, disable and recovery have executable evidence for standalone and central modes.
- AC-010 — Frozen synthetic known-pattern, false-pattern and contradictory-source fixtures yield human-inspected2–3 before/after examples, supported/unsupported claim counts, non-conclusions, actual provider usage and resource/timing observations. Clearly separate mocked correctness from actual-model quality and target-hardware claims.

## Functional requirements

- FR-001: Offer opt-in authorized scoped scheduling with deterministic preview and explicit history boundaries.
- FR-002: Generate only derived, source-linked, reviewable pattern suggestions without promoting evidence or mutating originals.
- FR-003: Persist accepted work and application identities for bounded, idempotent recovery.
- FR-004: Enforce current support and authority at application and every read, preserving the existing evidence contract.
- FR-005: Deliver measured examples, verified populated upgrade and operator enable/disable/recovery guidance.

## Compatibility boundaries

Source0.6.17/schema029, target0.6.18 with additive migration only if required. Existing CLI/MCP tools and legacy arguments remain callable; old clients neither enable nor start synthesis. Existing data, permissions, pins, checkpoints, source versions and history are retained. No canonical writes outside the audited gateway. No destructive downgrade; after new target writes, restoring an old dump alone cannot preserve them. No production rollout is part of this issue implementation.

Provider selection reuses the configurable provider boundary from61; no new provider dependency or private-corpus provider evaluation. Synthetic fixtures only for new model calls. Finite budgets apply in standalone as well as service deployments.

## Interface contracts

| ID | Boundary | Input | Observable output/invariant |
|---|---|---|---|
| IC-001 | Scope policy/preview | Explicit domain and canonical project/global scope, bounded limits | Eligible original references, independence counts, forward boundary and budgets; no provider/write for preview |
| IC-002 | Durable worker | Authorized versioned policy and finite source snapshot | Accepted result/non-conclusion, idempotent application receipt and bounded usage/status |
| IC-003 | Pattern inspection | Visible pattern anchor, bounded page | Derived label, separate confidence/review/status, current part-to-source evidence references or withheld response |
| IC-004 | Existing clients | Old tool signatures and populated data | Preserved behavior; feature disabled until explicitly opted in |

## Edge cases

Duplicate import under a new namespace; several spans from one event; repeated assistant copies; manual sources marked user; truncation; no qualifying evidence; output without citations; output with foreign IDs; provider output prompt injection; contradictory values; shared sources; expiry without writes; document/source ABA edits; graph/direct-get bypass; policy changed during inference; actor credentials revoked before commit; worker killed after acceptance or application; ordinary old writers on the new schema; accepted work exceeding a new budget; disabling/re-enabling without implicit backfill.

## Assumptions and unresolved decisions

The existing authorized scopes and source trust model are authoritative. This release starts with suggestions and explicit non-conclusions, not autonomous operational decisions. The initial minimum is deliberately conservative; configurable limits may raise it, but must not weaken independence below the stated floor. A dedicated dashboard pattern editor, semantic truth oracle and automatic historical backfill are outside scope. No material user decision is outstanding.

## Success measures

- SC-001: Zero pattern/provider activity in tested default-off/migration/ordinary-read cases.
- SC-002: Zero duplicate applications across tested retry/concurrency/recovery cases; exact original fields preserved in upgrade/restore.
- SC-003: Zero unauthorized or stale required-support disclosures across tested transports and lifecycle cases.
- SC-004: Publish actual sample sizes, support errors/non-conclusions, provider counts, timings and clear fixture/model/hardware limits; no invented accuracy gain.

## Playbook obligations

PB-065-OPS (system): operators enabling forward synthesis, requesting bounded backfill, disabling a policy or recovering accepted work. OriginFR-001/003/005; canonical `docs/playbooks/system/rag-065-pattern-synthesis.md`. Include0.6.17 upgrade/preflight/verified backup, pause/restart/ordered migration, policy preview/enable/status, provider outage/accepted retry, disable, integrity checks and restoration limits. Independent content review and executable isolated populated-copy rehearsal before PR handoff. This is one medium standalone procedure, not a new documentation set.
