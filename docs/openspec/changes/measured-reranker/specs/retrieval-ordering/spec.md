## ADDED Requirements

### Requirement: Explicit bounded local reranker configurations

The system SHALL preserve legacy local ordering defaults and offer an explicit
focused-v1 six-passage600-character configuration and local model/revision
selection, bounded by the existing query/deadline/concurrency limits. It MUST
reject invalid settings and MUST NOT send passages to a remote origin or use an
unadvertised model. Selection does not attest weights or activate a benchmark winner.

#### Scenario: Opt-in configuration and rollback

- **WHEN** an operator selects focused-v1 and a matching local model
- **THEN** only the bounded prefix enters inference and original payloads/tail survive.
- **WHEN** the options are removed or0.6.14 code/config are restored
- **THEN** legacy ordering/defaults remain available without changing persisted rows.

### Requirement: Safe optional ranking decision diagnostics

The system SHALL expose opt-in fixed-schema route/model/revision/outcome and
bounded input counts without source/query/URL/exception text. Failures MUST
retain deterministic candidate order, existing identifier/source/scope/time
filters, original citations and diversity. Scores MUST NOT be truth probabilities.

#### Scenario: Unavailable or invalid reranker

- **WHEN** a timeout, malformed response, unrelated model or pressure occurs
- **THEN** original ordering survives and diagnostics identify only a safe fixed outcome.

### Requirement: Sealed bilingual failure-derived evaluation

Evaluation SHALL use versioned public synthetic EN/DE cases with separated
related source families, exact/temporal/multi-source/unsupported coverage and
traceable failure-class origins. It MUST freeze candidate choice and source/
corpus/model identity before held-out evaluation, reject drift and retain every
failure in independent quality denominators. It SHALL report source recall,
precision/nDCG, retrieval-empty abstention, citation parity, first/warm latency,
throughput and observed CPU/RSS, with actual hardware and generalization limits.

#### Scenario: Held-out evidence cannot retune selection

- **WHEN** development comparison finishes
- **THEN** candidate.json is written exclusively before held-out calls; repeat
  timings do not multiply quality observations and no held-out label reaches ranking.

### Requirement: Reviewed operator adoption and recovery

PB062-OPS (`docs/local-reranker.md`) SHALL document0.6.14→0.6.15 compatible
code/config adoption, model identity, explicit bounded options, safe diagnostics
and rollback. Content review plus synthetic local/central recovery rehearsal
MUST pass before delivery; production acceptance remains separate.

#### Scenario: Existing installation keeps original knowledge

- **WHEN** old/new clients read a populated schema027 store and configuration is rolled back
- **THEN** canonical IDs, evidence, permissions, queues, pins and audit rows remain unchanged.
