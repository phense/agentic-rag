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
