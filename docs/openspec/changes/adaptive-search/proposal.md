# Change Proposal: Adaptive retrieval fast paths

## Stable work ID

- Backlog ID: 5.1; GitHub Issue: #26
- Change ID: adaptive-search
- Artifact path: docs/openspec/changes/adaptive-search/proposal.md
- Status: Authorized for implementation by the maintainer, 2026-10-03

## Why

Every ordinary search currently embeds its query. An exact document identifier or standalone
error symbol can often be resolved safely without local inference. This bounded delta changes
routing inside the existing search seam and adds optional strategy controls to its existing consumers.

## Changed requirements

See specs/retrieval-routing/spec.md for the added routing and compatibility requirements.

## Acceptance criteria

- AC-001: eligible exact UUID/slug and standalone error-symbol hits avoid embeddings and retain original citations.
- AC-002: misses, ordinary questions and explicit hybrid strategy retain the existing hybrid selection/fallback.
- AC-003: all fast paths respect status, domain, project/global applicability, source trust and current/as-of/history eligibility before accepting a result.
- AC-004: CLI/MCP shapes and reader privileges remain compatible; bounded k, graph expansion and reranking still apply. Invalid strategies fail before DB/inference work.
- AC-005: full tests, independent review without Critical/High/Medium findings and three reproducible practical measurements support handoff.

## Compatibility boundaries

Existing defaults become adaptive only for strict selectors with eligible hits. Hybrid is retained
as an explicit strategy and legacy benchmark baseline behavior is unchanged. No schema/config/data
migration is required; installations with migrations 001–014 remain readable by both old and new code.
Deployment changes code only, restarting long-lived MCP processes when adopted. Roll back to the
prior source revision or request hybrid; knowledge, vectors, pins, queues and audit remain unchanged.

## Scope

In scope: exact UUID/slug, standalone error-symbol lexical shortcut, fallback and explicit strategies.
Out of scope: caches, learned reranking, general question rewriting, new graph or research subsystems.

## Escalation check

- New subsystem: No
- Tightly coupled multi-component reach: No; existing search seam and thin CLI/MCP adapters only.
- Risky migration: No
- Material architecture uncertainty: No

## Playbook obligations

No new system playbook: the existing code install/MCP restart and source rollback procedures apply.
No critical development operation is needed: production is read-only and no schema/state is altered.
