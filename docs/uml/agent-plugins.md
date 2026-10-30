# Queued tools and native lifecycle adapters

```mermaid
sequenceDiagram
 participant H as Agent plugin
 participant C as Durable client spool
 participant A as API admission
 participant Q as PostgreSQL request queue
 participant E as Fixed foreground executor
 participant W as Serial background worker
 H->>C: source delta + handoff before compression
 C->>A: bounded source/checkpoint upload
 A->>Q: durable source ACK (existing contract)
 H->>C: timestamped idempotent tool envelope
 C->>A: negotiated queued request
 A->>Q: scoped bounded durable insert
 A-->>C:202 handle, expiry, retry advice
 E->>Q: fair claim + database execution pin
 E->>E: reauthorize + existing gateway
 E->>Q: atomic knowledge/result commit for mutation
 C->>A: status/result by handle
 A->>Q: ownership + current authority recheck
 A-->>H: result or explicit waiting/error
 W->>Q: check foreground demand before job/model batch
```

AF06801: Tool functions commit/close their own connections. Deferred connection
scope must retain a root transaction and prevent every early physical commit,
including transaction contexts. Final result and effect share one commit.
AF06802: Read result caches can survive scope revocation. Capture exact immutable
credential plus permission fingerprint; current mismatch denies release.
AF06803: Bounded idempotency cleanup risks duplicate late writes. Created-time
admission window plus retained accepted identity prevents timestamp refresh replay.
AF06804: Worker priority alone cannot control Ollama. Gate each shared model call,
use single-input background pages, and pause background job admission under load.
AF06805: Native hosts differ. Codex/Claude pre/post events, Gemini PreCompress's
advisory/asynchronous semantics and agy's fallback must never be conflated.

## As-built correction reconciliation

- Admission uses a short queue reservation separate from canonical-write capacity;
  transient execution pressure retains the accepted envelope with a1second retry.
- Result publication serializes briefly with a1second lock deadline; timeout
  rolls back uncommitted effects and retains the same accepted envelope pending.
- Client persistence precedes discovery. UUID consumption maps to the same local
  record; observation rotates across unread terminal handles. Result GC retains
  an explicit result_expired outcome without implying rollback of knowledge.
- Gemini recording roles cannot prove authorship of synthetic compression input.
  BeforeAgent also carries hook-generated continuations without an origin
  discriminator. Both observations stay separately identified advisory assistant
  context; neither supplies confirmed original user authority.
- Foreground checks cover source claims, embedding pages, curation phases/model
  iterations and opportunistic backup admission. Already running calls stay finite.
- Interrupted package changes retain both known hash generations; explicit recover
  restores only reviewed owned bytes and refuses foreign changes.

- A request deferred on source count/owner/byte pressure yields to the source
  worker that can relieve its dependency. Runnable retrieval and running writes
  still suppress new background work. Retry does not require cancellation/expiry.
