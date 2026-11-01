# Implementation Plan: Versioned extraction instructions

## Stable work ID

Feature6.9 / RAG-067 / Issue67 / roadmap9of15. [Specification](spec.md).
Baseline `01bc13bd`,0.6.19/schema031; target0.6.20/schema032.

## Summary and project gates

Introduce a bounded file-first extraction-policy module and immutable per-work
snapshots. Preserve `mining.SYSTEM`, `build_prompt`, `build_schema` and accepted
legacy extraction behavior when no custom guidance is configured. Extend only
mining, its two admission paths, introspection and upgrade coverage. No providers
or new authentication. One writer owns the cohesive implementation slice.

| Gate | Repository evidence | Decision |
|---|---|---|
| Original-preserving audited store | AGENTS.md, mining._apply_prepared_extraction/store.save_claim/save_assertion | mandatory, no direct knowledge writes |
| Admission/retry split | jobs.enqueue_mine; service.ingest.accept; mining.mine_session accepts output before apply | snapshot before first call and reuse accepted output |
| Scope/security | service.context/auth, service.worker.before_apply, SQL021 service_batches | snapshot never substitutes current authority |
| Upgrade | service.upgrade, schema.py, tests/service/test_lifecycle_upgrade.py | additive032, supported source0.6.19, real archived old code |
| Version/doc/review | AGENTS.md | exactly+1patch, public evidence and independent bounded review |
| Authority | maintainer remaining6.x instruction | autonomous merge only after all gates; production excluded |

## Technical context and verified seams

Python3.13, PostgreSQL17+pgvector, existing Pydantic and stdlib TOML. Config uses
section prefixes and explicit path conversion. jobs.enqueue_mine commits queue
admission and retains its payload when a debounced job requeues in worker._complete.
service.ingest.accept validates an extra-forbid source envelope, redacts it and
commits source window/stream/queue atomically. service.worker.process_source opens
a current principal scope and rechecks before/after accepted extraction apply.
mining.mine_session currently calls the provider before INSERT mining_batches,
then commits accepted normalized output independently of its atomic gateway apply.
Thus adding policy only at batch acceptance is too late for provider failures.

## Ownership and contracts

New `agentic_rag/extraction_policy.py` owns strict models, bounded file reading,
normalization, scope resolution, digest validation, prompt preference rendering,
category/limit enforcement and read-only sample evaluation support. `Config` adds
only an optional policy-file path; no custom settings means builtin behavior.
CLI gets `rag extraction validate|inspect|dry-run` (exact argparse shape may be
refined before fixtures, document any change). Dashboard editing is deferred;
it will call the same pure validation API, not duplicate parsing.

The policy file has `version=1`, an optional global policy and bounded rules with
explicit optional domain/project selectors. Reject duplicate selector pairs,
empty/invalid selectors, unknown keys and dangerous reserved capability settings.
Guidance is data appended under a bounded operator-preference section; mandatory
SYSTEM rules remain authoritative. Do not claim a keyword blacklist can prove
natural-language safety. Reject guidance containing detectable unredacted secrets
rather than hashing one value and sending another. Sample/output redaction stays
mandatory. Limits are output item/body limits within hard caps; source windows
are never shortened/acknowledged differently by custom guidance.

Build a policy bundle once per admitted project, containing effective policies
only for the caller's then-writable domains plus a domainless global/project
policy. Do not store all foreign installation rules in a service-owned payload.
Capture authorized domains for enforcement; later authorization is intersection,
never union. Hash canonical normalized values including schema/builtin version
and semantic settings; formatting-only file changes retain identity.

## Durable binding and schema032

Use additive `sql/032_extraction_policy.sql` and schema/check/restore allowlists.
Add `extraction_policy_bindings` keyed by (session_id,input_cursor), holding a
bounded normalized policy snapshot/digest and creation metadata. Session RLS and
old-write restrictions match mining_batches; grants cannot expose foreign policy.
A binding and its audit commit atomically before any provider call, and survives
provider failure. Concurrent direct callers take one winner, not two meanings.
No mutable global active-policy registry or policy-text audit duplication.

New local job payload captures its bundle inside enqueue_mine's serialized
admission transaction. A rerun_requested flag/continuation retains that bundle.
New service_windows payload captures its bundle server-side inside accept's
existing transaction, after principal/project validation. Public envelope cannot
supply this field. Worker passes the captured bundle to mine_session, which binds
it before calling extraction. Queue/window entries lacking metadata mean explicit
legacy builtin, not today's file. Direct new calls resolve once, then reuse the
binding on retries within the same canonical project. An admitted snapshot from
a different project is invalid. If a new admission differs from an existing
unaccepted binding, refuse with extraction_policy_conflict before the provider;
keep the binding and cursor unchanged. No silent replacement or policy reuse.
Existing mining_batches win before binding/resolution so old
accepted data is applied untouched; new accepted output records its digest in
reserved metadata/provenance and binds to the same snapshot.

This is a design obligation, not permission to rewrite old extraction JSON.
Prefer retaining snapshots in the dedicated table plus existing private payloads
instead of adding unrelated columns. Migration itself does not modify old rows.
Malformed snapshots fail safely without reading a replacement file or moving a
cursor. Schema migration must remain transactional and rerunnable.

## Enforcement and evaluation

Existing output categories are memories,lessons,signals,assertions,contradictions,
pin_suggestions,contradictions_with_pins,domain_proposals. Resolve per-item domain
where present; use domainless policy for the rest. Prompt/schema may explain or
restrict choices, but normalized output filtering is the authoritative guard.
Reapply only the bound policy on new output; never reinterpret an old accepted
batch. Ground exact source fragments and derive speaker/time using unchanged
code, then apply through the existing atomic gateways. Record bounded rejection
counts/reasons, not discarded private text. An all-disabled bundle skips provider
execution and accepts an intentional empty batch while preserving window cursor.

Default dry-run validates and shows a sanitized effective plan, zero provider
calls. Explicit evaluation runs the configured structured provider on a bounded
sample through the same policy/grounding functions with no canonical writes,
embeddings, suggestion audits or queue changes. Use synthetic mock providers for
CI and public fixture measurements; disclose lack of real-model quality evidence.
Client mode must not read a service's local policy file or silently evaluate under
client settings: reject unsupported remote administrative operations clearly, or
use an authenticated scoped read-only server API with tests if needed.

## Upgrade and recovery

Support0.6.19 as a source for verified_backup/upgrade. Audit schema validation,
restore-target/resume tables and previous exact-migration-count expectations.
Populate with actual archived `01bc13bd` code, ordinary knowledge/assertions/pins,
multiple scopes, old pending jobs and an accepted unapplied batch. Hash every
original row and source/evidence version; compare grants/owners/sequences. Prove
transaction interruption then retry and independently restore both pre/post dumps.
Exercise old ordinary readers/writers on032 before custom activation. Old mining
code ignores new policies: all old direct mining/hooks/workers must be stopped or
upgraded before enabling custom guidance, with a process inventory/restart gate
reusing the corrected PB-065 max(mtime,ctime) technique, not a timestamp-only claim.

Rollback to prior valid file affects only new admissions. Captured work keeps its
policy. Old-code rollback with custom work pending is unsupported unless the work
is fenced/drained under new code; do not silently claim old miners enforce rules.
Restoring a preupgrade dump loses later writes and requires stopped writers. No
production procedures execute under this implementation permission.

## Tests and evidence

Freeze synthetic EN/DE cases before product changes: confirmed solution/decision,
abandoned experiment, disallowed category with dishonest provider output, exact
quotes/secret stripping and changed-policy retry. Unit tests cover strict types,
selector precedence, duplicate conflict, normalization, unknown versions, limits
and no-custom prompt/schema compatibility. Real DB tests cover binding races,
audit rollback, accepted replay, provider-failure retry, scope revocation and old
queue metadata. Central tests traverse existing admission→worker→batch→gateway,
including malformed metadata and read-only/foreign denial. No parallel pytest.

Publish three repeated fixture measurements, labels and provider-call counts,
not just prompt snapshots. Independent reviewer checks the complete bounded diff,
derives real collaborating-component success and recovery tests after as-built
reconciliation, reviews PB-067-OPS and verifies owned DB cleanup. Root runs the
final full suite, Node/packaging/lock/docs checks as appropriate, then converges,
creates/links the focused PR and merges only with clean final gates.

## Architecture and playbook handoff

Named design questions: who controls preferences; when policy becomes immutable;
what happens across failure/retry and old/new code. The minimal sequence model and
AF-067 findings must precede tasks. PB-067-OPS is the required system playbook at
`docs/playbooks/system/rag-067-extraction-policy.md`, operator-owned, needed before
delivery. Independent content review plus owned populated CLI/service rehearsal
is mandatory. Development playbook: none; only isolated owned data is changed in
development, while any later live rollout requires its own reviewed operation.
