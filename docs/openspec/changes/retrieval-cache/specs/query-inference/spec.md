## ADDED Requirements

### Requirement: Bounded permission-safe inference reuse

Successful query vectors SHALL be reused only within the bounded lifetime, complete
caller/retrieval context and verified current model identity. Cached retrieval results
SHALL NOT bypass fresh applicability/source trust or database privilege checks.

#### Scenario: Repeated query

- WHEN an identical MCP query repeats in the same context with the same model digest
- THEN query inference can be skipped while SQL eligibility and citations run again.

#### Scenario: Correction, expiry or changed visibility

- WHEN source trust, current-time applicability or caller/project/domain selection changes
- THEN previously returned knowledge cannot be exposed through cached authority.

### Requirement: Safe lifecycle and fallback

Transport/cache resources MUST be bounded and process-local. Model identity or inference
failure MUST retain the uncached/fail-open contract without storing a failed result.
Forks, concurrent calls and shutdown MUST NOT reuse unsafe state or leak other contexts.
No persisted production mutation SHALL be required to adopt or roll back this code.
