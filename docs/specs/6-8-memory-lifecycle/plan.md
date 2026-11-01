# Implementation Plan: Source-preserving consolidation and lifecycle views

## Stable work ID

- Feature6.8 / RAG-066 / Issue66 / roadmap8of15.
- Specification: [spec.md](spec.md).
- Baseline: `d4d2372`,0.6.18/schema030; target0.6.19/schema031.
- Planning status: coordinator approach accepted for architecture analysis; tasks and product implementation follow the design gate.

## Summary

Add a small reversible lifecycle overlay and audited gateway, not physical document
merging. Reuse existing assertion event-time/evidence predicates and original source
contracts. Retain exact originals; canonical links and explanations live separately.
A deterministic preview makes five operation types explicit. Only proved exact
matches qualify for automatic policy; semantic/extension/replacement decisions are
explicitly reviewed. Contradictions remain unresolved visible records.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Current baseline and branch isolation | merged PR88/main d4d2372; clean feat/memory-lifecycle-66 in existing isolated worktree | pass |
| One audited store and genuine RO tools | store.py, mcp_server.READ_TOOLS/WRITE_TOOLS, service.engine/context | preserve |
| Data preservation and old-code compatibility | service.upgrade, schema.py, tests/service/test_synthesis_upgrade.py real-source harness | required031 rehearsal |
| Exactly+1 patch and docs | pyproject/uv.lock/README/CHANGELOG0.6.18 | target0.6.19 in this PR |
| Independent review and source-bound verification | AGENTS.md; existing owned PG55460 | delivery gate |
| Merge policy | maintainer explicitly permits remaining6.x autonomous merges after tests/review/upgrade | no per-PR wait; no automatic production rollout |

## Technical context and repository evidence

Python3.13/PostgreSQL17+pgvector. Existing curation archives exact same-body legacy
copies and adds duplicate_of; immutable facts/claims are excluded (curation.py:64).
validity.save orders explicit replacements by event time within domain/project;
claim/evidence qualification remains authoritative. store.get_document is original
inspection; search defaults current while unparametrized graph defaults historical.

Read-only independent inventory found: all SQL candidate families and managed-index
paths must apply selection before LIMIT; a post-filter alone can starve results.
Current profile/thematic/pattern revisions do not automatically include independent
new lifecycle rows. QueryCache stores vectors only, so SQL remains current authority.
service.upgrade accepts sources only through0.6.17 and restore-resume has an explicit
allowlist. Add0.6.18 support, new tables to schema/RLS checks and restore allowlist.
Do not change already-published SQL001..030 or frozen earlier feature fixtures.

## Data ownership and lifecycle design

New `agentic_rag/lifecycle.py` owns bounded preview, classification, version-bound
application, correction and read-only detail/history. Thin `store.py` methods are
the audited write boundary. Additive031 stores immutable decision identity/anchors,
operation/classification/reason/inspected versions and append-only activation or
correction history; a minimal current-state index may reference these events.
Use UUIDs rather than new sequences, preserve originals/evidence and avoid invented
legacy lifecycle history. Existing duplicate_of and supersedes edges remain readable
as existing legacy relationships, explicitly distinguished from new decisions.

Both anchors must remain readable and writable for mutations and in the same
known domain/project. Canonical chains cannot leak an invisible target. Lock scope
and affected records deterministically; database-level guards must reject cycles
and unsafe moves even under concurrent writers. Expected versions bind content,
evidence, scope and monotonic decision state, including ABA; a replay key cannot
be reused with another payload. Correction closes only its own active decision,
never modifies independent truth/source/expiry state, and never deletes an original.

The design gate selects flat one-hop groups, separate `lv1` optimistic versions
and immutable base snapshots. `lv1` includes the append-only lifecycle event count
for action ABA; the base snapshot used by hiding excludes that count, so an action
never stales itself or other group members. Both bind portable content/evidence/
state/scope versions. Compare full base snapshots (not only `updated_at`) to catch
source ABA. Leave existing ev1/src1 untouched on migration and overlay operations.
New anchors exclude immutable assertions/alias definitions/synthesis; existing
assertion operations and legacy duplicate relationships remain explained by detail.
The existing automatic legacy exact curation is tightened to require identical
non-empty body, title and dtype, not merely a same-body pair. Its source preservation,
archive/edge/audit behavior stays. No new automatic semantic applier is added.
Design findings AF-066-001..010 are explicit implementation obligations.

## Selection and invalidation

Add optional explicit view fields to supported reader signatures and omit unset
fields over the wire for old servers. Resolve view/as_of/history centrally, reject
contradictory combinations, preserve each existing omitted-view default.
Current/latest excludes explicitly merged/superseded members while preserving all
existing claim/source/temporal gates. Include-merged adds merged originals, not
invalid/expired/future/refuted truth. Explicit historical results label retained superseded or expired accepted past
observations, enforce current source trust and exclude future/refuted/withdrawn
truth; omitted legacy history keeps its old contract. `include_merged` widens only
duplicate/extension hiding, never replacement. A replacement stays suppressive
until explicit correction even if its target is missing; duplicate/extension stale
or unavailable relationships resurface members only through their own truth gates.
Original get/evidence remains inspection, not a silently redirected citation.

Integrate SQL eligibility before candidate LIMIT across raw/contextual/managed
indexes, identity shortcuts and graph expansion. Re-evaluate after expansion and
under current authorization. Include scoped lifecycle revision/current eligibility
in profile/thematic/alias/pattern dependency/cache checks; applying/correcting a
link cannot leave an old derived result presented as current. Query vectors need
no global clearing. Atomic lifecycle events and audit provide the future event
consumer seam; no webhook delivery is implemented here.

## Interface contracts

| ID | Producer → consumer | Planned change | Failure behavior |
|---|---|---|---|
| IC-001 | CLI/MCP/REST → lifecycle preview | pure bounded pair preview, classified support/versions/approval | same missing/foreign response, no writes/calls |
| IC-002 | writer → store → lifecycle/SQL | apply/correct with expected versions and semantic replay identity | conflict/denial rolls back state+history+audit |
| IC-003 | explicit view → current candidate and original-reader seams | central selector plus bounded detail/history, optional wire fields | invalid combinations rejected, no candidate leakage/starvation |
| IC-004 | service upgrade → schema031/real0.6.18 clients | source support, new RLS/restore inventory and verified local/central rehearsal | refuse unsupported/unsafe path before mutation |

## Implementation ownership and dependencies

One serialized implementation owner for the cohesive feature; no parallel writers
or pytest runs. Owned feature files: new lifecycle module/031/tests/benchmark/docs;
necessary scoped edits in store, retrieval/graph/derived readers, MCP/CLI/service
transport/schema/upgrade, version files. Coordinator owns requirements/task state,
independent reviews, integrated full tests, PR and merge. Existing worker/provider
seams remain; no new daemon, external package or model download.

Order: freeze labelled fixtures → storage/gateway/rollback → view+invalidation
integration → transports → populated upgrade/recovery → measurement/user/playbook
docs/version → independent full-slice and architecture probes → final full tests,
wheel/lock/links → PR and merge with green checks. Only disjoint read-only inventories
run concurrently; their outputs are integrated before coding.

## Tests and evidence

- Baseline: existing curation, validity, domain-assertion and evidence-invalidation tests on owned PG55460; final main suite already passed1974/1skip/1warning before the branch was created.
- Meaningful original reds before each new behavior, no retroactive TDD claim. Freeze false-merge/richer/contradiction/late-import/multi-scope labels in git before product changes.
- PostgreSQL apply/correct replay, opposing concurrent chains/cycles, stale preview/source ABA, revoked writer, incomplete evidence, bounded overflow and injected audit failures.
- Reader parity: local/central REST and MCP, CLI/client; RO tool restrictions, scope errors, actual old source code; all retrieval branches and derived caches tested against stale relationships.
- Upgrade: use existing owned_source/old_tree/run_old machinery pinned to d4d2372 with30 migrations and representative multi-user source/pins/history/queue data; verified backup restore, original-row/ACL hashes, interrupted retry and empty reapply. No automatic consolidation/provider calls.
- Measurements: known exact/richer/false merges, explicit replacement versus delayed old import, correction/replay recovery; original/evidence retention and retrieval before/after; three deterministic repetitions and disclosed sample/limits. #21 remains separate.
- Final: full pytest once per final integrated source, Node adapters, offline wheel179+newpayload/SQL/assets/version smoke, uv lock, relative links, clean diff and actual GitHub checks. Failed/interrupted outputs remain retained.

## Architecture questions and required responses

1. Where do version/current-chain/authorization gates run so RLS cannot hide a cycle or expose a foreign canonical target?
2. How do all candidate and original/derived reader paths distinguish current versus intentional history without changing omitted-view defaults?
3. How does link correction/source change invalidate existing65 patterns/profile/thematic/alias caches without rewriting original evidence or changing all untouched ev1 versions?
4. Which old0.6.18 operations remain valid before/after first use, and which restart/code-rollback boundary is necessary? Prove with real old code.

Answer in `docs/uml/memory-lifecycle-66.md` and stable AF-066 entries in
`docs/uml/findings.md`; derive collaborating-component success and rollback probes.
Only a justified compact contract under this feature's contracts/ is conditional;
no generic research/data-model/quickstart document is needed.

## Playbook obligations

PB-066-OPS, system, `docs/playbooks/system/rag-066-memory-lifecycle.md`, operator
owner with independent content reviewer. Deliver after gateway/transports/upgrade
are implemented, before PR; rehearse the published CLI/REST actions on owned copies,
including correction and failure/recovery, not just internal functions. Preserve
old-client/restart and post-backup-write limits. No separate development playbook:
all development operations are owned synthetic database tests using existing isolation
and cleanup helpers, with no production execution or special manual cutover here.

## Coordinator design dispositions

Accepted AF-066-001 exclusions and legacy-archive distinction with the specification
clarifications above; existing assertion lifecycle remains in unified detail and
uses its original audited gateway. Accepted one-hop groups and no new automatic
applier. Corrected D2/D6 view semantics, D7 replacement persistence and full
source/content snapshots, and D5 conservative legacy exact-title/type proof.
These are source-grounded safeguards, not requirements waived to fit the code.
AF-066-009/010 record the added curation and snapshot tests. No application code
changed during planning; the independent implementation review checks these too.

Worker compatibility refinement: upgrade/restart every automatic-curation worker
and hook launcher as part of the existing fence/cutover. Old0.6.18 ordinary clients
may be supported only through the explicit compatibility tests; old-code fallback
must set `curation_budget=0` and prove no differently titled auto-merge. Do not
claim a schema overlay changes old Python policy. PB-066-OPS includes this gate.
