# Implementation plan: Thematic summaries

RAG-5.7, [spec](spec.md). Ignored worktree `.worktrees/thematic-summaries`, branch
`feature/thematic-summaries`, source `bd01d97`. Sequential implementation with
independent read-only review. No new framework or installed-wrapper mutation.
Repository `.engineering-method` and `scripts/project-state` are absent;
Git, Issue32 and these artifacts provide continuity. No event-ledger recovery is claimed.

## Design

Add thematic.py and017_thematic_summaries.sql. Cache key binds canonical scope
selection, topic, optional domain and temporal mode. One SQL statement obtains
cache and current candidate versions from the same snapshot. Eligibility filters
precede candidate limits. Fingerprints include document/chunk/claim/assertion tuple
versions, all source/span versions, assertion-source versions and superseded state.
Reads withhold changed entries and label incomplete coverage. Refresh hydrates
only changed chunk excerpts, reuses current entries and commits cache+audit together.
Source changes during hydration produce withheld entries on the subsequent read.
No-change refresh leaves generation time and audit count unchanged.

Historical mode uses current claim trust plus accepted/event/expiry qualification,
never the existing unqualified search history bypass. Expired replacements do not
revive previous current values. `historical_superseded` is retained only in the
explicit historical view and the default deployment profile theme.

Existing profile_refresh jobs call the gateway inside the profile transaction;
no new kind, payload or scheduler. Context combines theme freshness with profile
maintenance status, retains exact pins/checkpoints and the existing2400-character
profile budget, and discloses theme omission/failure warnings. Explicit domain
refresh uses CLI; main and read-only MCP expose only the new reader tool.

## Verification

Baseline1039 Python tests/7 Node tests passed. Meaningful tests exercise exact
citations, current/historical invalidation, malformed selectors, writer authority,
fresh-connection commit=False, interruption/audit rollback, concurrent clients,
SQL settings, missing migration, hook freshness and whole-entry context omission.

The acceptance driver starts with source016 on a populated gateway-seeded
multi-actor/project/domain store. It strictly verifies backup restore, transactional
DDL interruption, retry/idempotence, original rows/grants and actual old/new/rollback
CLI/MCP. A separately selected verified private source016 dump is restored only
into an owned disposable database; aggregate original-corpus costs and populated
state checks supplement public synthetic examples. No dump/body/title/identifier
is sent to a provider or included in public measurement results.

## Upgrade and recovery

017 touches only a new table; old sessions and queued work remain compatible.
No dependency reinstall, re-embedding, settings edit or service stop is required.
Migration order, source preflight, strict backup verification, code activation,
reconnect, safe retry and code rollback are PB-5.7 obligations. Any live execution
requires separate authorization after specific PR approval.
