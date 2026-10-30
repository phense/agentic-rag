# Implementation Plan: Authenticated dashboard

## Stable work ID

RAG-059; [specification](spec.md); target0.6.12 on0.6.11 (promotionPR78).

## Summary

Extend existing Starlette service with isolated `/dashboard` routes, packaged HTML/CSS/JS, existing human sessions and a session-derived CSRF token. Use PostgreSQL for bounded setup/presence and administrative change journals; retain the TOML policy as sole access authority. No frontend framework/runtime or new database.

## Project gates

| Gate | Evidence | Result |
|---|---|---|
| One canonical store/gateway | service/api.py, auth.py, engine.py, requests.py | Reuse; no separate knowledge store |
| Local/old client compatibility | protocol1 and standalone remain unchanged | Additive migration025 only |
| No private public artifacts | Synthetic tests; private rehearsal manifests/logs | Enforced |
| Independent review and upgrade proof | S05903 | Delivery gate |
| Exactly one patch | pyproject/lock/README/changelog0.6.12 | Before PR |

## Technical context

Python3.13, PostgreSQL17/pgvector, Starlette/httpx/psycopg/tomlkit. Owners: coordinator writes `agentic_rag/service/dashboard*`, packaged `dashboard_assets`, SQL025, tests and documentation; independent reviewer reads complete bounded diff. Existing `protected_file`, Policy, service_sessions, invoke/queued requests, upgrade verifier and resource admission remain shared.

## Compatibility boundaries

Serve only current-schema stores; verified upgrade precedes server restart.025 adds owner-only dashboard tables and preserves all prior rows. Extend known-prefix/version verification and strict restore; test actual populated024. CLI bootstrap explicitly creates an empty policy only when absent and emits a token to a newly created0600 file; never prints token. Operator-owned model/runtime settings are read-only. Existing policy edits are explicit and revision-checked.

## Interface contracts

| ID | Producer/consumer | Change | Failure |
|---|---|---|---|
| IC-059-01 | browser/dashboard | HttpOnly cookie + CSRF, bounded independent capacity, CSP/no cache |401 expiry,403 origin/role,429 capacity |
| IC-059-02 | administration/file+DB | Preview validated complete result; owner-only file lock; prepared journal commit; exact session-row lock and clock-expiry check; atomic fsync file; finalize/reconcile |409 stale revision, no secret replay; unknown drift503 |
| IC-059-03 | browser/engine | Scoped bounded list and queue submit/status for search/get/review | Uniform safe errors; no foreign result |
| IC-059-04 | setup/operator | Four modes, persisted bounded check results, explicit synthetic checks and export | No migration/reinitialization side effects |
| IC-059-05 | clients/presence | Throttled fixed safe metadata, capped one row/configured principal | Best effort, never auth authority |

## Dependencies

Existing0.6.11/schema024 baseline, local isolated PostgreSQL55458, Playwright Chromium for local E2E, SSH mcp-server for authorized test-copy deployment. No dependency on PR78 merge to develop; stack PR59 on its branch until main includes it.

## Tests

Meaningful red-first API/bootstrap concurrency/CSRF tests; file permissions/atomicity/revision races/crash reconciliation; current authorization/last-admin protections; existing-store detection and restart/idempotent completion; knowledge count/content scope; body/result/row budgets. Browser checks real form/navigation plus mobile and keyboard; populated024 backup→strict restore→025/retry originals/ACL/sequences; bounded40-client exercise without private provider input. Full Python and affected plugin/packaging checks serial on owned cluster. Cloud rehearsal uses only owned copy/services; canonical worker stays stopped.

## Architecture findings

AF-059-01: cross-resource file/audit consistency requires durable prepared journal and recovery before next apply. AF-059-02: cookie authority must not leak into Bearer API; isolate path and enforce CSRF. AF-059-03: admin metadata is not knowledge authority; all data projections require RLS and pre-materialization bounds. See [model](../../uml/dashboard.md).

## Supporting artifacts

Formal HTTP behavior in `contracts/dashboard.md`; data lifecycle and recovery model in `docs/uml/dashboard.md`; no separate research artifact is needed.

## Implementation structure

S05901: SQL/authenticated browser shell/bootstrap/policy preview-apply and journal. S05902: scoped operational views/setup/heartbeat/assets. S05903: integration, reviews, docs, cloud and full verification.

## Playbook obligations

PB-059-01/02 in `docs/15-dashboard.md`, coordinator owner; content review and browser/copy rehearsal block delivery. Existing PB-058 upgrade/restore is reused, with025/version additions; no new production/canonical operation is authorized by the PR. Development whole-tree review and isolated upgrades are validated by this feature's test/verification record.
