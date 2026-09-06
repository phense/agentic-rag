# RAG-008 verification

- Full regression: `PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`
  →732 passed in24.22s, after all implementation and review fixes.
- Twelve retrieval tests cover lexical and vector-only document crowding, late spans,
  exact-symbol priority and stable offsets, distinct extra chunks, deterministic ties,
  embedding/reranker failure, untrusted reranker payloads, existing graph intermediates,
  scope, source withdrawal, expired facts/edges, history/as-of and traversal budgets.
  Two additional offline benchmark contracts verify disjoint facts and evidence metrics.
- `uv build --wheel --out-dir /private/tmp/rag-issue8-wheel` passed. Archive bytes for
  retrieval.py, migration013 and the new corpus equal the source tree. Both reader search
  and function-local ANN-setting restoration are tested.
- Eleven synthetic benchmark runs completed without indexing/query failure; every owned
  database cleanup verified; zero hosted model calls. Equal context/k and source hashes
  checked. [Measurements](../../../../docs/benchmarks/2026-09-06-retrieval-quality/README.md).
- Independent reviewer `/root/review_issue8` inspected the complete tracked/untracked
  change from126a2b3, requirements, regressions and plan evidence. Final verdict: Ready;
  no unresolved Critical/Important findings. Reviewer did not implement or run DB tests.

## Review findings and disposition

1. Existing lower-ranked graph intermediate was premarked visited: reproduced failing
   regression, then separate frontier visitation from result promotion/deduplication.
2. Generic terms displaced an exact late error symbol: reproduced failure, prioritize
   exact-symbol windows before lexical coverage, preserve original contiguous offsets.
3. Dev/test shared source facts: separate sources/answers, explicit families and offline
   disjoint-source test. Reports state author-known synthetic fixtures, not blind holdout.
4. Missing expansion eligibility evidence: source-refutation, expired edge/assertion,
   as-of/history, evidence-before-limit and bounded traversal tests added and passed.
5. Coordinator SQL measurement found corpus-wide ranking cost576–653ms: replace with
   bounded HNSW256 pool, document approximate coverage limits, verify actual index plan
   and reader setting restoration. New SQL23–40ms in three read-only measurements.

## Release state

Completed2026-09-06 after explicit operator approval. Migration013 activated and replayed
idempotently; fingerprints for all8210 documents and22 pins unchanged. Installed main
search returned three hits with exact original-chunk offsets/citations, working local
embeddings and reader UPDATE denied. The newest automatic backup was over seven hours
old, so the existing backup agent refreshed it at10:33 local time; archive readability
and local/cloud SHA equality passed. Closely spaced rollouts may reuse a recent verified
backup per the user's instruction; no per-issue fresh backup rule is imposed.

Published implementation/head8591c63: [CI passed](https://github.com/phense/agentic-rag/actions/runs/34022212748).
[Issue8 closed](https://github.com/phense/agentic-rag/issues/8#issuecomment-5558065758).
Fresh pre-archive verification:
`PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest tests/test_retrieval_quality.py tests/benchmark -q`
→39 passed in4.60s. Final documentation synchronization/archival contains no code change.
