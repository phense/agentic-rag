#6.10 implementation tasks

### Slice S06801: Durable foreground execution
- [x] T06801 Red tests for durable handles, replay, fair quotas, expiry/cancel,
  foreign/RO/revoked result denial and atomic mutation rollback; FR03–06/AF01–03.
- [x] T06802 Implement024,requests.py,queued_transaction.py,API/client/spool
  negotiation and fixed executor; depends01; real DB/HTTP correction tests.
- [x] T06803 Add foreground/model priority and bounded background deferral;
  FR07/AF04; depends02; prove foreground progress and resumed extraction.

### Slice S06802: Native packaging and compression
- [x] T06804 Red package preservation/rollback and host event/compaction tests;
  FR01–02/AF05; depends02 shared connector.
- [x] T06805 Native manifests, package operator, shared MCP/lifecycle bridge and
  separate Gemini adapter; depends04; preserve existing local adapters.

### Slice S06803: Compatibility, operations and complete acceptance
- [x] T06806 Populated023→024 strict restore, version/dependency/docs update and
  PB06801 rehearsal; FR08–09; depends03/05.
- [x] T06807 Real40-client/p50/p95/resource and2–3continuity traces, full Python/
  Node checks and independent full-range review; fix C/H/M, append Lows75.
- [x] T06808 Publish tested stacked PR, immediate T3link, canonical68evidence;
  no merge/cutover without specific authorization; depends06/07.
