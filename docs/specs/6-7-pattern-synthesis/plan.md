# Implementation Plan: Source-linked pattern suggestions

## Stable work ID

Feature6.7 / RAG-065 / Issue65; [specification](spec.md). Target0.6.18; source main0.6.17/schema029 @81beaf6. Accepted under end-to-end authority; specific PR merge and deployment remain separate.

## Summary

Add a small synthesis subsystem behind explicit scoped policies. Reuse canonical source-evidence versions, audited writes, the existing singleton worker, structured provider adapters and central authorization. Persist finite accepted output before applying one derived suggestion. Revalidate support on publication and inspection; do not create a second truth store or run a model during retrieval. Initial output is a suggestion, not automatic truth.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Base | origin/main81beaf6, previous PR87 merged, clean isolated checkout | Verified |
| Baseline | evidence-contract/thematic/service-scope tests, PG55460 | 64 passed, exit0,28.26s |
| Shared engine / writes | AGENTS.md; store.py, evidence.py, service.engine/context | Reuse gateway and transaction/revocation fences |
| Compatibility | Source0.6.17/schema029; current upgrade operator allowlist ends0.6.16 | Add tested0.6.17 source support rather than mislabeling new evidence |
| Review | Complete feature diff, SQL/RLS/concurrency and system integration | Independent review required before PR |
| Publication | Step7/15; Low75 | One PR; await new weiter; no production changes |

## Technical context

Python3.13, PostgreSQL17/pgvector. `evidence_contract.py` computes portable ev1/src1 versions from persisted values; migration029 supplies revision/history triggers. `thematic.py` offers bounded extractive views but is not synthesis and cannot prove evidence independence. `store.save_claim` accepts `kind=inference`, preserves quotes and supports `commit=False`; claim_eligible excludes unreviewed inferences from ordinary retrieval. `documents.dtype=synthesis` already exists. New derived identity must survive any later review and never be used as independent evidence.

`jobs.py`/`worker.py` provide durable mining_queue, retry/provider backoff and cross-host advisory authority. `service.worker` re-resolves credential references and applies request scopes; `ServiceConnection` checks current authority on commit. `service.engine` discovers MCP signatures for REST and server-MCP. `cli.py` has local and client dispatch. Reuse these paths; do not introduce a second worker or client-side inference.

## Compatibility boundaries

Use one additive030 migration for scoped policies, finite accepted batches/application identities and dependency references. Preserve all original rows; no automatic policy enablement, generation, content rewrite or re-embedding. New central startup must validate its required schema/RLS. Actual old0.6.17 reads are a compatibility probe only before patterns exist. Before synthesis activation, stop, inventory, upgrade and restart every local/central reader and agent/MCP process at0.6.18; record the commands and observed process versions. Once a pattern exists, code-only rollback on030 is unsupported because old get/evidence/history/graph paths cannot enforce withholding; use new-code disable/repair or the verified pre-upgrade restore with post-backup-write reconciliation. Upgrade.SUPPORTED_VERSIONS must recognize0.6.17; do not substitute a false source label in new tests.

Default `[synthesis] enabled=false` is a global safety switch in addition to explicit scoped policy opt-in. Fresh and upgraded stores contain no enabled policy. Enabling records server time as forward boundary; re-enabling must not quietly sweep disabled history. Backfill requires explicit finite start/end parameters and authorization. Runtime config rollback/disable does not delete originals or accepted output. Schema downgrade after new writes is unsupported.

## Interface contracts

| ID | Producer | Consumer | Design / failure behavior |
|---|---|---|---|
| IC-001 | Scoped policy + eligibility selector | Preview/scheduler | Concrete domain and normalized project/global selection; visible qualifying originals only; deterministic preview has no model/write |
| IC-002 | Bounded snapshot + versioned policy | Structured provider / durable batch | Sorted portable evidence versions, independent user-event and normalized-quote identities; finite schema; exact citations; accepted response staged once |
| IC-003 | Audited apply | Pattern inspection and ordinary retrieval gates | Inference/suggestion label; part-to-source dependencies; current authority/version/expiry required; stale or inaccessible support fails closed |
| IC-004 | Existing worker and engine | Local/central tools | Same provider, job/revocation/fence logic; RO inspection only; no implicit synthesis via old calls |

Exact tool names/fields belong in a small `contracts/pattern-v1.md` authored alongside implementation. Prefer a small explicit family (preview/configure/status/list/inspect/backfill) over a multipurpose unvalidated request dict. Remote CLI and MCP use the same functions. Operator status and public responses omit transcript namespaces/paths, credentials, prompts and raw provider errors.

## Ownership and data lifecycle

One serialized implementation owner owns the tightly coupled SQL, synthesis core, worker scheduling, gateway, config and transport seams. Coordinator owns spec/plan/tasks, architectural findings/state, final integration, review and publication. No concurrent writers or pytest processes.

New policy/batch/dependency tables have finite bounded payloads, authorized read/write rules and update guards consistent with service.context/schema validation. No security-definer helper may expose private joins; any narrowly necessary helper must use a fixed safe search_path, scoped predicates, restricted privileges and explicit independent SQL review.

Candidate selection requires current eligibility plus exact original qualifying user spans. Exclude previous patterns (`dtype=synthesis`/durable derived registry), legacy-unknown, manual attestations, assistant-only and truncated support. Minimum three distinct original events across three distinct memories, with normalized quote-content deduplication across namespaces. Cap candidate memories12, spans8 per original, exact quote4000chars with a stricter aggregate provider input limit; raise floor if necessary rather than guess independence. Preserve quote bytes; normalize only independence keys. Source-contract versions must be used, never xmin as persisted identity.

Durable application key hashes canonical scope, semantic generation-policy parameters and sorted source/span/ev1/src1 identities, excluding the incidental enable/disable version counter. Persist accepted result once before canonical application. A retry of accepted work must not call the provider again. Revalidate current source versions/eligibility, policy and authority before gateway application; atomic derived document + dependencies + application audit prevents half-published suggestions. Concurrent identical jobs serialize through existing worker/database authority plus a unique application key. Only originals may be dependencies, so cycles are structurally rejected.

Withhold on dependency drift immediately, including time-only expiry and source ABA; ordinary direct reads, search, graph and derived views must not bypass withholding if a stored inference is later confirmed. Keep inference confidence distinct from review state and truth. Either a canonical eligibility predicate or a comparably complete read boundary must guard every affected surface; checking list only is insufficient. Disabled suggestions remain retained but unavailable as current support. No silent source mutation or auto-confirmation.

## Scheduling and resource budgets

Use the existing worker tick; no provider at migration/startup/preview/retrieval and no autonomous timer outside the existing maintenance supervision. Schedule at most one due job per scope/policy interval, with a hard finite per-tick policy/job cap and visible pending/error/non-conclusion state. Document finite policy capacity and accepted-output retention under existing storage admission.

Default limits: one provider call per batch, timeout30seconds, aggregate input12000characters, output1024tokens, max3suggestions per response and finite per-part citations. Reuse llm.run_structured and61 provider dispatch; expose bounded synthesis-specific overrides of provider/model/time/input/output through Config without hardcoding a new backend. Enforce bounds before invocation and before persisting/applying output. Provider outage follows existing finite retry/backoff; revocation/disable before commit blocks application. Synthesis uses background priority and existing worker authority/resource checks.

The forward cursor must be explicit and resumable: distinguish source arrival from event time; avoid skipping unprocessed candidates at a batch boundary. If a bounded selection cannot cover the scope, status exposes continuation/omission rather than claiming complete analysis. Backfill is a separate explicit finite window, never a migration side effect.

R65-02/03/06 correction: replace cursor-only consumption with a scoped, durable processed-original membership at the policy enable epoch, recording it atomically with terminal analysed outcomes. Late commits remain discoverable independently of the maximum seen timestamp. A partial scan must continue without starving later eligible originals; do not mark ineligible or unseen originals analysed. Re-enable starts a new forward epoch, while explicit backfill remains finite. Build an input-budget-fitting selection before creating a provider run; defer the remainder. If even the minimum independent group or one original cannot fit, expose a bounded blocked reason and leave the unanalysed originals pending until a documented budget/re-analysis action. Do not repeatedly pay for unchanged context alone. When new originals arrive, fill remaining candidate capacity with bounded recent eligible context from previous runs (prefer originals not already represented by a current pattern); context does not count as newly processed work. Cap total memories at12 and enforce the same independence, exact-version and input limits. Publish the finite window's remaining limits and add an actual cross-run recurrence regression.

## Dependencies

Issue63 is merged;61 provider seam and existing SQL eligibility are available. No Mem0 dependency, external service, new model download or destructive production operation. Existing private installations are not evaluation fixtures.

## Tests

- Test-first: default-off/preview no mutation or provider, evidence independence and exact citations, false/conflict non-conclusions; freeze synthetic dev/held-out fixtures before product code.
- Real isolated PostgreSQL: policy scope/RLS/RO, source edits/withdrawal/reinstatement/expiry/supersession, confirm-and-retrieve/graph bypass, duplicate imports, derived recursion, accepted retry/concurrent application and audit rollback.
- Worker/service: scoped credential propagation, revoke/disable while provider runs, actual queue/fence and provider outage recovery; no separate central singleton.
- CLI/MCP/REST/server-MCP/client-proxy parity, bounded pages/errors and no guessed-ID oracle.
- Populated standalone and central0.6.17→0.6.18 migration, original fields/ACL/history preservation, verified backup/restore, empty migration retry, actual old-code read/feature-off rollback; use owned PG55460 only.
- Freeze labels, inspect2–3 actual example outputs, count supported/unsupported parts and non-conclusions, exact provider calls and repetitions/timings. Mocked model correctness is not a real-model quality claim; any real-model synthetic evaluation reports model/revision and failures separately.
- Final full pytest actual exit, Node adapter suite where relevant, wheel/SQL/assets and exact version/README/lock consistency. Do not claim a running suite green.

## Architecture findings

AF-065-001 evidence identity/anti-recursion; AF-065-002 accepted-output transaction and retry; AF-065-003 current authorization and dependency invalidation. See `docs/uml/pattern-synthesis-65.md` and `docs/uml/findings.md`. All map to S1 implementation and independent S2 success/recovery tests.

## Supporting artifacts

One formal pattern-v1 contract is justified by durable work and new shared tool surfaces. One sequence model answers the acceptance/application/revocation ordering question. No generic research or deployment catalog is needed. Synthetic benchmark and public verification live under `docs/benchmarks/2026-10-31-pattern-synthesis/` and `docs/verification/issue65-pattern-synthesis.md`.

## Implementation structure

S1 is one cohesive owner: `agentic_rag/synthesis.py`, additive `sql/030_*`, audited `store.py` gateways, `config.py`, `jobs.py`/`worker.py`, relevant service worker/schema/upgrade/engine and MCP/CLI/client adapters, meaningful tests/fixtures, contract/user docs, PB-065-OPS and exact0.6.18 version files. Changes to shared eligibility SQL/functions need bounded regression coverage of all existing consumers. No edits to live configs, launchd/systemd, credentials or other repositories.

## Playbook obligations

PB-065-OPS is the system deliverable named in the spec, owned by S1, reviewed and rehearsed on an owned populated multi-domain copy before delivery. It covers migration and recovery and must match actual commands. Development operations: none beyond automatically cleaned owned isolated test/restore databases; no live rollout, coordinated cutover or private-corpus transfer. Reassess before any scope expansion.
