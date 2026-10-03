---
id: local-neural-rerank-measurements
title: Local neural reranker measurements
type: reference
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: feature/local-rerank against 342bccf6fce51213b7bac1560e41e7554b2e989c
last_reviewed: 2026-10-03
depends_on: []
assets: []
summary: Three paired Trading source-coverage examples, latency costs and populated rollback evidence.
---

# Local neural reranker measurements

## Outcome

Feature 5.3 / [Issue #28](https://github.com/phense/agentic-rag/issues/28) adds a
bounded adapter for a trained local multilingual query/passage model. The three
Trading development examples put more preselected expected sources into the
same three-hit context. They take about one additional second per query.
This feature improves source ordering in these examples; it does not demonstrate
a speedup, generated-answer accuracy, hallucination reduction or a general
corpus-wide quality gain. Production adoption has not occurred.

## Practical examples

Each route has 20 alternating paired repetitions plus a first call. Both use the
same query, reader-only repeatable-read snapshot, fixed as_of, project scope,
`k=3` and maximum 1200 context characters. The table shows expected source coverage
in every measured call, median and nearest-rank p95. It counts positive labels,
not exhaustive relevance judgments or precision.

| Practical case | Expected sources in top 3 | Median before → after | p95 before → after |
|---|---:|---:|---:|
| Price drift versus earnings volatility risk | 1/2 → 2/2 | 1,036.595 → 2,206.709 ms | 1,068.701 → 2,229.031 ms |
| German earnings-surprise question, English detection sources | 1/3 → 3/3 | 1,059.102 → 2,190.499 ms | 1,065.909 → 2,203.822 ms |
| Ambiguous newsletter-failure verification question | 2/3 → 3/3 | 1,057.589 → 2,024.124 ms | 1,061.704 → 2,059.029 ms |

The first case needs two complementary mechanisms: post-announcement price drift
and earnings volatility exposure. The second asks about event detection and
expects three English sources explaining a proxy, its implementation and the
observer lifecycle. The third expects three distinct failure/verification branches
in a newsletter pipeline. Their labels were read from original eligible sources
and fixed during calibration before the final paired run. Labels are positive
source examples, not an exhaustive answer or an independent held-out test set.

Across the 60 paired calls, expected-source coverage is 80/160 before and 160/160
after. Each route has 180 validated original-source citations, and the top-three
citation lists change 20/20 times in each case. Shared returned sources keep the
same complete payload, RRF score and citation. Source offsets are validated
against the original stored chunk, not against model-provided text. One unrelated
financial source still occupies the third result in the first example; two covered
labels do not mean every returned source is useful.

Full per-call timing and label-count arrays are in [trading-reader.json](trading-reader.json).
Private queries, source identifiers, bodies and labels remain in a local case
file outside the code repository. No private corpus content was published or sent
to a hosted inference service. Before/after embeddings are uncached; these are
synchronous Python retrieval measurements, not transport-inclusive MCP SLAs.
The previously delivered MCP vector cache remains available and is not credited
again here. First calls use a warm model process; process-cold results follow below.

## Model, runtime and resources

- Model: Qwen3-Reranker-0.6B Q8_0, ggml-org revision
  `a02f48bb4f057028298c21fa033da2b30d7742d5`.
- Verified file: 639,153,184 bytes; SHA-256
  `22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48`.
- Native runtime: llama.cpp b9840,
  `8c146a8366304c871efc26057cc90370ccf58dad`, bundled with Ollama 0.31.1.
- Hardware: Apple M2 Pro, 16 GiB unified memory, Metal GPU. Dedicated lab process,
  separate model files and loopback port; production Ollama and model storage unchanged.

[model-runtime.json](model-runtime.json) records two isolated process starts and
20 warm synthetic two-passage requests per process. Startup-to-ready is 463.207
and 478.617ms; first inference is 84.149 and 81.434ms. Warm median is 71.665/71.355ms,
p95 72.838/72.247ms. RSS after the small warm request is 1,230,784/1,230,848KiB
(about 1.17GiB); it is an observation, not a memory cap or GPU-memory allocation
measurement. These tiny smoke timings must not be substituted for the real
12-passage Trading timings above. No filesystem/page-cache flush was performed:
these are new-process starts with warm filesystem caches, not cold disk boots.
Both restarts preserve the positive-above-negative order and stop cleanly.

The positive/negative smoke scores are approximately 0.996112 and0.000029014;
they validate model discrimination on one synthetic pair, not calibrated confidence.
An earlier community GGUF/Ollama generation-logit prototype returned uniform
punctuation outputs and was rejected. The shipped path uses native /v1/rerank.

## Compatibility and verification

Supported direct source: merged PR #38, `342bccf`; schema migrations001–014.
The actual prior search module is loaded from that git revision and its SHA-256
is checked against both the stored artifact and git blob. All five candidate
runtime source hashes in the measurement artifact match final application files.
The existing production checkout remains0c8addd; previous features document its
additive upgrade chain. No production deployment, migration, restart or model
installation was performed by this feature.

[upgrade-reader.json](upgrade-reader.json) records an owned synthetic installation
with two user actors, two projects, two domains, five documents, a pin, checkpoint,
queued work and audit history. Actual previous-revision and candidate readers run
concurrently. Endpoint outage, retry and previous-code rollback preserve original
payloads and every row of all 17 public tables; owned-database cleanup is verified.
Knowledge writes use the audited gateway. No persisted migration is needed.

Full verification: final Python/Node counts and review disposition are recorded
in [the feature review](../../openspec/changes/local-neural-rerank/review.md).
Test coverage includes malformed/duplicate/nonfinite scores, incomplete/model-swapped
responses, privacy boundaries, redirects/proxies, cancellation across discovery and
response bodies, true concurrent in-flight requests, pressure fallback, fork reset,
source correction/expiry, both MCP roles and additive client/configuration modes.

## Selection policy and remaining limits

Only ordinary auto questions with at least three query terms, three documents,
and a top-two distinct-document RRF gap within 20 percent consider inference.
Exact selectors, strong symbols, explicit hybrid/lexical, legacy benchmarks,
oversized queries and rerank=off keep prior stages. Inference is bounded to 12
passages of 1200 characters, 512 query characters, two in-flight requests per client
process and a total 1500ms deadline. The runtime's global capacity across clients
is the operator's responsibility. Timeouts and invalid results retain old ordering;
an absent endpoint or unrelated advertised model is a quiet compatibility fallback.

This is a conservative bounded heuristic calibrated on development examples,
not a learned ambiguity classifier. Only the first 12 original candidates can be
promoted; candidates outside that prefix and evidence after passage truncation
can remain missed. ANN remains approximate. Local-runtime model identity is an
operator-verified alias: verify the pinned weights/smoke test before adoption.
The adapter does not install or start the optional runtime. Review and CI do not
authorize its production rollout. Existing dependency-security triage remains #37.

## Reproduce

Export the actual previous source and run the two independent verification tools
from the feature checkout, using its existing Python environment:

```sh
git show 342bccf6fce51213b7bac1560e41e7554b2e989c:agentic_rag/search.py > /tmp/before-neural-search.py
python -m scripts.measure_neural_rerank --before-search /tmp/before-neural-search.py \
  --cases /path/to/private/cases.json --project /Users/peter/Agents/Trading \
  --url http://127.0.0.1:PORT --output /tmp/neural-trading.json
python -m scripts.rehearse_neural_upgrade --before-search /tmp/before-neural-search.py \
  --url http://127.0.0.1:PORT --output /tmp/neural-upgrade.json
python -m pytest -q
node --test tests/test_opencode_plugin.mjs
```

The upgrade tool allocates and verifies cleanup of its own random synthetic
database; it accepts no production target. Follow [local model operation and
recovery](../../local-reranker.md) for the exact pinned download and runtime
commands. Keep private labels outside git and request explicit rollout authorization.
