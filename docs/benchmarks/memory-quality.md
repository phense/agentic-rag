# Run and interpret the synthetic memory benchmark

`rag benchmark` measures the real audited document gateway/mining and search paths
in a newly created local PostgreSQL database. The shipped corpus contains 26
fictional source documents and 60 labeled English/German questions (48 answerable,
12 explicitly unanswerable). Families, including translations and current/historical
versions of a fact, stay together in a fixed development or held-out partition.
It includes exact identifiers, paraphrases, project distractors, corrections, expiry,
long-tail evidence, cross-session and multi-hop questions. No private store content
or transcript is copied into a run.

## Produce a local retrieval baseline

Use the normal development installation (Python 3.13+, PostgreSQL with pgvector).
The configured database owner needs CREATEDB and the existing migration privileges.
An empty configured host selects loopback `127.0.0.1`; a local Unix socket directory
can be configured explicitly. Unset `PGHOST`, `PGHOSTADDR`, `PGSERVICE` and
`PGSERVICEFILE`: inherited libpq routing is rejected. There is no database-name or
cleanup-target option. The canonical database is never the benchmark's target.

```bash
rag benchmark run --search-mode fts --output /tmp/rag-bench-fts
rag benchmark run --search-mode hybrid --output /tmp/rag-bench-hybrid
rag benchmark compare /tmp/rag-bench-fts/results.json /tmp/rag-bench-hybrid/results.json
```

The hybrid run uses configured local Ollama embeddings. FTS deliberately exercises
the real embedding-unavailable fallback, including its warnings. Neither command
invokes an answer/extraction provider. Output directories must be new or empty.
Each contains the exact `corpus.json` bytes, `results.json` and `report.md`.

For exact dataset replay, pass `--corpus /tmp/rag-bench-hybrid/corpus.json` and a new
output directory. The report records corpus/source SHA-256, repository revision
(when available), model/prompt IDs, Python/platform and non-secret settings. The
source hash also identifies uncommitted code; revision alone does not prove a clean
checkout. Custom corpora must be explicitly synthetic and follow the shipped schema.
A saved report supports offline evidence inspection/comparison; interrupted runs
are restarted, not resumed. Hard process death can leave a random test database;
normal exceptions trigger cleanup and a committed ownership marker is checked
before dropping it. During marker initialization, only the creator connection can
drop the exact database it just created. No wildcard cleanup or DROP FORCE is used.

## Separate extraction and answer quality

These stages call the configured Codex/Claude provider and can consume paid usage.
Use them only within the operator's authorized evaluation budget. For a bounded
smoke test (four required sources, two distractors, eight questions):

```bash
rag benchmark run --mode end-to-end --search-mode hybrid --limit 8 --smoke \
  --answers --judge --output /tmp/rag-bench-e2e-smoke
```

This uses actual synthetic JSONL session mining, then search, answer generation and
a separately recorded model judge. `--smoke` reduces the corpus and is not a full
quality baseline. Without `--smoke`, all 26 sources are ingested even if queries are
limited. Each source is windowed using production mining caps; answer and judge
requests are batched by ten. `--answers` can also measure answer quality after curated
document ingestion (`--mode retrieval`), separating extraction losses from retrieval.
The deterministic integration test doubles only the model response boundary; it
verifies pipeline behavior, not real model quality.

Spot-check model grading by inspecting `rows` in `results.json`: compare question
and labels in `corpus.json`, `context`, `answer_text`, deterministic `answer` and
`judge.reason`. Include negative, stale/current, multi-hop and long-tail cases and
all disagreements. Record the sampled query IDs and your verdict with the run;
do not treat an unreviewed model judge as ground truth. No model-judged baseline is
claimed by the initial local retrieval measurements.

## Metrics and comparison rules

- **Recall@5/10 and MRR:** source-level evidence retrieval across all answerable
  queries, including failed ingestion/indexing and search cases. Multi-hop cases
  require all labeled source IDs for full recall. Duplicate chunks consume rank
  positions. Source retrieval does not prove the answer survived snippet/context
  clipping, particularly for long sources.
- **Answer accuracy:** deterministic word-boundary alias matching, with explicit
  abstention and stale-answer checks. It is a transparent heuristic that can miss
  semantic errors; `judge_accuracy` is reported separately. Failed answer/judge
  requests stay in denominators. Unanswerable accuracy and false abstention are
  separate; all unexecuted answer metrics are null, never fabricated zeros.
- **Context and latency:** at most 4,000 context characters by default, exact
  character counts, clearly estimated tokens (`ceil(chars/4)`), and measured
  retrieval p50/p95 plus ingestion and model-batch timings. Retrieval latency does
  not include answer generation. Index readiness requires chunks (and, in hybrid,
  embeddings) for all documents produced by each source.
- **Uncertainty:** fixed-seed query bootstrap intervals are in JSON. The tiny,
  synthetic corpus and correlated bilingual pairs limit generalization; a perfect
  recall interval does not establish perfect real-world retrieval.
- **Cost:** structured provider CLI billing/token usage is not exposed. Reports
  record attempted model commands and explicit unknown cost/usage rather than
  estimating a dollar amount from undocumented usage.

Compare candidate retrieval changes using the same corpus, query/source selection,
answer/judge configuration, prompt/provider identity and context budget. `compare`
rejects mismatches and prints metric deltas. Tune with `--split dev`, freeze the
candidate, then evaluate `--split test`; report both partitions, not just wins.
The runner also emits per-category results. A run with operational failures exits
3 while retaining its completed report; low quality scores alone do not fail the
command. Setup errors use normal CLI error codes and do not represent a scored run.

The offline CI workflow runs the metrics, corpus, model-failure and cleanup-safety
contracts without PostgreSQL, Ollama or credentials. Full integration tests additionally
verify real database cleanup, the CLI, audited save/search and the mining boundary.

## Recorded runs

- [Full 60-question local retrieval baseline](2026-09-05-memory-baseline/README.md).
- [Authorized eight-question real-model smoke and complete inspection](2026-09-05-memory-model-smoke/inspection.md).

The second run checks the actual extraction/answer/judge pipeline and deliberately
retains its small denominators; it does not replace the full retrieval baseline.
