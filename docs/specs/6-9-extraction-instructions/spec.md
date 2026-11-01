# Feature Specification: Versioned extraction instructions

## Stable work ID

- Feature6.9 / RAG-067 / [Issue67](https://github.com/phense/agentic-rag/issues/67), roadmap9of15.
- Artifact: `docs/specs/6-9-extraction-instructions/spec.md`.
- Status: coordinator-accepted requirements for the authorized roadmap implementation.
- Source baseline: merged PR90, `01bc13bd`,0.6.19/schema031. Target0.6.20.

## User scenarios

### US-001: Choose durable knowledge without editing code (P1)

An operator configures extraction guidance, category allowlists and examples for a
whole installation or a domain/project. Inspect explains the effective settings;
dry-run checks a sanitized sample without saving knowledge. An explicit evaluation
option may call the already configured provider, with the same safety checks.

### US-002: Keep retries reproducible (P1)

Changing the file affects new work. An admitted job and an accepted batch retain
their policy identity and normalized snapshot after process failure or reload.
Current authorization and evidence qualification are always checked again.

### US-003: Upgrade an existing populated installation safely (P1)

The operator upgrades without re-mining or altering existing knowledge, pins,
sources, batches, queue cursors, users or ACLs. A known previous valid policy can
be restored for future work, independently of replaying already accepted work.

## Acceptance criteria

- AC-001 — A strict version1 configuration supports bounded instruction text,
  positive/negative examples, category allowlists, item/output limits and stable
  policy identity. Unknown fields/versions, malformed selectors, duplicate scope
  rules and invalid combinations fail with safe, actionable error codes.
- AC-002 — Effective policy is deterministic: builtin defaults, global, domain,
  project, then exact domain+project overrides, field by field. Arrays replace
  rather than concatenate. Inspect reports the selected scope, identity/digest,
  precedence and effective limits. Domainless outputs use global/project policy.
- AC-003 — Validate/inspect/default dry-run never invoke a provider or write
  knowledge. Evaluation requires an explicit option and uses the existing provider
  configuration; output explains accepted/rejected categories and applicable limits.
  Samples, guidance and provider output are secret-checked/redacted before exposure.
- AC-004 — No custom instruction can change authorization, evidence/source binding,
  claim qualification, validity, pin immutability, gateway auditing, structured
  output or hard budgets. Category and limit enforcement is deterministic after
  extraction, including suggestions and contradiction side effects. Transcript or
  uploaded source text cannot set policy. Exact quotes do not prove entailment;
  free text guidance is advisory, not a semantic truth validator.
- AC-005 — Queue admission and central source-window admission capture the effective
  versioned policy before provider execution. Direct mining binds the input cursor
  before its first provider call. Retries, accepted-output replay and continuation
  of the same admitted job never resolve a different policy silently. Malformed or
  mismatched durable snapshots block rather than fall back to today's settings.
  Before acceptance, a new admission conflicting with an existing cursor binding
  fails with `extraction_policy_conflict`, without provider call or cursor movement.
  Every admitted and bound snapshot must match the work's canonical project.
  Retrying a direct call may reuse its binding only in that same project.
  A changed domain set alone is not a policy conflict: compare effective policy
  hashes for shared domains and domainless output, retaining the original bound
  domain set. Legacy retries require a builtin binding. Current authority is
  still intersected before each attempt; neither newly available domains nor
  revoked authority may widen the bound work.
- AC-006 — Existing queue windows/batches without custom-policy metadata have an
  explicit legacy/builtin interpretation. Missing configuration preserves existing
  mining prompt/schema/output behavior. Existing accepted batches are never
  reinterpreted or filtered using a later policy. Current revoked authority still
  blocks application. New jobs after a policy change use the new identity.
- AC-007 — File-first operation has one shared validation/resolution API for future
  dashboard editing. Service-side files own central mining; clients cannot upload
  guidance or override service rules. A file is read once per admission, changed
  atomically, with required restart/reload behavior documented. The binding audit
  identifies policy hashes without copying arbitrary text into audit summaries.
  File replacements themselves are not database events and are not audited.
- AC-008 — Policy changes are prospective and never trigger historical re-mining.
  This feature adds no bulk historical rewrite/re-mining operation. Reusing an
  accepted cursor replays its accepted result. Any future historical run requires
  separate explicit authorization, bounded source selection and a distinct run.
- AC-009 — Populated0.6.19 upgrade, interruption/retry and independent restore
  preserve original rows, evidence versions, ownership and grants; exercise old/new
  clients and pending/accepted work. A rollout gate prevents old mining processes
  from bypassing custom policy. Supported code/config rollback and data-loss limits
  are documented and rehearsed on owned copies.
- AC-010 — Freeze public EN/DE examples before implementation. Publish at least
  three inspected cases (retained solution/decision, rejected category/abandoned
  experiment, policy change during retry), source fidelity, provider-call counts,
  actual latency and replay behavior. Mock-provider results establish enforcement
  and replay, not real-model extraction accuracy. Independent review and fresh
  relevant/full verification have no open Critical/High/Medium findings.

## Functional requirements

FR-001: Expose one typed policy contract with explicit immutable builtin defaults.
FR-002: Separate advisory extraction preferences from mandatory correctness checks.
FR-003: Retain the policy used by durable work without granting any new authority.
FR-004: Keep local operation and existing Claude/Codex/HTTP authentication intact.
FR-005: Never acknowledge unconsumed source fragments to enforce an input budget;
policy limits may reduce retained output, not truncate source windows silently.

## Compatibility boundaries

No dashboard UI, provider migration, new model dependency, automatic historical
reprocessing or semantic-classifier quality guarantee. Existing fixed categories,
pins and structured output remain the baseline. Existing per-window/provider/time
caps remain mandatory; configured limits can only narrow supported output limits.
Explicitly empty allowlists are valid and cause no provider call when no output
category is enabled. Invalid custom files fail new admission visibly, while an
already captured valid snapshot remains replayable without reading that file.
Old clients may submit the existing envelope; old miners may not run after custom
policies are enabled, because they cannot enforce this new contract.

## Interface contracts

| ID | Boundary | Inputs | Outputs / invariant |
|---|---|---|---|
| IC-001 | Operator → policy validator/resolver | strict versioned local configuration, domain/project | normalized effective policy, safe errors; no authority changes |
| IC-002 | Admission → worker → batch | protected normalized snapshot and digest | same policy on retry/continuation, current authority checked |
| IC-003 | Provider → mining gateway | existing structured extraction, exact source events | deterministic category/limit filtering then unchanged grounding/gateway |
| IC-004 | CLI → inspection/evaluation | explicit sample and optional evaluate | bounded sanitized report; no knowledge writes |
| IC-005 | Upgrade → existing installation | populated031, verified backup, pending work | preserved originals/ACLs and tested retry/restore, explicit old-process gate |

## Edge cases and decisions

Conflicting duplicate selectors fail; a project-wide rule overrides a domain-wide
rule, with the exact pair taking final precedence. Domainless suggestions cannot
inherit an arbitrary document's domain. New domains on a retry cannot widen the
captured domain set; removed/revoked domains cannot be written. All-disabled policy
is an intentional empty extraction. Concurrent binding uses one committed winner;
an audit failure must not leave an unaudited binding. No snapshot text crosses
foreign-scope inspection or public error surfaces. Invalid config does not consume
a queue cursor, and policy rollback never mutates a durable accepted extraction.

## Success measures

SC-001: Every frozen enforcement/retry label is explained, with zero foreign writes.
SC-002: Zero original rows/evidence versions changed by the upgrade itself.
SC-003: Replay uses zero extra extraction calls after output acceptance.
SC-004: No open Critical/High/Medium or Important playbook defect at PR/merge.

## Playbook obligations

PB-067-OPS, system deliverable, `docs/playbooks/system/rag-067-extraction-policy.md`.
Audience: installation operator. Source: US-002/003, AC-005/007/009. Cover populated
upgrade, stopping/restarting old miners, policy validation/activation, invalid-file
recovery, queued snapshot inspection, prospective rollback and backup/restore.
Acceptance requires independent content review and public CLI/service rehearsal
on owned multi-domain data, including one failure/retry branch. Production/TLS/
systemd/macOS/multi-host operation is outside the rehearsal claim unless tested.
