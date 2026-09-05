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
  checked. [Measurements](../../../docs/benchmarks/2026-09-06-retrieval-quality/README.md).
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

Implementation, independent review, full tests, package and measurements complete.
Fresh backup-gated migration013 activation, canonical content/pin verification,
publication/CI and issue closure remain pending. OpenSpec archive follows those gates.
