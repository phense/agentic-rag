---
id: R083-RESULTS
title: BGE and Jina omni embeddings on the local CPU fixture
type: reference
doc_id: standalone
readers: [retrieval-maintainers]
status: drafted
version: 0.6.33
depends_on: [../../provider-indexes.md]
assets: []
last_reviewed: 2026-11-04
summary: Retain BGE; Nano is faster on this fixture but has mixed retrieval results, while Small exceeds the frozen CPU time budgets.
---

# BGE and Jina omni embeddings on the local CPU fixture

Retain the current BGE profile. Nano produced embeddings faster on this VM, but
the independent questions do not show a retrieval advantage. Small exceeded
both scheduled time budgets. No production model, stored vector or provider
setting was changed. These measurements support that bounded recommendation;
the wider acceptance criteria in [Issue 83](https://github.com/phense/agentic-rag/issues/83)
remain partly unproven.

The intended reader maintains retrieval profiles and understands the existing
[generation workflow](../../provider-indexes.md). Application 0.6.33 adds opt-in
task prefixes and the reproducible comparison tools. Measurements used the
0.6.32-based source revisions listed below. A release label does not establish
that a served endpoint implements the measured native Jina recipe.

## Terms

| Term | Meaning here |
|---|---|
| Native | Direct local model inference; Jina uses its pinned text loader and adapter, BGE uses an owned Ollama daemon. |
| Canonical | Actual stored `# title` plus body input, one chunk per document. |
| Recall@k | Fraction of labeled relevant documents present among the first k results. |
| All-required@k | Every required source group has a representative among the first k results. This differs from recall when sources are alternatives. |
| MRR | Mean reciprocal rank of the first relevant result; 1 means a relevant result ranks first for every supported question. |
| nDCG | Ranking score that discounts later results and uses graded relevance labels. |
| p95 / p99 | Nearest-rank warm inference durations below which 95% / 99% of observed calls fall. |
| RSS | Sampled resident memory of the worker process tree, including its owned model daemon. |
| Replay | HTTP responses containing previously measured vectors for exactly matched model, role and input bytes. It tests storage/recovery, with no model timing claim. |

## Models, data and source identity

| Model | Immutable identity | Native width / format | Weight terms |
|---|---|---|---|
| BGE | `bge-m3-q8:latest`, digest `7f5f712dd874a537ca5cbbd6366cec74ebef63e364e102ec070836e8b7ed340d` |1024 / GGUF Q8_0 | MIT |
| Jina omni nano | `jinaai/jina-embeddings-v5-omni-nano`, revision `14b55e6b7004a8b6d53a6a8d2ff3cf69a502bd50` |768 / float32 | CC BY-NC 4.0 |
| Jina omni small | `jinaai/jina-embeddings-v5-omni-small`, revision `950200abde3a3bcf3d5bdfe5d28fb5bb5e7dfbb0` |1024 / float32 | CC BY-NC 4.0 |

Commercial Jina adoption requires a separate license decision. The current BGE
digest matched the local and Hetzner configuration at discovery; the identity
of historical legacy vectors cannot be reconstructed from today's tag.
[Model manifests](provenance/model-manifests.json) record the artifact hashes.
The complete omni snapshots were staged, but only their text modality was loaded.
No hosted inference or private corpus was used.

The [frozen corpus](corpus.json) has 46 fictional CC0 documents, 23 German and 23
English, and 100 original questions: 94 supported and 6 unsupported. Eight
questions are development examples; the other 92 are nominal single-author
held-out questions. The [independent supplement](independent-public-queries.json)
adds 16 questions, 14 supported and 2 unsupported, written before inspecting any
measurement output. It is reported separately. Unsupported rankings are retained
but excluded from relevance averages; retrieval alone provides no answer-abstention
or supported-answer guarantee.

The [protocol](protocol.json), [canonical v2 input](canonical-inputs-v2.json)
and [errata](errata.json) retain the original freeze and its limits. Jina uses
the retrieval adapter, last nonpadding token pooling, L2 normalization,
float32 and explicit 8192-token validation, with `Document: ` / `Query: `.
The tokenizer's default 512-token truncation is not used. Nano is never padded
to 1024 dimensions. Longest canonical text is 2915 characters, so the full 4000-character
application boundary is not measured on the real models.

| Evidence | Source revision / provenance |
|---|---|
| Original primary run | Exact historical [runner](provenance/original-run_models.py), SHA256 `edb5b515fc54e62c12b45a964fdca938a6b50ca7b49fae0bfcce628d05c6e592`; frozen worker hashes in raw input manifests. |
| Corrected Small primary | `02abd30d42e8afc1742a02d446e98337dc98035c`; its new output preserves the earlier loader failure. |
| Canonical run | `1ef9af416aa62bf1ced9882662e01f9a482a1fc9`; [freeze](provenance/canonical-freeze.json), input SHA256 `37a25d5929a851ec0d8fe67da5f1a571841041e1719fb3797198ba2a02622131`. |
| Populated replay and export | `2ced8e0`; reports bind exact script, input, result and vector hashes. |

## Observed retrieval and latency

The [complete report](results/report.json) includes per-question rankings,
Recall@1/3/5/10, all-required coverage, MRR and nDCG grouped by language,
question family, split and cross-language status. The tables below select a
few aggregate measures; all supported and missing denominators remain in the report.
No reranker was enabled.

| Primary body-only vector retrieval | BGE, 3 completed runs | Nano, 3 completed runs | Small, 1 partial failed run |
|---|---:|---:|---:|
| All-required@1, supported questions |79/94 (84.04%) |82/94 (87.23%) |80/94 (85.11%) |
| All-required@3 |94/94 |93/94 |94/94 |
| MRR |0.9291 |0.9441 |0.9344 |
| Warm query p50, range across runs |1.499–1.615 s |0.295–0.327 s |3.328 s |
| Warm query p95 |1.960–2.019 s |0.550–0.641 s |5.253 s |
| Warm query p99 |2.144–2.320 s |0.650–0.758 s |5.896 s |
| Peak sampled RSS, range |1.544–1.558 GB |1.926–1.944 GB |2.451 GB |

Each warm distribution contains 100 calls per run. Identical ranking metrics
across the three BGE/Nano repetitions are retained as repetitions, not counted
as three independent sets of questions. Small completed these 100 queries and 46
document vectors before its 1800-second candidate deadline; it did not finish
deduplication or the remaining scheduled stages, and two repeats were unattempted.
Its partial query scores do not make the overall experiment successful.

| Canonical vector retrieval | BGE 1024 | Nano 768 |
|---|---:|---:|
| Original supported: all-required@1 |78/94 (82.98%) |84/94 (89.36%) |
| Original supported: MRR |0.9238 |0.9557 |
| Independent supported: all-required@1 |12/14 (85.71%) |11/14 (78.57%) |
| Independent supported: MRR |1.0000 |0.9643 |
| All-required@3 and@10, both slices |100% |100% |

Query-paired bootstrap intervals use 4000 resamples and seed 8301. For Nano minus
BGE, the original canonical all-required@1 difference is +6.38 percentage points
(95% interval 0 to +13.83). On the independent supplement it is −7.14 points
(−21.43 to 0). The primary MRR difference is +0.0151 (−0.0115 to +0.0426).
The fixture therefore supplies no general quality winner.

Analytically truncating Nano to 256 dimensions and renormalizing gives 83/94
original and 11/14 independent all-required@1, with all-required@3 at 100%.
This is a separate vector-ranking calculation. No 256-dimensional managed
generation, index-size measurement or served-endpoint parity is claimed.

The populated replay also executed 232 real managed hybrid searches, 116 for
each complete model. For this fixture their document rankings produced the same
aggregate scores as canonical cosine retrieval. Those are SQL and lifecycle
observations over replayed vectors. They do not prove the quality or latency of
a live Jina service.

### Attributable examples

These are illustrative canonical queries selected from the exported rankings,
not additional quality evidence. All use the frozen documents and labels.

| Question | BGE before / Nano candidate | Measured consequence |
|---|---|---|
| `compound-a-en`: "Who checks the consumption-based heating bill for Spruce house?" (nominal held-out) | Relevant `compound-a` moves from rank 2 to rank 1; `compound-b` moves down. | Reciprocal rank 0.5 to 1.0. |
| Independent `ind-03`: "Für welche Anlage gilt der Auftrag TKT-7381 und welcher Treiber darf dort ersetzt werden?" | Relevant `ids-b` moves from rank 1 to rank 2, behind `ids-a`. | Reciprocal rank 1.0 to 0.5. |
| Same 100 original query inputs, warm inference | BGE p95 is 1.960–2.019 s over three runs; Nano is 0.550–0.641 s. | Faster model calls on this VM; application response time was not measured. |

## Resource and failure boundaries

The host was an 8-logical-CPU Xeon E5-2650 VM with 16 GiB RAM and 4 GiB swap.
Workers used two CPU threads, one PyTorch interop thread and batches of four.
OS caches were retained. BGE includes an HTTP daemon and Q8 weights; Jina uses
an in-process float32 loader. BGE loads lazily during its first query, whereas
Jina loads during initialization. Their load-stage values cannot be compared
as equivalent cold-start measurements.

The 46-document primary build took 97.08–99.31 s for BGE and 52.98–63.90 s for
Nano. Raw results retain process load, first query, CPU counters and 1/2/4-client
calls (4/8/16 calls). CPU accounting can miss exited children, and the native
Jina client serializes model access. These are observations, with no CPU-efficiency,
concurrent-capacity, cgroup-memory or production SLA claim. Nano's original
measurements overlapped Small artifact-download I/O. The final canonical Small
run shared the host with light offline checks. Hetzner and Mac were not benchmarked.

The original Small run failed before inference because of an upstream loader
attribute mismatch. The separately frozen correction reached its 1800-second
deadline and preserved partial vectors. Canonical Small reached its 900-second
deadline before completing document embeddings, so it has no canonical query
score or substitution rehearsal. Failed and unattempted runs remain visible in
the [raw archive](results/raw/manifest.json); no deadline was extended.

Deduplication has 18 frozen pairs, including one incorrect positive label
(`paraphrase-32`). Results include both frozen 18-pair and erratum-excluded 17-pair
counts. BGE and Nano each have 0 false positives and 5 false negatives on the 17
completed pairs. Small has 0 completed and 17 missing pairs there. Six positives
are identical texts; all negatives are cross-language. Threshold 0.95 is
uncalibrated, and Jina's text-matching adapter differs from retrieval-role product
deduplication. These numbers cannot select a production threshold or model.

## Populated substitution and recovery evidence

The [rehearsal](populated-rehearsal.json) completed with exit 0 in 101.57 s against
an owned synthetic, multi-domain/project PostgreSQL 17 copy. Strict source and
target backups were independently restored. Across 55 tables, all 326 original
rows were retained, including IDs, pins, checkpoints and audit. Roles, memberships
and grants matched; three generation/selection derivative tables were separately
managed, and the retained BGE vectors were checked for preservation.

Both BGE 1024 and Nano 768 used the existing generation workflow. The rehearsal
covered a first batch, a provider outage with no partial batch write, bounded
resume, query-role probe failure with unchanged selection, atomic activation,
reader domain/project isolation, dimension/revision/profile rejection, new writes
during catch-up, stale rollback refusal, completed catch-up and successful rollback.
It exercised the in-process CLI parser and command dispatch with the rehearsal
configuration, plus central MCP tool dispatch. Console-script startup, real CLI
configuration loading, transport-level HTTP/MCP clients, an older binary and a
live Jina endpoint were not exercised here.
The existing provider-upgrade tests cover archived populated local/central upgrades.

[Cleanup](populated-cleanup.json) verifies removal of both owned databases.
One unrelated database remained untouched. Dump files stay private; only their
[source](source.dump.manifest.json) and [target](target.dump.manifest.json)
verification manifests are published. Replay timings are not rebuild/catch-up
performance, and the corpus is not a production-store copy.

## Reproduction and remaining acceptance

The [public supervisor](../../../scripts/run_embedding_benchmark.py) accepts
the pinned local model directory and isolated Python executable. The separate
[environment record](provenance/original-environment.txt) identifies packages;
model downloads are a staging prerequisite. Run `--help` for each command before
allocating an exclusive output directory. The main entry points from the repository
root are shown below. `BENCH_PY` names the separately installed Python
environment with the recorded model dependencies and `psutil`; `MODEL_ROOT`
contains verified `nano`, `small` and `bge-ollama` directories. `NEW_CANONICAL`,
`NEW_REPLAY` and `NEW_EXPORT` must be distinct paths that do not yet exist.
`PRIMARY` and `SMALL_CORRECTED` name the retained primary experiment directories.
The [execution record](provenance/execution.json) preserves the exact paths,
commands and exits of the completed replay and export.

```bash
"$BENCH_PY" scripts/run_embedding_benchmark.py --mode canonical \
  --python "$BENCH_PY" --models "$MODEL_ROOT" --output "$NEW_CANONICAL" \
  --canonical-inputs canonical-inputs-v2.json

PGPORT=55460 .venv/bin/python scripts/rehearse_embedding_substitution.py \
  --models bge nano \
  --inputs docs/benchmarks/2026-11-04-embedding-comparison/canonical-inputs-v2.json \
  --corpus docs/benchmarks/2026-11-04-embedding-comparison/corpus.json \
  --results "$NEW_CANONICAL" --output "$NEW_REPLAY"

.venv/bin/python scripts/summarize_embedding_benchmark.py \
  --primary-root "$PRIMARY" --small-root "$SMALL_CORRECTED" \
  --canonical-root "$NEW_CANONICAL" --hybrid "$NEW_REPLAY/report.json" \
  --output "$NEW_EXPORT" --copy-raw
```

The historical primary collector is published byte-for-byte. Raw before/after
input manifests, worker results, exact exit artifacts, partial vectors and
resource samples are allowlisted under `results/raw/`. Gzipped files record both
source-byte and archive-byte hashes; model weights and daemon private keys are
excluded. The export records its script and scorer hashes. Re-running creates a
new experiment; it must not overwrite these observations.

Issue 83 remains open for the wider unproven acceptance: complete Small stages,
real served-recipe parity, representative target-host CPU/cgroup/index-size and
rebuild/catch-up measurements, smaller-width managed generations and complete
old/local/central client behavior. No model adoption is needed to deliver the
prefix correctness fixes and honest benchmark tooling. Deferred supervisor Low
findings are [LOW116/117](https://github.com/phense/agentic-rag/issues/75#issuecomment-6635171632).
Remaining exporter negative-path coverage is tracked as
[LOW118](https://github.com/phense/agentic-rag/issues/75#issuecomment-6636690754).
Any later Jina adoption requires a new serving/parity and commercial-license decision.
