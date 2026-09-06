# Search

## Purpose

Bounded evidence retrieval for the shared memory store.

## Requirements

### RQ-001: Diverse bounded results

Given many matching chunks in one document and another relevant document, the result
budget must include distinct sources present in bounded candidate pools before redundant
chunks. Vector selection is approximate and bounded to256 eligible candidate chunks;
very large duplicate runs or selective filters can reduce coverage. Additional chunks may
remain when they contribute distinct necessary evidence. Deterministic ties include
document and chunk identity; result count never exceeds k.

### RQ-002: Useful evidence spans

Given a query match after character400, the returned contiguous snippet includes that
match and retains original text with stable chunk ID and verifiable start/end offsets.
Exact symbols remain exact. German lexical and semantic search remain supported.

### RQ-003: Measured optional stages and safe fallback

Measure evidence recall, ranking, false-positive retrieval, context size and p95 on
held-out equal-budget fixtures including negatives and two-hop evidence. Optional local
reranking cannot add/drop identities or bypass eligibility; failure returns deterministic
hybrid results with a warning. Embedding failure retains FTS. No hosted default query
model. Evaluate graph/query expansion separately; do not enable unmeasured rewrites or
misinterpret RRF as probability.

### RQ-004: Bounded expansion with unchanged eligibility

Explicit graph expansion is at most two hops, bounded in seed/edge/final results, and
uses permitted evidence-bearing predicates. Every candidate/hop obeys project scope,
current source trust and temporal validity; history remains explicit. Expanded hits
carry stable source citations and an indication of their graph origin.

## Compatibility

Manual get/history, exact pins, one canonical database, audited writes, source/evidence
and temporal semantics remain intact. Migration changes retrieval functions only;
legacy documents/provenance/timestamps/pins remain unchanged. Existing callers retain
search signature defaults with additive result metadata and improved ordering/snippets.
