# Change Design: Adaptive retrieval fast paths

## Context

search.search calls try_embed_texts before SQL. SQL hybrid_search_candidates already enforces
scope/source/time filters and returns bounded candidates. SearchHit presentation adds evidence
spans; graph and validated reranker stages run afterward. Keep this shared finish path intact.

## Interface contracts

| Boundary | Existing contract | Delta | Failure behavior |
|---|---|---|---|
| Python search | Existing arguments and hit/warning pair | strategy=auto/hybrid/lexical keyword | invalid strategies rejected before side effects |
| CLI search | --json results/warnings | optional --strategy | argparse validation |
| MCP memory_search | existing optional parameters | optional strategy | normal validation failure |
| Database | migrations 001–014 | SELECT-only queries | no new objects or migration |

## Dependencies

Existing PostgreSQL/pgvector and Ollama only; no new model, daemon, provider or package.

## Tests

First write red tests for exact/identifier zero-embedding behavior, selective domain/project/time
and source trust, misses and semantic fallback, strategies, old clients, citations and readers.
Run affected suites, full Python suite and Node tests. Use synthetic gateway-seeded data and
reader-role production transactions. Capture three paired practical cases and source fingerprints.

## Decisions

Only canonical UUIDs, lower-case hyphenated slug selectors, and standalone strong error symbols
qualify. Natural-language questions do not route based on arbitrary score thresholds. A lexical
shortcut must have a surviving exact-symbol result; empty/ineligible probes revert to hybrid.
Exact ID lookup joins eligible documents with original chunks; generic get remains unchanged.

## Risks and rollback

False shortcut inference is minimized by strict selector syntax. Every shortcut uses the same
source/domain/scope/time filters as hybrid. The explicit hybrid strategy and untouched old binary
provide rollback without a data migration. Compare forced hybrid to the pre-feature source to
prove that the baseline is preserved; report any measured non-improvement honestly.

## Playbook obligations

None beyond existing install/restart/rollback guidance: there is no production write operation.
