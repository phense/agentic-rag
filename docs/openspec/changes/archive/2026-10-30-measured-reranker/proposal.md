# Change Proposal: Measured local reranker configurations

## Stable work ID

- Change ID: `measured-reranker`; work RAG-062, roadmap#58 step4/15, Issue#62.
- Status: Authorized for implementation by the sequential roadmap request.
- Source: 0.6.14/schema027, `7a61955446119df522a34967273d8dacae56108b`.
- Target: 0.6.15; no schema migration.

## Why

Issue#28 shipped a selective local model but its three measured examples were
development cases, not held-out evaluation. Issue#35 supplies failure-derived
synthetic families and original-source checks. Extend the existing ordering
callback and benchmark utilities, keeping production defaults unchanged.

## Changed requirements

Add bounded local configuration choice, safe decision diagnostics and a versioned,
sealed bilingual evaluation to the retrieval-ordering capability. Retain all
existing eligibility, original-payload and deterministic fallback requirements.

## Acceptance criteria

- AC062-001: A versioned public EN/DE corpus contains failure-derived and
  representative exact-identifier, temporal, multi-source and unsupported cases.
  Related translations/sources stay in one family/split; labels never enter ranking.
- AC062-002: Compare legacy12×1200 with focused6×600 on the same pinned local
  Qwen model, plus the justified small local Jina tiny challenger. Freeze development choice, corpus/source/model identity and budgets
  before any held-out evaluation; retain every failure and independent denominator.
- AC062-003: Add opt-in local model/revision and fixed policy configuration.
  Enforce candidate, query, passage, deadline, response and concurrency bounds.
  No remote reranker or automatic download; no heavier default activation.
- AC062-004: Reordering preserves authorized/current source membership, exact
  identifier bypass, diversity and complete original citation payloads. Empty,
  unavailable, malformed, timeout and pressure paths retain deterministic order.
- AC062-005: Optional diagnostics disclose route, configured model/revision,
  bounded input counts and a fixed outcome; no text, URL, body or exception leaks.
  Scores remain ordering signals, never truth probabilities or answer labels.
- AC062-006: Publish source recall/precision/nDCG denominators, retrieval-empty
  abstention, citation parity, all misses, first/warm p50/p95, throughput and
  process CPU/RSS under one effective4CPU/8GiBzero-swap service cgroup; include 2–3 attributable examples and hardware limitations.
- AC062-007: Rehearse populated local and central reads, existing-client/default
  configuration, source withdrawal, scope/time checks and code/config rollback.
  Independent complete-diff review and actual full-suite exit precede PR handoff.

## Compatibility boundaries

Defaults retain the prior model, policy and 1500ms deadline. New configuration
fields are additive; no canonical rows, embeddings, settings or clients are
rewritten. Old/new readers share schema027. Rollback removes the new rerank
options and restores0.6.14 code; retained original evidence needs no recovery.
Production adoption, private corpus calls and real hosted inference are separate.

## Scope and escalation check

Only the existing config/neural ordering seam, its search diagnostics and bounded
evaluation tooling change. No new subsystem, topology/authority change, risky
migration or tightly coupled cross-component design is needed. Reassess if any
of those become necessary. Existing service serialization is retained.

## Playbook obligations

PB062-OPS: extend `docs/local-reranker.md`, operator/coordinator-owned, before
delivery. Include supported0.6.14→0.6.15 code/config adoption, offline policy
inspection, explicit model identity, failure diagnostics and rollback. Independent
content review plus actual synthetic local/central recovery rehearsal required.
