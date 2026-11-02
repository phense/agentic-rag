# Change Proposal: Statement-local document permission inputs

## Stable work ID

- Change ID: `document-permission-initplans`; parent RAG-092 / Issue #92, feature 6.10 / Issue #68.
- Artifact path: `docs/openspec/changes/document-permission-initplans/proposal.md`.
- Status: Implementation authorized by the maintainer's continuing 6.x instruction; coordinator scope decision recorded 2026-11-02.

## Why

Migration 021's document policy repeatedly reads and parses the same permission settings while scanning rows. The settings are bound between statements by `service.context.apply_connection`. This delta moves those inputs to lazy, statement-local InitPlans inside the existing policy. It adds no authorization cache and changes no component boundary. Static independent review identified the required role coverage and operator binding before implementation.

The valid actual-client run at source `17479b1` failed idle40 with search p95 11.42878 seconds. The two subsequent SQL characterization attempts remain INVALID. Their timings, comparisons and partial checks are not benefit evidence, and no claim links this optimization to reaching the latency target.

## Changed requirements

See [the delta requirements](specs/service-document-permissions/spec.md): identical permission results/errors, statement-local work, populated upgrade/recovery and prospective effectiveness gates.

## Acceptance criteria

- AC-001: All existing roles, active/inactive/legacy settings, visibility, write checks and error SQLSTATEs remain equivalent to the original policy, including generic prepared plans and complete scope restoration after revocation.
- AC-002: Permission JSON is read once per statement input, the pure helper is inlined, and point lookups retain indexed access. No privilege elevation, leakproof marking, parallel-safety change or result cache is introduced.
- AC-003: An existing populated 0.6.21 installation upgrades through 034 and 035 without original-row, pin, source, audit or queued-work loss; retry, independent source/target restore and policy rollback/reapply are verified, including a non-superuser owner.
- AC-004: Before delivery, fresh paired CPU measurements pass the design's effectiveness gate, independent RLS review has no C/H/M, the full suite passes, and one newly frozen actual-client run meets all unchanged parent gates.

## Compatibility boundaries

Release remains 0.6.22 in this unmerged PR; migration 035 is additive to 034. Migration files 001–034 remain byte-identical. Old readers retain their existing SQL signatures and follow the equivalent policy. There is no configuration, API, host-adapter, queue or model change. Only the migration owner runs the upgrade after the existing verified-backup/writers-stopped preflight.

Performance rollback restores the 021 policy and removes the new pure helper in one transaction, retaining the applied migration marker. It does not downgrade the database or rewind user data. Explicit reapplication of the 035 SQL restores the optimization; the ordinary idempotent upgrade does not silently undo an operator rollback.

## Scope

Only a pure argument-only helper and `ALTER POLICY service_documents` USING/WITH CHECK are in scope, plus verification and the existing upgrade playbook. The functions from 021, chunk policy, GIN access under RLS, consumer counts and security boundaries are unchanged.

## Escalation check

- New subsystem: No.
- Tightly coupled multi-component reach: No.
- Risky data migration: No; transactional expression replacement, no row rewrite; security-sensitive review remains mandatory.
- Material architecture uncertainty: No beyond runtime checks of the accepted existing-boundary design.

Any need for a definer matching helper, LEAKPROOF, chunk-policy change, denormalized scopes or a different component boundary stops this change and requires A4/security design.

## Playbook obligations

Update PB06801 at `docs/playbooks/agent-plugins.md` and its evidence sidecar before delivery: 0.6.21/schema033 → 0.6.22/schema035, non-superuser prerequisites, transactional retry, policy rollback/reapply, and limits of code downgrade. Coordinator owns content and populated rehearsal; independent content review and practical evidence are separate gates.
