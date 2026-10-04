## Purpose

Avoid unnecessary query inference for strict selectors while preserving the existing retrieval
contracts and the eligibility of every returned knowledge item.

## ADDED Requirements

### Requirement: Adaptive retrieval routing

The system SHALL resolve eligible exact document UUIDs/hyphenated slugs and standalone strong
error symbols without embedding when useful fast-path evidence exists. It MUST use the existing
hybrid path for ordinary queries and shortcut misses. strategy=hybrid SHALL preserve the previous
candidate pipeline; strategy=lexical SHALL explicitly use bilingual FTS without inference.

#### Scenario: Eligible selector

- **WHEN** a strict exact selector has eligible source evidence
- **THEN** bounded original-source hits and citations are returned with no embedding call.

#### Scenario: Missing selector or semantic question

- **WHEN** a shortcut has no surviving hit or the question is natural language
- **THEN** the previous embedding and hybrid fallback behavior runs.

### Requirement: Fast-path compatibility and eligibility

All routes MUST enforce domain, project/global scope, active status, source trust and current/as-of/history
eligibility before accepting hits. Existing k, reranking, graph expansion and presentation contracts SHALL
remain shared. Invalid strategies MUST fail before database or inference work. Legacy baseline selection
SHALL remain unchanged. No schema or production data mutation SHALL be needed.

#### Scenario: Ineligible exact target

- **WHEN** a target is foreign, expired, refuted, future-dated or outside the requested domain
- **THEN** it is not returned by a shortcut and fallback cannot bypass its eligibility.

#### Scenario: Existing client

- **WHEN** a reader-role caller uses the existing CLI/MCP signature without a strategy
- **THEN** its output shape and privileges remain valid, and forced hybrid remains available for rollback.
