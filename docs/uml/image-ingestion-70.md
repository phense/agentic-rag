# Source-backed image ingestion (RAG-070)

- Mode: design-time gate (2026-11-03) against store.py, evidence.py, evidence_contract.py,
  SQL012/021/029/035, service/api.py, service/context.py, service/upgrade.py and the
  RAG-070 plan. As-built reconciliation is appended below the diagrams.
- Purpose: AC-001..007, IC-001..005, AF070-001..007. Which component owns authority,
  trust, identity and atomic publication for an image and its derivations?
- Notation: Mermaid. Semantic source review only; no renderer dependency added.

## Data and authority

```mermaid
classDiagram
    class image_originals {
      id uuid PK
      source_key FK knowledge_sources UNIQUE
      domain, project_scope (immutable copy of the write scope)
      sha256, mime, width, height, byte_size
      bytes bytea NULL only after operator erasure
      erased_at timestamptz
      created_by, created_at
    }
    class image_derivations {
      id uuid PK
      original_id FK image_originals
      kind ocr|interpretation
      identity_hash, identity jsonb
      status text|empty
      text, text_sha256, regions jsonb, warnings jsonb
      document_id FK documents NULL
      created_by, created_at
    }
    class knowledge_sources {
      source_key = H(namespace, "sha256:" digest)
      role unknown
      state active|refuted|removed
    }
    class documents {
      dtype source
      claim kind stated (OCR) | inference (interpretation)
      review unreviewed until explicit confirmation
    }
    image_originals --> knowledge_sources : one source per scoped original
    image_derivations --> image_originals
    image_derivations --> documents : claim (absent when empty)
    documents --> knowledge_sources : claim_evidence spans (complete=false)
```

RLS: `image_originals` uses the stable SQL021 document-visibility helper on its own
immutable `domain/project_scope` columns (no reference to another table).
`image_derivations` is visible only through `EXISTS(image_originals)`. Neither policy
references `documents`, `claim_evidence` or `knowledge_sources`, so no policy can
re-enter itself. Both tables are insert-only for `rag_writer`; no UPDATE/DELETE grant.
Source trust and claim review stay in the existing registry and are checked by the
image gateway on every read and publication, in local and central operation.

## Upload, validation and atomic publication

```mermaid
sequenceDiagram
    participant C as CLI file or central upload
    participant G as images gateway
    participant V as Bounded decoder subprocess
    participant E as Tesseract / loopback Ollama subprocess or HTTP
    participant D as PostgreSQL (RLS, audit, evidence)
    C->>G: bytes <= 4 MiB, domain/project, opt-in flags
    G->>G: magic, header dimensions, frames, pixels (no decode)
    G->>D: authorization precheck (domain, write scope)
    G->>V: complete decode, time/memory/output limits
    V-->>G: format, size, frames confirmed or bounded failure
    Note over G: any failure so far: zero writes
    G->>D: Tx A: lock(source_key); refuse withdrawn source; insert source + original; audit; commit (authority recheck)
    G->>D: read derivation for (original, kind, identity) - exists: return, zero engine calls
    G->>E: OCR (and optional interpretation), no transaction or lock held
    E-->>G: bounded TSV / response, identity re-verified
    G->>D: Tx B: lock(source_key); recheck original, source active, duplicate; claim via evidence gateway; derivation row; audit; commit (authority recheck)
    alt engine failure, timeout, revoked writer, audit failure
        G-->>C: explicit code; original retained; no partial derivation
    else concurrent duplicate
        G-->>C: existing derivation, no second claim
    end
```

## Historical processing

```mermaid
stateDiagram-v2
    [*] --> Preview: explicit manifest (paths or stored original IDs)
    Preview --> Preview: selected / unchanged / changed / missing / unauthorized / invalid / withdrawn
    Preview --> Apply: --apply --limit N
    Apply --> Apply: one successful or explicitly skipped item, then cursor fsync
    Apply --> Blocked: failed derivation, cursor unchanged
    Blocked --> Apply: fix cause and rerun --apply
    Apply --> Paused: limit reached
    Paused --> Apply: rerun --apply
    Apply --> Canceled: SIGINT/SIGTERM between items, or --cancel marker
    Canceled --> Apply: rerun --apply (signal) or --apply --resume (marker)
    Apply --> Interrupted: unavailable engine or transport outage stops the run
    Interrupted --> Apply: rerun --apply
    Apply --> Complete: cursor at end
    Complete --> [*]
```

The cursor file is an operator convenience only; correctness under loss or concurrent
reruns comes from the idempotent scoped source/derivation keys in PostgreSQL.

## Derived integration cases

Success: real PNG/JPEG/WebP decode + real Tesseract TSV → audited claim → region and
original drilldown → explicit confirmation → retrieval, through local CLI/MCP and the
central REST upload. Recovery: engine timeout followed by successful retry, revoked
writer at commit, audit failure, concurrent duplicates, source withdrawal and
reinstatement, changed identity with preserved review, interrupted backfill resume,
populated 0.6.17/029 and 0.6.23/035 upgrade with independent restores.


## As-built reconciliation (review correction candidate)

The gateway retains Tx A before engine work; Tx B records a derivation, the
existing claim/evidence audit and any detected-secret withdrawal together.
`secret_redacted` withdraws the whole scoped source: raw pixels cannot be redacted.
Original downloads and region drilldown recheck source state. The operator-only
`image erase` command previews by default, fences the exact original digest,
removes payloads and exclusively supported claims atomically with an audit, and
leaves a content-free tombstone. Shared claims and other originals survive.
Limited roles retain INSERT/SELECT only; erasure uses an explicit local admin
connection and rejects service/fence/queued contexts. No erasure REST/MCP route exists.

Claims deduplicate through the existing evidence gateway across originals in one
scope. A source-derived slug includes its scoped source/kind/text digest to avoid
foreign collisions. A new identity with unchanged text reuses the same claim and
preserves human review. Changed text creates an unreviewed claim with `previous_id`;
older claims display `newer_derivation_differs`, including retrieval metadata, and
receive changed evidence review tokens. No machine reading silently refutes a
human decision. Failed backfill items do not consume their cursor.

Independent correction review, final full-suite verification and representative
restores remain acceptance gates; this section reconciles the implemented design,
not production readiness. Upload buffering still occupies a shared gateway slot
before authentication (R070-L3), and the engine runner still uses `preexec_fn`
(R070-L4); these are disclosed residual risks pending a separate bounded fix.


### Second correction reconciliation (review candidate)

The canonical SQL `rag_document_version` now includes visible latest image
readings; the Python contract delegates to it on schema036, preserving every
non-image token. This also keeps synthesis dependency freshness consistent.
Erasure locks affected claims and re-evaluates all support after deletion, so
concurrent erasures cannot retain an unsupported transcription. Detected-secret
quarantine is persisted in derivation warnings and cannot be reversed by normal
source-state transitions; original reads enforce it independently of source trust.
Client backfill distinguishes explicit item errors from service failures.
The pre-OCR visibility interval, retained digests/cache and pinned-claim erasure
limitation remain documented limits, not claims of complete privacy sanitization.
