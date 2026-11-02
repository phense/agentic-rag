## Purpose

Preserve the existing service document authorization contract while reducing repeated permission-input work inside its row-security policy.

## ADDED Requirements

### Requirement: Equivalent statement-local document permissions

The policy SHALL read its domain/project permission JSON lazily per statement, through an inlined pure invoker helper. Read and write results, row visibility, SQLSTATEs and legacy behavior MUST remain identical to the 021 policy for all existing roles, including rag_admin. Helper EXECUTE SHALL remain available to every caller subject to the policy without granting data authority. No definer, leakproof, strict or parallel-safety change is permitted.

#### Scenario: Prepared-plan revocation

- **WHEN** a reused connection executes a generic prepared read, changes its domain or project permission, and executes again
- **THEN** the second execution uses the new complete binding and hides revoked rows; restoring the exact initial binding restores the initial result.

#### Scenario: Lazy legacy and malformed inputs

- **WHEN** the service is inactive, or a row is excluded before a malformed project input is reached
- **THEN** the candidate raises no new JSON error; when the original policy reaches a malformed input, both return the same SQLSTATE.

#### Scenario: Scoped writer and nested readers

- **WHEN** reader, writer or admin accesses documents or a dependent chunk/evidence path, or a writer inserts/updates inside or outside its write scope
- **THEN** visibility and accepted/denied writes equal the frozen baseline, including NULL, wildcard, empty and missing settings.

### Requirement: Populated permission-policy upgrade and recovery

Migration 035 SHALL atomically add the pure helper and alter only service_documents USING/WITH CHECK. Existing knowledge, sources, pins, jobs, audit and other policy/function definitions MUST remain unchanged. Populated 0.6.21 upgrade, interruption/retry and independent backup restoration MUST pass with supported limited owners. Performance rollback/reapply SHALL restore either equivalent policy without rewinding data.

#### Scenario: Interrupted existing-installation upgrade

- **WHEN** the migration is interrupted and the operator retries through the existing verified upgrade path
- **THEN** the source remains recoverable, migrations apply once and preserved original rows and queued work are unchanged.

#### Scenario: Performance rollback

- **WHEN** an operator transactionally restores the frozen policy and removes the pure helper, retaining marker035
- **THEN** current and compatible old readers retain the same access decisions, schema validation succeeds, and explicit reapplication restores the optimized policy.

### Requirement: Prospective effectiveness and parent delivery gates

Delivery SHALL require the fresh three-round paired CPU gate in design.md, independent security review, full verification and unchanged parent physical acceptance. INVALID diagnostic data MUST NOT establish savings or acceptance. The coordinator's earlier 0.15 CPU-s locating heuristic and S3 are superseded prospectively, not retroactively passed.

#### Scenario: Ineffective or invalid candidate

- **WHEN** any parity/plan/CPU-coverage gate fails, a job kind slows in a measured round, or weighted savings are not strictly positive in every round
- **THEN** delivery stops and no automatic benchmark repetition or semantic relaxation is allowed.

#### Scenario: Physical latency failure

- **WHEN** a final 40-client phase fails search p95 strictly below 11 seconds, or any existing correctness/drain/model/resource gate fails
- **THEN** #68/#92 remain open and standalone delivery requires an explicit maintainer decision; no production rollout is implied.
