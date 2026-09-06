# Implementation Plan: Bounded project context

RAG-009; specification spec.md; accepted for end-to-end implementation.

## Technical context and gates

Python3.13+, PostgreSQL/pgvector; hooks/session_start.py already budgets pins and
checkpoints, prompt_recall.py is error-only, jobs.py/worker.py own asynchronous work.
Gateway:store.py; reader/writer grants are separate. All gates preserved. Isolated
worktree87077ce, baseline732 passed24.46s in issue-owned test DB (external test overlay).
Shared agentic_rag_test is concurrently used by another worktree and must not be used.

## Architecture and interfaces

S1: profiles.py + migration014 store only project key, config/version key, memory
revision, built time and <=12 selected document IDs (6 stable,6 recent). Rebuild is
local deterministic extraction, not model synthesis. Store.refresh_profile is the
audited gateway; jobs.enqueue_profile feeds existing worker profile_refresh jobs.
Per-project advisory refresh lock + atomic upsert preserves last usable view on failure.

Revision is a deterministic digest of scoped visible document/claim/evidence/source/
assertion tuple versions and temporal boundary booleans, plus relevant configuration.
No global write trigger/counter or extra canonical text store. Read always revalidates
cached IDs for active scope/source/validity. Stale IDs remain visibly dated; missing
cache falls back to baseline. Cache mismatch queues asynchronous refresh at startup.
Writer profile refresh must never edit source docs, source evidence or pins.

profiles.read(conn,cfg,project) returns project,revision,generated_at,status,warnings,
sections:{stable:[items],recent:[items]}. Items:id,slug,title,text,source_keys,kind,
review_state,provenance_status,event_at,expires_at. Stable text is a complete short
supported stated convention/preference; recent excerpts explicitly label incomplete
provenance. Never imply source count means truth. Global only if no project.

S2: context_gate.py owns pure deterministic EN/DE project/history gate, safe lexical
query and replay receipt. No response cache. A receipt records only an emitted digest
keyed by host/session/project/realturn/config/currentrevision. Missing real turn IDs
skip suppression; never derive identity from prompt text. Files are local ephemeral
receipts, bounded in count, not knowledge. Mark only after successful emit.

S3: context.py is the shared read API. startup wraps existing build_context then adds
bounded profile items only within remaining budget; omissions visible. prompt mode
retrieves at most3 FTS evidence spans after gate, using scoped eligible candidate SQL,
without embedding/model calls. Dedup compares actual emitted complete text, not all
candidate IDs. CLI rag context and read-only MCP memory_context expose both modes.
Shared hooks use service; existing error recall remains prior SQL path.

Preserve startup checkpoint priority; profile/query additions may be omitted. Exact
multiline pins are whole units during truncation, never split into partial directives.
Startup maintenance enqueues a stale/missing profile independently of rendering success.
No new scheduler. Existing unrelated maintenance-failure behavior remains separate.

## Tests and rollback

Atomic refresh rollback; reader denied write; source withdrawal/expiry and correction
invalidate view/replay; project separation; stable vs recent; ordinary/irrelevant prompts;
real-turn replay vs later identical text; no-turn fallback; omitted-section dedup;
cap and exact multiline pins/checkpoint; startup->queue->worker->reader integration and
failed-refresh recovery. Synthetic replay compares baseline/new useful context, redundant
characters (estimated tokens), gate/injection precision and p95. No private model calls.
Migration014 additive table+queue kind; no backfill. Rollout reuses recent verified backup
for closely spaced issues, verifies unchanged documents/pins and idempotence.

## Ownership and dependencies

S1 profile/storage/job paths, S2 pure gate/receipt are independent. S3 consumes both only
after their contracts are verified. S4 coordinator owns integration/convergence/release.
Architecture findings AF-009A/B/C mapped in tasks; no unresolved scope decisions.
