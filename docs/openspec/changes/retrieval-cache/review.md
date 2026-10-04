# Independent review: retrieval-cache

Date: 2026-10-03. Base:`f27acd98e04c7c67d66ca374eded071ac47c0416`.
Independent read-only reviewer:`review_cache`; no implementation ownership, shared
PostgreSQL test execution or production reads.

## Findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| Low | Each QueryCache registered its bound clear method as a fork callback, preventing transient caches from being collected. | Replaced with one module callback and weak registry; GC and actual fork independently verified. |

Final unresolved counts: Critical0, High0, Medium0, Low0. No Low backlog issue is
needed because the finding is fixed. Verdict: Ready for PR handoff.

## Evidence reviewed

- Complete bounded code/tests diff, requirements, vector-only context keys, fresh SQL
  authority, model replacement/race checks, failure fallback and public call contracts.
- Eight existing embedding tests and14 isolated cache cases passed independently.
- Real fork with parent cache lock held and unfinished request: child clears vectors,
  locks, futures and transport; parent retains its state and open transport.
- Owner/waiter inference failure and exception release, capacity pressure, copies,
  role isolation, no response-cookie persistence and transient-instance garbage collection.
- Actual prior embed/search/MCP baseline and candidate file hashes verified; paired
  metrics recalculated. Empty negative case and mock correction limits are explicit.
- Coordinator's fresh864 Python/7 Node checks and populated multi-user/multi-domain
  cached/uncached coexistence, rollback and full table snapshot comparison inspected.

Merge approval and production deployment remain separate. Existing dependency security
findings in #37 are outside the feature diff and remain open.
