# Design: bounded search delta

## Context

Existing migration011 hybrid_search_temporal fuses top50 chunks per vector/EN/DE branch;
search.py returns prefix400 snippets. Migration012's assertion_eligible composes evidence
trust and valid time. Keep that predicate before every candidate limit. Chunker hard
bounds chunks at4000 characters. No new storage ownership or mutation semantics.

## Interfaces and decisions

Add migration013 search candidate function, retaining existing temporal function as
explicit baseline/compatibility. Vector search first draws at most256 eligible ANN chunks (function-local ef_search256);
FTS uses all matching chunks. Within each branch pool, cap a document at two candidate chunks
before top50; order ties by document/idx/id. Python final selection prefers one chunk
per document then an additional chunk when it contributes different evidence terms.
ANN selection is approximate; very large duplicate runs and selective filters can exhaust
the pool. Stable ties apply after ANN selection, not across arbitrary index rebuilds.
Candidate content is bounded by existing chunker. Return a contiguous <=400 character
query-centered span, offsets in original chunk, stable chunk ID citation and match score
metadata. Exact error/symbol identifiers are preserved; no fuzzy rewriting of symbols.

A bounded optional graph_depth0..2 uses the existing edge store with explicit scope/history/
as-of and evidence-bearing predicates; expansion is limited to a small seed/edge/result
budget. Defaultdepth0. A caller-supplied local reranker may reorder only the supplied
candidate identities; invalid output/failure warns and falls back to deterministic
hybrid ordering. No reranker model/dependency enabled without gain under p95<=500ms on
the synthetic local fixture (budget is a fixture decision, not a production SLA).

Relevance calibration compares labeled negative and positive queries; RRF is never a
probability. Exact-symbol mismatches may abstain. A cosine cutoff or generic query
rewrite is only enabled if dev measurements reduce false positives without losing
positive evidence. Keep no generic cutoff if evidence is insufficient; report result.

Benchmark gains a prior-retrieval baseline option and fixture graph links/expected
snippet text, output evidence coverage, false-positive retrieval rate and selectors.
Run equal k/context budgets and disjoint dev/held-out families, inspect before/after.
Graph and rerank experiments are separate; scope/time/evidence filters remain binding.

## Verification and rollback

Tests: document crowding, distinct extra evidence chunk, >400-char match, exact symbols,
German text, no-answer queries, stable ties, invalid reranker fallback, embedding
fallback, bounded two-hop scope/validity filtering and contiguous citation offsets.
Full regression, package, independent migration/interface review, held-out measurements.
Migration adds a read function only, no legacy data rewrite. Fresh backup and worker
lock precede matching code activation; old search remains an explicit fallback, never
an alternative curation version. Rollback via forward fix or verified backup.
