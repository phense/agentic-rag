# Retrieval diversity and evidence spans

Ordinary CLI, MCP and hook searches now prefer distinct documents from the hybrid
candidate pool. An additional chunk can remain when it covers different query terms;
this is a deterministic heuristic, not a semantic proof that evidence is redundant.
Each result contains a contiguous snippet of at most400 characters, `snippet_start`
and `snippet_end` offsets in the original chunk, and a citation
`document_id#chunk_id:start-end`. Exact requested error/exception symbols take priority
when selecting the window. Offsets and chunk identity refer to that saved chunk version;
re-saving a mutable legacy document replaces its chunks.

## Candidate selection and limitations

Migration013 adds `hybrid_search_candidates`; the previous temporal function remains
available for benchmark/compatibility baselines. Vector retrieval uses HNSW with a
function-local search budget of256 and at most256 eligible candidate chunks. Within
that pool, keep up to two chunks per document before the branch's top50. English and
German full-text branches apply the same document cap over matching chunks. Fusion
uses reciprocal rank, then deterministic document/chunk ties within the candidate set.
At most150 fused candidates reach Python; evidence metadata is loaded only for final
selected documents.

ANN remains approximate. Selective filters can yield fewer than256 candidates, and
more than256 near-duplicate chunks can still crowd out a second vector-only source.
Stable result ties do not promise identical approximate candidate sets across index
rebuilds. This bounded tradeoff avoids ranking every eligible document: a read-only
measurement on the current store found the initial exact-diversity SQL took576–653ms;
bounded SQL took23–40ms versus12–43ms for the prior query. These are three-query samples,
not production p95 or a service-level guarantee. No private content was exported.

## Optional stages

```bash
rag search 'topology entry' --project /path/to/repo --graph-depth 2 --json
```

`memory_search` also accepts `graph_depth` (default0; at most2). Expansion follows
`references`, `depends_on`, `extends` and `derived_from` only when an edge has evidence.
It uses at most three seeds, eight eligible neighbors per frontier and twenty discovered
nodes, and always respects final `k`. Both endpoints obey scope, source trust and
current/as-of eligibility before limits. Edge validity also applies; `history=true`
explicitly permits historical evidence. Existing hits may act as intermediate nodes.
New graph results carry `graph_depth`; their first chunk is presented with the same span
and citation contract. Graph relevance is advisory and can introduce unrelated context.

The Python search seam accepts a local `reranker` callback. Only a complete permutation
of candidate identities is accepted; original payloads are restored. Failure or invalid
output produces a visible warning and the deterministic hybrid ordering. No reranker
model, dependency or hosted query service is enabled. Embedding outages retain bilingual
FTS with the existing warning. Graph expansion defaults off pending broader workload gains.

Scores are RRF ranks, **not probabilities**. Exact error/symbol mismatches can abstain;
ordinary semantic negatives still return candidates. No generic cosine cutoff or
confidence threshold was justified by the small development set. Consumers must not
treat a nonempty result as proof that a question is answerable.

## Reproduce the comparison

```bash
rag benchmark run --corpus agentic_rag/benchmark/corpus-retrieval-v1.json \
  --retrieval-baseline --output /tmp/retrieval-before
rag benchmark run --corpus agentic_rag/benchmark/corpus-retrieval-v1.json \
  --output /tmp/retrieval-after
rag benchmark compare /tmp/retrieval-before/results.json /tmp/retrieval-after/results.json
```

For separate experiments add `--graph-depth 2`, `--local-rerank`, or `--query-expansion`
to the after command, each with a fresh output path. The benchmark reranker is a cheap
lexical-overlap ordering, not a learned model. Expansion uses explicitly authored
`expanded_query` fixture text; exact symbols are never rewritten. It neither invokes
a model nor implements a production rewrite policy. Expansion text excludes answer
labels. Baseline mode rejects these optional stages so reports cannot silently claim
an experiment that was ignored.

`evidence_recall` measures labeled evidence strings surviving the bounded context,
separately from source recall. `false_positive_rate` is the fraction of unanswerable
queries that retrieve any source, not generated-answer hallucination rate. Read the
[measurements and limitations](benchmarks/2026-09-06-retrieval-quality/README.md).
