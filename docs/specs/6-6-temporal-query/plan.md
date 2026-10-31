# Implementation Plan: Explainable EN/DE temporal search

## Stable work ID

Feature6.6 / RAG-064 / Issue64; [specification](spec.md). Artifact: `docs/specs/6-6-temporal-query/plan.md`. Accepted under existing end-to-end authority; production and future PR merge remain separate.

## Summary

Add a bounded deterministic calendar parser and one temporal candidate stage around the existing search engine. Keep existing eligibility SQL and RLS authoritative. Use stdlib datetime/zoneinfo, canonical fact/source timestamps, stable matching-first preference and explicit strict filtering. No new dependency, provider call or schema.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| Approved source | main8772fbd, mergedPR84; tree equals approved2a1dac1 | Verified |
| Baseline | tests/test_search.py tests/test_validity.py tests/service/test_scope.py; PG55460 | 26passed,exit0,15.01s |
| Production compatibility | AGENTS.md; current0.6.16/schema029 | No migration; populated old-client/code rollback proof required |
| Independent review | Complete bounded diff and architecture-derived success/recovery | Required before PR |
| Version | Targetmain0.6.16 | Exactly0.6.17 in pyproject/lock/badge/changelog |
| Publication | Step6of15, Low75 | Wait NEWweiter for this PR; no deployment |

## Technical context

Python>=3.13 (actual3.13.13), PostgreSQL17+pgvector. search.py returns hits/warnings and selects up to150 candidates through managed/contextual/base routes; exact selectors and optional neural reranking precede diverse/k and optional graph expansion. validity.py and SQL020/023 govern assertion eligibility; fact_assertions.event_at and knowledge_sources.source_at are canonical, documents.created_at/updated_at are not event time. evidence.py owns source trust/claim evidence. service.engine builds tool validation from mcp_server signatures and supplies existing transaction/RLS scope. cli.py has both local search and remote command dispatch. Config is a frozen dataclass with TOML prefix mapping.

## Compatibility boundaries

Default `[temporal] enabled=false`, timezone UTC. Request modes auto/off/prefer/filter: auto consults server/local config; off always bypasses; explicit prefer/filter opt in. An aware reference and IANA zone are additive options. Old arguments and result fields remain unchanged; avoid unconditional new SearchHit fields in legacy JSON. Search's existing tuple can be retained with an optional per-call diagnostics output dict; add the top-level temporal envelope only when active interpretation/ambiguity merits it. Per-hit explanation can be nested in existing evidence only for active intent. Server config is authoritative for remote clients; remote CLI must avoid sending new defaults to old servers when no temporal option was requested.

No schema change, no database version relaxation. Config/code rollback must be tested on a populated synthetic schema029 store using actual archived0.6.16 source. Original rows, source timestamps, accounts/scopes/audits remain unchanged. Feature-off behavior is tested with an intentionally inaccessible temporal metadata path to ensure bypass. Long-lived processes need restart only to load new code/config/signatures, not a live action in this PR.

## Interface contracts

| ID | Producer | Consumer | Change | Failure behavior |
|---|---|---|---|---|
| IC-001 | CLI/MCP signature | Local search and central generic dispatcher | Optional temporal mode/reference/timezone | Invalid options yield bounded ValueError/400; legacy calls unchanged |
| IC-002 | New temporal.py | search.py | Immutable normalized interpretation | Finite query length/grammar, explicit ambiguity, hard mode fail-closed |
| IC-003 | Canonical timestamp query | Rank/filter stage | Batch only eligible visible IDs, at most candidate+graph budget | Unknown remains unknown; soft safe warning on unavailable metadata; hard error |

Capture reference once; convert local midnight calendar endpoints via ZoneInfo to UTC. Support yesterday/gestern, last week/letzte Woche, next month/nächsten Monat, currently/aktuell, ISO date, dd.mm.yyyy and explicit full-date ranges. Reject conflicting/ambiguous unsupported dates rather than infer locale/year. Never overwrite as_of/history with the parser reference. Recognized temporal terms can be removed for semantic retrieval only when a meaningful residual query remains and exact selectors/symbols are preserved; document the safe date-only behavior.

Use the assertion event time exclusively when an assertion exists. Otherwise use active source events qualifying through the same claim semantics as claim_eligible: confirmed+reviewed support or complete user support for stated claims. Manual sources retain their distinct evidential label. Do not boost from an assistant/partial source merely because a different source makes the claim eligible. Fetch only timestamps/basis/finite aggregates, not unbounded source quotes or raw locators. No second truth store.

Run temporal preference/filter after normal rerank and before diverse/k. Guard graph expansion too: out-of-period graph hits cannot leak through a hard filter; preference must not be undone by graph promotion. Preserve stable ties, original relevance scores and exact-source snippets. Existing candidate/graph caps mean no exhaustive historical recall: expose candidate-limited semantics with actual counts, not a whole-corpus promise. No new security-definer SQL/helper required. Respect the caller transaction snapshot; inspect if a consistent read boundary is necessary for temporal metadata parity with current eligibility.

## Dependencies

stdlib zoneinfo availability and existing canonical metadata/schema029 are sufficient. No model parsing, downloads, generation or private-corpus benchmark. All tests use owned PG55460; no concurrent pytest processes because conftest resets agentic_rag_test. Independent standalone probes must own distinct databases.

## Tests

Test-first parser boundary/ambiguity/DST; real PostgreSQL event-time ranking and scope/lifecycle/future/no-resurrection; local MCP/CLI JSON and central authenticated REST/remote CLI/MCP parity; hard-filter graph safety; empty/unknown/many-source/long-query bounds; legacy off/no-intent exact parity; safe soft failure and hard failure without transaction corruption. Mock external provider boundaries only. Freeze dev/held-out corpus and expected-source labels before implementation and report their hashes; measure parser correctness, source top1/MRR/recall@k, unknown/failure counts, paired latency including no-intent/off controls with repetitions, and 2–3 practical examples. State synthetic lexical/mock-vector limits plainly. No arbitrary performance gate invented after measurement.

Run populated0.6.16→0.6.17/no-schema compatibility and actual old-code rollback/read, verify unchanged row hashes and original timestamps. Final full pytest with actual exit, package contents and version/docs consistency after independent whole-diff review and any correction re-review. Architect derives and executes separate collaborating-component success and failure/recovery probes after as-built reconciliation.

## Architecture findings

AF-064-001 parser/validity separation; AF-064-002 canonical event truth/authority; AF-064-003 bounded candidate/graph ordering and compatibility. See docs/uml/findings.md and temporal-query-64.md. Each maps to S1 tasks and final independent integration gate.

## Supporting artifacts

One minimal sequence answers where temporal reasoning may act without expanding authority. No new data-model/research/contract catalog: fields and bounds live in code, user docs and this plan. Benchmark harness/results live under docs/benchmarks/2026-10-31-temporal-query/; public verification under docs/verification/issue64-temporal-query.md.

## Implementation structure

One serialized strong implementation owner owns temporal.py, search.py, config.py, mcp_server.py, cli.py and any existing remote dispatch seam, meaningful new/affected tests, temporal user/benchmark docs and exact patch version files. Coordinator owns spec/plan/tasks, UML/findings, durable state, independent review and publication. No other edits are reverted. Shared interface producer/consumer changes remain with one owner.

## Playbook obligations

System: none per spec; ordinary reversible code/config activation is documented and tested. Development: none, because only isolated disposable fixtures and automatic no-write compatibility tests run; no live rollout, coordinated cutover or nontrivial migration. Reassess if schema/persistent state or deployment enters scope.

## Authorized live-adoption extension (2026-10-31)

The maintainer explicitly requests Hetzner activation before merging PR87.
Observed source: both active API stores0.6.15/schema028, historical database
owners administrator/rag; worker inactive/cutover gate absent. The target
0.6.17 bundles unchanged029 SQL from0.6.16. T064-009 owns the
[PB-064-LIVE](../../playbooks/system/rag-064-live-temporal-upgrade.md)
development/system obligation: independent review and full-copy migration,
restore and old-code recovery proof before the maintenance window; real TLS
probes and a fresh restore-verified backup before merge. Existing provider,
embedding, reranker, policy and worker authority remain unchanged. This adds
operational acceptance without changing application behavior or prior tests.
