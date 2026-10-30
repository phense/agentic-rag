# Feature Specification: Authenticated dashboard and resumable setup

## Stable work ID

- Feature ID: `RAG-059`, roadmap6.1, [Issue59](https://github.com/phense/agentic-rag/issues/59).
- Status: specified for authorized autonomous implementation.
- Source request: complete Issue59 through an independently reviewed, tested PR like58/68.

## User scenarios

### US-001: Secure first administration (P1)
An operator explicitly arms one-time bootstrap on an uninitialized policy. Exactly one concurrent claimant creates the first administrator; subsequent claims fail. Existing accounts cannot be taken over through bootstrap. Browser sessions expire and revoke independently of agent session names.

### US-002: Resume installation safely (P1)
An administrator selects new local, existing local upgrade, central server, or client connection. The assistant discovers existing data/schema, validates prerequisites, saves progress across restart, and exports a reviewed configuration/instruction plan. Repeating completion has no destructive effects. Verified migration/restore remains an operator action.

### US-003: Manage enrolled clients (P1)
An administrator sees principal labels, effective permissions, enabled/revoked and online/stale/never-seen states, reported version/capabilities, queue/provider health and scoped pending reviews. Explicit, revision-checked policy changes enroll, rotate/revoke credentials and change scopes. Generated secrets appear once. File-owned configuration retains precedence.

### US-004: Browse scoped knowledge (P1)
Human users browse/search memories, inspect original sources and review states under their current rights. Restricted users have read-only navigation; denied actions and errors reveal no foreign counts or content. Mobile/keyboard navigation remains usable.

## Acceptance criteria

- AC-001: Two bootstrap claims yield one admin; an existing/nonempty policy disables bootstrap regardless of a leftover token. No default password/open registration.
- AC-002: HTTPS cookies are HttpOnly/Secure/SameSite=Strict, unsafe requests require same-origin plus session CSRF, login is rate-limited, expiry/logout/current-policy revocation is checked on every API call. Bearer API behavior remains unchanged.
- AC-003: All four setup paths have explicit prerequisites/results. Existing data prevents fresh initialization; completed and interrupted progress resumes after application restart. Failure codes are safe; configuration/credential values never appear in diagnostics.
- AC-004: Database/schema/permissions, embedding identity/access, provider access and protocol/capability checks have explicit verified/configured/unavailable states; probing is explicit, synthetic and bounded.
- AC-005: Enrollment/rotation/revoke/scope changes require a currently authorized human admin and an exact prior file revision, are audited and race-safe. Failed/replayed changes never reveal a previously generated secret. Losing the last enabled login-capable admin is refused.
- AC-006: Enabled state is distinct from heartbeat freshness; authenticated observations are bounded and reported versions are informational only. Policy permissions remain authoritative.
- AC-007: Browse/search/detail/counts/reviews obey current domain/project RLS. Read-only users cannot mutate knowledge or administer policy.
- AC-008: Existing024 data, sequences, roles/ACLs, source evidence, jobs/checkpoints/audit history survive additive025 upgrade, verified backup/restore and retry. Standalone operation and old REST/MCP clients remain usable.
- AC-009: Browser E2E checks cover first-run race, discovery/resume, expired session/revoked credentials, denied action, source drill-down and keyboard/mobile navigation. Resource tests exercise40 logical users; pending browser tool work uses the existing bounded queue rather than extra provider runtimes.

## Functional requirements

FR-001..009 correspond respectively to AC-001..009. Administrative privilege controls configuration, not automatic knowledge access. File-owned runtime/model settings are read-only; policy editing uses an explicit validated preview/apply contract with revision protection. Secrets are never stored in browser persistent storage or audit payloads. No request-log UI (6.2), arbitrary provider replacement (6.3), new hosted infrastructure or automatic multi-store merge.

## Compatibility boundaries

The web server requires an initialized, verified current database, as the existing service does. For a pre-database install, the operator follows the displayed/documented CLI prerequisites first. Browser setup does not perform DDL, reset a populated store, move data or restart services. Local CLI/stdio operation does not require dashboard accounts. The new API/UI is additive; protocol1, two MCP privilege levels, compaction hooks and background scheduling are preserved. Upgrade source0.6.0–0.6.11/schema018–024; target0.6.12/025. Roll back code only if no025-dependent service is started; otherwise restore a verified current-target backup and preserve post-upgrade writes.

## Interface contracts

| ID | Boundary | Observable contract |
|---|---|---|
| IC-059-01 | Browser→dashboard API | Same-origin session cookie plus CSRF; bounded bodies/results; safe status codes; no ambient cookies on v1 |
| IC-059-02 | Dashboard→policy file | Owner-only, validated preview/apply, optimistic revision, serialized atomic replace; restart-recoverable nonsecret audit |
| IC-059-03 | Dashboard→knowledge | Existing authenticated engine/queue and scoped DB reads; original-backed details; no direct knowledge writes |
| IC-059-04 | Setup→operator | Persisted check codes/mode, read-only discovered configuration, explicit validated exports; no destructive migration |
| IC-059-05 | Legacy clients→presence | Best-effort throttled observations, bounded reported versions/capabilities; no access changes |

## Edge cases

Crash after file replacement before audit completion is reconciled from old/new digest under the policy lock; unknown drift fails closed. A lost generated-secret response requires fresh rotation. A concurrent operator file edit invalidates preview/apply. A disabled author does not remove team-readable history. Stale clients are never silently revoked. Over-capacity controls return retryable bounded errors; no unbounded browser/model jobs.

## Assumptions and unresolved decisions

No unresolved design choices require user action. Browser setup begins after DB prerequisites; this matches the issue's boundary that the assistant does not replace verified migration/restore. Admin settings are initially file-owned; validated policy apply is explicit. Database credentials and provider tokens stay in operator-owned files, never the browser.

## Success measures

One successful concurrent first-admin claim, zero cross-scope fields/counts, no lost original rows during024→025, bounded40-user test and successful restart/resume. Record measured samples and limits, not inferred performance gains.

## Playbook obligations

PB-059-01 (operator): bootstrap and recover/resume setup, including last-admin lockout prevention, private secret handling and existing-store detection. PB-059-02 (operator): policy preview/apply, lost response/crash/drift recovery and revocation. Deliver in `docs/15-dashboard.md`, rehearse on an owned populated copy and through browser E2E before delivery.
