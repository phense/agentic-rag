#6.10 technical plan

Owner: coordinator, sequential cohesive slices. Base07f989f. Same already-isolated
checkout, new feat/agent-plugins-68 branch; PR stacks on76, never merges it implicitly.

1. Add024 queue/control tables and scoped guards. Owner-side admission/claim/status
   helpers never return stored credentials or foreign rows. Finite TTL and timestamped
   idempotency envelopes prevent replay after bounded tombstone deletion. Dispatch
   in the API lifespan with two fixed consumers, not a process per session.
2. Queue canonical mutations in one deferred-commit connection group. Existing
   gateway commit calls still revalidate authority, but final physical commit
   includes the result/terminal receipt. Context managers cannot prematurely close
   or commit that transaction. Read requests use existing RLS connections. Per-job
   database execution pins fence orphan recovery and completion after lease loss.
3. Add negotiated client requests and persisted local handles/outbox to existing
   private SQLite spool; a wait timeout returns a useful handle, never cancellation.
   Preserve opt-in/legacy synchronous transport. Plugin MCP adds bounded status/
   cancel tools with the original read-only/main distinction.
4. Record foreground activity with leases and gate new background work/model pages.
   Shared embedding admission serializes calls with foreground preference;
   background pages are single-input with a finite request deadline. Active source
   extraction can retain accepted output and retry application without new inference.
5. Package actual host manifests plus common Python lifecycle/MCP bridge. Keep
   existing host-specific parsers/installers; Gemini CLI gets its own documented
   JSON transcript/event adapter, not agy's camelCase schema. Native package
   files use ownership hashes and conflict-safe update/uninstall records.

Compatibility:0.6.11/schema024; known sources018–024, explicit023→024 rehearsal.
Old source jobs, queue vocabulary and embeddings remain. Do not downgrade DDL;
code rollback can leave additive024 in place and use legacy synchronous access.
Stop only owned test services for crash probes. Public artifacts contain aggregates.

System playbook PB06801 docs/playbooks/agent-plugins.md: package/config/enroll/disable,
queue full/offline/accepted wait/cancel/expiry, source retention and staged update.
Coordinator authors/reviews/rehearses during slice3. Development tests use isolated
PG55458 and owned databases, as in DB05801. No production migration required.

Testing: meaningful red behavior tests before each slice, real SQL/HTTP/transactions;
mock inference only at provider boundaries. Bundle1–3 major full-range reviews/test
rounds; independent Sol high, sparse use. Upgrade original-row/ACL comparisons,
40-client queue benchmark, compaction traces and full Python/Node before PR.

## RAG-068-A1: native origin correction and remaining acceptance

Continue the merged implementation from29a2f44 (0.6.20/schema032) on the
existing isolated acceptance branch; preserve the old RAG-068 run and evidence.
The actual Claude2.1.314 manual probe revealed `isCompactSummary:true` inside a
`user` message. Treat outer conversation type and generated-origin flags as
authoritative before prose can become source evidence. Generated summaries,
metadata and API request mirrors do not enter extraction or continuity digests.
Raw recordings and historical normalized lengths remain available to advance
old partial `mw1` cursors without rewinding or shifting subsequent originals.

Use existing source trust rather than rewriting historical roles or documents:
an operator previews a bounded complete recording and explicit local/service
namespace, then applies its exact SHA-256 with writers stopped. The audited
source gateway atomically marks proven generated source identities removed,
including orphan tombstones for pending old batches. New inference filters
those fragments out of old staged windows. Immutable accepted batches keep
their existing replay identity and cannot restore removed source trust. This
is per-recording evidence, never a claim to have censused unavailable histories.
Review M1 requires additive migration033: only a replacement supported solely
by proven generated-origin tombstones loses its suppressive effect. Ordinary
refutation/removal/expiry and genuinely supported replacement keep the existing
no-revival rule. Inactive-source replay is review-only, with no new edge. The
DB-backed preview must cover retained windows, accepted batches and known sources;
remote export must separately cover pending SQLite outbox windows. The target
release0.6.21 still needs the populated upgrade,
backup/restore, independent review and final suite gates in T06812..14.

Native observations remain separate from adapter tests. Manual Claude compact
and native restart/resume retained all three frozen identifiers. After two
failed artificial-threshold attempts, the frozen multi-turn probe emitted a
native automatic summary plus Pre/PostCompact and SessionStart compact, then
recalled3/3 identifiers. The separate same-partition offline/reconnect probe
retained4/4 originals in2 windows after a lost ACK, with0 pending. Other native
hosts remain explicitly unobserved; Issues12–14 stay open.

The reference VM was read-only verified as4 CPUs and8,134,742,016 bytes RAM.
The owned copy completed140/140 foreground calls and8/8 background windows.
High search execution time and head-of-line queue waiting need a bounded SQL
and restored-index/statistics diagnosis (M-ACC1); the8-window phase is a fixed
initial backlog, not continuous growth. No numerical SLA has been agreed.
Keep performance acceptance open until diagnosis and independent disposition.
Use no production service, credentials or data changes to manufacture acceptance.
All production cutover gates remain.
