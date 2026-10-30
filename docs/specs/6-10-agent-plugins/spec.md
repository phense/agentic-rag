#6.10: Native plugins, queued requests and compaction continuity

Canonical Issue68; base PR76 at07f989f (0.6.10/schema023). The maintainer
explicitly authorizes autonomous end-to-end implementation and tested PRs,
without merge or production cutover. Stable runtime ID RAG-068.

## User outcomes

Agents on many VMs retrieve current authorized context through one engine.
When execution is busy, they keep a durable request handle and can continue
waiting after disconnect/compaction. Session logs are captured durably before
shortening context and extracted by one lower-priority central worker.

## Requirements

- FR01: Ship native Claude/Codex plugin packages and a Gemini CLI extension;
  distinguish agy and OpenCode adapters and their actual available events.
  Preview/install/update/doctor/uninstall must preserve foreign content, pending
  source data, native memories and credentials; retain conflict-safe recovery.
- FR02: Reuse existing source/checkpoint/transport DTOs. Capture startup/resume,
  completed turns, manual/automatic pre/post compression and final tail where
  supported. Suppress subagent/fork/maintenance recursion and never fabricate
  original evidence from a compressed summary. Missing events require a tested
  fallback and explicit capability/observation matrix.
- FR03: Add opt-in protocol1 queued tool requests with durable202 handles,
  immutable idempotency identity/time, status/result/cancel/expiry and bounded
  wait. Preserve legacy synchronous REST/MCP shape. Client outboxes retain
  unsent/accepted request identity across restart and context compaction.
- FR04: Authenticate before queue admission. Recheck exact credential/session,
  current scopes and uploader before execution, canonical commit and result
  release. Owner-only job administration, including when knowledge is team-shared.
- FR05: Commit queued mutations and their completed result atomically through
  the existing audited gateways. A lost ACK/worker crash cannot duplicate effects;
  cancellation before commit rolls back the operation. Expiry must not revive a
  deleted idempotency record through a later replay.
- FR06: Bound global/owner/team queue items, payload/result bytes, age and workers;
  fair dispatch across owners/departments, finite polling and garbage collection.
  Full admission remains explicit backpressure. Expose aggregate diagnostics
  without prompt/result/credential disclosure.
- FR07: Interactive knowledge/context first, capture next, extraction last.
  One central extraction worker; foreground demand pauses new background jobs
  and model batches, including indirect shared database/Ollama work. Keep model
  residency/concurrency finite; bound already-running background model work.
  Resume background progress after foreground pressure subsides.
- FR08: Standalone remains default. Additive populated023→024 upgrade preserves
  original knowledge, embeddings, ACLs, pending source jobs and history; require
  verified backup and documented staged server/client upgrade/code rollback.
- FR09: Publish configuration, host capability/event/version/observation matrix,
  queue waiting/recovery procedures,2–3 measured practical traces, reference-host
  foreground/background latency/resource results and complete independent review.
  No unobserved host UI or production rollout is claimed as verified.

## Acceptance

AC01: Real DB/HTTP tests cover40clients with fewer execution slots, durable ACK,
full queue/local retention, fair progress, bounded polling/cleanup and finite RAM/SSD.
AC02: Lost ACK, client/server restart, queued/running cancel, expiry and replay
preserve one operation/application; revoked/rotated/scope-changed authority cannot
execute or read results. Test at commit boundary, not only on initial request.
AC03: Plugin install/update/remove preserve foreign edits and source state;
manifest/command/real hook adapter tests exercise each claimed host and manual/
automatic shortening, final tail, offline/reconnect, child suppression and resume.
Record unavailable native UI/model integration separately; keep12–14open.
AC04: Populated additive migration/strict restore pass, legacy synchronous clients
remain compatible, full suite and applicable Node tests pass; independent review
leaves no Critical/High/Medium defect, Low findings append to75.
AC05: Real4-vCPU/8-GiB copy measures interactive p50/p95 and background progress,
CPU/PSS/model residency/disk/backlogs under20–40clients; no throughput/SLA invention.
