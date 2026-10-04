---
id: adaptive-search-adoption
title: Adopt or roll back adaptive retrieval
type: task
doc_id: standalone
readers: [operator]
status: reviewed
version: feature/adaptive-search against 0c8adddfaf96e105990019eef0b664c7e29ceade
depends_on: [adaptive-search-measurements]
assets: []
last_reviewed: 2026-10-03
summary: Code-only adoption preserves the populated 14-migration installation and provides hybrid/source rollback.
---

# Adopt or roll back adaptive retrieval

## Goal

Switch retrieval code while keeping the canonical store and all client integrations intact.

## Before you start

The verified source is agentic-rag 0.5.0 at `0c8addd`, with migrations 001–014. The target
is the reviewed feature PR revision. Existing PostgreSQL roles, Ollama, Python 3.13,
configuration and dependency lock remain unchanged. Earlier schemas need their existing
upgrade paths before this code is adopted. Production adoption requires separate approval;
the tests and read-only Trading measurements do not deploy this branch.

No new database migration, initialization, backfill or restore is required. Preserve the
old checkout/environment for rollback. Existing backup/restore policy continues to apply;
this change adds no write operation requiring a new migration backup. CLI invocations
use the code they start with; long-lived MCP servers need a session/server restart to
adopt a different checkout. Old and new readers can overlap without a database window.
Worker and scheduled ingestion do not need interruption for a retrieval-only deployment.

## Steps

1. Record the source checkout revision and the 14 filenames in `schema_migrations` using
   the reader role. Confirm the source/target boundaries above before selecting a target.
2. Select the reviewed target checkout using the installation's existing code/environment
   procedure. Keep its configuration and canonical database endpoint unchanged.
3. Restart the long-lived MCP sessions that should use the target. Keep the read-only and
   authorized MCP registrations and both providers' settings intact.
4. Verify a known eligible document ID, an error symbol and an ordinary question through
   the reader CLI/MCP. Verify project/domain boundaries and original chunk citations.

The selected MCP process now exposes optional `strategy` while existing calls still work.
The store still has the same migration set; adoption has executed no schema/data command.

## Check that it worked

Exact eligible ID/slug/error searches succeed without query embeddings. Ordinary questions
retain hybrid results. Pins, checkpoints, audit and queued work remain available. The
[rehearsal and paired measurements](README.md) verify these boundaries on populated data.
If behavior differs, use `rag search QUERY --strategy hybrid` or the MCP equivalent
`strategy="hybrid"` as an immediate retrieval fallback. Restore the retained source
checkout and restart the affected MCP sessions for a full code rollback. No data downgrade
or knowledge deletion is involved. A process interruption can be retried by starting the
chosen source/target process again; there is no partially applied migration state.
