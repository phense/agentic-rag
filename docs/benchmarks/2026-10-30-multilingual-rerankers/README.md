---
id: RAG062-MULTILINGUAL
title: Compare four local multilingual rerankers
type: reference
doc_id: standalone
readers: [repository-maintainer]
status: reviewed
version: 0.6.15 / schema027
depends_on: [issue62-reranker]
assets: [comparison.html, report.html]
last_reviewed: 2026-10-30
summary: Measured German/English quality, latency, memory and client outcomes; v3.5 fails the prescribed runtime bound.
---

# Compare four local multilingual rerankers

mMARCO is the strongest small Apache-2.0 candidate in this experiment for a single client: 41/48 correct first sources in each language, with a 6×600-character p95 of 1,093.8 ms. MiniLM L6 is faster (508.7 ms) and tolerates more parallel work, with 38/48 in each language. Both still make role, negation or numeric mistakes; neither is approved for production by this report.

Jina v2 leads German source ranking (46/48) but takes 3,843.2 ms at that same payload and misses seven of 96 actual client deadlines even on the shorter primary questions. Jina v3.5 reaches 44/48 in each language, takes a primary-query median of 11,729.7 ms, misses all 96 client deadlines, and fails the first long-text test. These CPU configurations do not meet the current interactive deadline. Jina's declared noncommercial weight licenses also need a separate commercial licensing decision.

This medium reference is for the maintainer choosing the optional reranker in [Issue #62](https://github.com/phense/agentic-rag/issues/62) / [PR #82](https://github.com/phense/agentic-rag/pull/82). The [rendered report](report.html), [interactive comparison](comparison.html), [complete summary](summary.json) and [independent review](verification/independent-review.txt) retain the evidence. The original 2,688-observation protocol failed: nine successful units and one failed v3.5 unit produced 2,338 actual observations; 350 v3.5 observations were never attempted. Completion of the other candidates does not change that failed status.

## Terms and measurement boundary

| Term | Meaning |
|---|---|
| Primary | First seeded candidate order for one query; 48 German and 48 English questions per model. |
| First source | Top-ranked passage is a required source. |
| Recall@3 / all sources@3 | Per-query fraction / complete set of required sources among the first three results. |
| MRR / nDCG@3 | Mean reciprocal rank of the first required source / normalized discounted relevance in the first three positions. |
| p50/p95/p99 | Descriptive percentiles, interpolated at `(n-1)*p`. |
| Ranked / fallback | Product accepted the ranking within its deadline / retained original source order. |
| Censored / unattempted | Request timed out without usable HTTP response / request was never sent. |
| Process-cold | New server process with operating-system caches retained. |
| RSS / cgroup | Server resident memory / jointly limited process tree, including charged temporary model copies. |
| INT8 / FP32 | Published eight-bit ONNX representation / 32-bit floating-point CPU representation. |

The frozen [protocol](PLAN.md) uses synthetic public passages, six candidates/query and 96 questions in 24 related families. Thirty-two prior diagnostic cases remain unchanged; 64 are newly authored controls. Gold labels never enter inference. Each language has 53 required-source occurrences because five questions require two sources. Recall@3 is averaged per question. The reverse candidate order supplies separate sensitivity checks, without doubling the primary denominator.

The shared host is Intel Xeon E5-2650, AVX without AVX2. Every isolated process tree receives four CPUs, affinity 0–3, 8 GiB and zero cgroup swap; no GPU, PostgreSQL or private corpus is used. The published AVX2-named ONNX artifacts execute through runtime-selected kernels. Three models use INT8 ONNX; v3.5 uses its official audited Transformers code loaded FP32 from BF16 weights. This compares those local configurations, not precision-equivalent or architecture-only performance.

The loopback lab bridge retains native scores and explicitly maps logits with sigmoid and cosine with `(cosine+1)/2`. MiniLM's upstream default activation is Identity. All observed native orderings and ties survive the mappings. Scores remain uncalibrated. The product's strict finite `[0,1]` guard is unchanged. Synthetic equal positive hit scores force route eligibility; this does not measure routing frequency in real retrieval.

## Source-ranking quality

| Configuration/language | First source | All sources@3 | Recall@3 | MRR | nDCG@3 |
| --- | --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE/de | 38/48 (79.2%) | 48/48 | 1.000 | 0.885 | 0.915 |
| MiniLM L6 EN/DE/en | 38/48 (79.2%) | 45/48 | 0.938 | 0.877 | 0.879 |
| mMARCO mMiniLMv2/de | 41/48 (85.4%) | 48/48 | 1.000 | 0.920 | 0.941 |
| mMARCO mMiniLMv2/en | 41/48 (85.4%) | 47/48 | 0.979 | 0.911 | 0.925 |
| Jina v2/de | 46/48 (95.8%) | 48/48 | 1.000 | 0.979 | 0.985 |
| Jina v2/en | 41/48 (85.4%) | 48/48 | 1.000 | 0.924 | 0.943 |
| Jina v3.5/de | 44/48 (91.7%) | 48/48 | 1.000 | 0.958 | 0.969 |
| Jina v3.5/en | 44/48 (91.7%) | 48/48 | 1.000 | 0.958 | 0.969 |

All 384 primary model/question responses are available. The [independent reconstruction](verification/audit-final-bounded-reconstruction.json) lists all 51 primary misses with queries, required/selected text and native scores. German Jina v2 misses include reversed expense-review roles and an exact decimal amount. mMARCO incorrectly promotes a denied archive permission in one control. Such mistakes remain material even when all necessary evidence reaches the top three.

| Configuration | Prior DE /16 | New DE /32 | Prior EN /16 | New EN /32 | DE query/EN source /16 | EN query/DE source /16 |
| --- | --- | --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 15 | 23 | 14 | 24 | 13 | 13 |
| mMARCO mMiniLMv2 | 13 | 28 | 12 | 29 | 13 | 11 |
| Jina v2 | 16 | 30 | 14 | 27 | 16 | 14 |
| Jina v3.5 | 15 | 29 | 15 | 29 | 15 | 12 |

Reversing candidate order changes no ONNX ranking. v3.5 changes the first source in 5/48 German and 6/48 English cases, and the full order in 40/48 each. Its reversed German all-sources@3 falls to 46/48; reversed English first-source rises to 46/48. The first seeded order remains primary. Paired wins/losses, per-family results and all reverse metrics are retained in the summary. Related synthetic families do not establish population accuracy, significance, stored-corpus retrieval recall or generated-answer accuracy.

## Execution time and actual client

Primary raw timing uses 96 varied short queries and their original passages. The separate performance grid pads each passage to approximately the stated character count. These distributions answer different questions.

| Configuration | Primary raw p50/p95 ms, n=96 | DE ranked/timeout/pressure | EN ranked/timeout/pressure |
| --- | --- | --- | --- |
| MiniLM L6 EN/DE | 152.3/250.6 | 48/0/0 | 48/0/0 |
| mMARCO mMiniLMv2 | 282.5/449.7 | 48/0/0 | 48/0/0 |
| Jina v2 | 998.9/1,478.8 | 46/2/0 | 43/5/0 |
| Jina v3.5 | 11,729.7/15,393.7 | 0/48/0 | 0/48/0 |

The actual unchanged focused adapter sends at most six passages of 600 characters and has a total 1.5-second deadline. No primary request was invalid. Jina v2 accepts 89/96 rankings: ranked-only first-source counts are 44/46 German and 36/43 English; all seven fallback first sources are wrong. v3.5 accepts none; its fallback first-source count of 4/48 per language describes original order only. All original hit objects are preserved.

Each performance cell has 15 requests per process across three fresh starts, n=45. The following p50/p95/p99 describe successful HTTP calls; censored counts are explicit.

| Configuration | Candidates × chars/passage | Success/censored | p50 ms | p95 ms | p99 ms |
| --- | --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 6x120 | 45/0 | 185.9 | 350.0 | 397.3 |
| MiniLM L6 EN/DE | 6x600 | 45/0 | 461.3 | 508.7 | 513.8 |
| MiniLM L6 EN/DE | 6x1200 | 45/0 | 875.9 | 1,392.6 | 1,531.2 |
| MiniLM L6 EN/DE | 12x600 | 45/0 | 901.4 | 1,359.4 | 1,709.6 |
| MiniLM L6 EN/DE | 12x1200 | 45/0 | 1,742.4 | 2,437.7 | 2,635.6 |
| mMARCO mMiniLMv2 | 6x120 | 45/0 | 346.2 | 579.6 | 627.4 |
| mMARCO mMiniLMv2 | 6x600 | 45/0 | 899.1 | 1,093.8 | 1,295.7 |
| mMARCO mMiniLMv2 | 6x1200 | 45/0 | 1,769.7 | 2,540.8 | 2,821.3 |
| mMARCO mMiniLMv2 | 12x600 | 45/0 | 1,848.4 | 2,659.4 | 2,898.4 |
| mMARCO mMiniLMv2 | 12x1200 | 45/0 | 3,515.5 | 4,434.4 | 4,711.0 |
| Jina v2 | 6x120 | 45/0 | 1,182.2 | 1,490.2 | 1,712.2 |
| Jina v2 | 6x600 | 45/0 | 3,231.0 | 3,843.2 | 4,462.0 |
| Jina v2 | 6x1200 | 45/0 | 6,125.2 | 7,576.3 | 8,947.2 |
| Jina v2 | 12x600 | 45/0 | 6,581.5 | 8,071.4 | 10,005.5 |
| Jina v2 | 12x1200 | 44/1 | 12,463.7 | 23,691.7 | 28,041.7 |

Jina v2's one censored 12×1200 request returned a client timeout at 30,088.1 ms; native work finished at 36,971.8 ms and drained. That cell therefore has 44 successful timings, not 45 uncensored inferences. Its all-attempt client p95 is 26,434.7 ms, including the deadline observation. v3.5 has no performance-grid observations; every cell is unavailable. Forty-five observations, especially p99, do not establish stable capacity.

| Configuration | Starts | Ready median/max ms | First request median/max ms | Server peak MiB | Cgroup peak MiB | CPU seconds total |
| --- | --- | --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 3 | 2,714.4/2,783.8 | 168.5/379.7 | 835.2 | 1012.4 | 1672.4 |
| mMARCO mMiniLMv2 | 3 | 3,323.3/4,403.2 | 321.5/568.6 | 697.9 | 853.8 | 3194.1 |
| Jina v2 | 3 | 3,627.4/4,330.8 | 2,040.9/2,241.5 | 1170.8 | 1520.5 | 10678.0 |
| Jina v3.5 | 1 | 22,887.9/22,887.9 | 20,226.6/20,226.6 | 3756.9 | 4481.7 | 16179.5 |

Ready time starts after copying the weights and measures server launch to health readiness. Cgroup counters include the charged model copy and cleanup. CPU totals sum different amounts of completed work, including the failed v3.5 work; they are not per-request efficiency comparisons. Values marked `[not set]` by retired systemd units remain unavailable; retained cgroup counters supply this table. ONNX preparation covers complete input preparation; v3.5's subtotal covers external pretruncation only, with upstream retokenization included in total handling.

## Load, formatting and long passages

Five bursts at each client count use the actual adapter in one Python process and padded 599-character passages. The existing client permits two in-flight calls; excess calls return pressure. Fast pressure replies do not measure inference throughput.

| Configuration | Clients | Requests | Ranked/timeout/pressure | Ranked-only p50/p95 ms |
| --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 1 | 5 | 5/0/0 | 478.5/483.7 |
| MiniLM L6 EN/DE | 2 | 10 | 10/0/0 | 1,063.6/1,226.4 |
| MiniLM L6 EN/DE | 4 | 20 | 8/2/10 | 1,083.6/1,380.3 |
| mMARCO mMiniLMv2 | 1 | 5 | 4/1/0 | 905.6/938.8 |
| mMARCO mMiniLMv2 | 2 | 10 | 0/10/0 | unavailable/unavailable |
| mMARCO mMiniLMv2 | 4 | 20 | 0/10/10 | unavailable/unavailable |
| Jina v2 | 1 | 5 | 0/5/0 | unavailable/unavailable |
| Jina v2 | 2 | 10 | 0/10/0 | unavailable/unavailable |
| Jina v2 | 4 | 20 | 0/10/10 | unavailable/unavailable |

mMARCO is therefore a single-client compromise, not a proven concurrent service at this deadline. L6 has more headroom but still has two timeouts in the four-client bursts. v3.5 load/bypass checks are unattempted; the other models each pass one exact-symbol bypass without inference. Complete batch makespan, drain and ranked-only timing distributions are retained.

| Configuration | Long first: beginning/middle/end /16 | Whitespace/ASCII/NFD first /8 |
| --- | --- | --- |
| MiniLM L6 EN/DE | 13/7/0 | 7/6/7 |
| mMARCO mMiniLMv2 | 12/8/0 | 7/6/7 |
| Jina v2 | 16/10/0 | 8/8/8 |

Long controls place evidence at the beginning, middle or end of approximately 6,000 characters/passage. ONNX limits the combined query/document pair to 512 tokens; end evidence is clipped. The 0/16 end results describe this input policy. v3.5 limits each document to 512 tokens before a joint prompt; its first attempt is censored and 47 remaining long controls are unattempted. No result proves full advertised context-window quality.

Formatting checks have eight German queries/variant. ASCII umlaut replacement and Unicode NFD each leave one query unchanged; whitespace changes all eight. ASCII changes the first source once for L6 and mMARCO, never for v2. Sixteen unsupported questions per completed model retain top-score distributions and top-two margins in the summary; they support no calibrated answerability threshold. v3.5 formatting and unsupported checks are unattempted.

## Three practical controls

These fixed prior questions illustrate source-order changes. Each row is one raw request plus one separate actual-adapter call, not a latency percentile. Input rank is the deliberately shuffled candidate order, not a real retriever baseline; no live retrieval gain is implied.

### access-negation-1-de

Wer hat eine ausdrücklich erteilte Zugangsfreigabe für das Rechnungsarchiv? Required: Nora darf auf das Rechnungsarchiv zugreifen. Ihr Zugang ist ausdrücklich freigegeben.

| Configuration | Input source rank | Raw source rank | Raw ms | Actual adapter |
| --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 2 | 2 | 314.9 | ranked |
| mMARCO mMiniLMv2 | 2 | 2 | 335.0 | ranked |
| Jina v2 | 2 | 1 | 1,075.4 | ranked |
| Jina v3.5 | 2 | 1 | 14,738.6 | timeout |

### amount-threshold-2-de

Welche Lieferantenrechnung liegt genau auf der Grenze von fünfhundert Euro? Required: Die Rechnung des Lieferanten Drossel beträgt genau 500,00 Euro und liegt damit auf der Grenze.

| Configuration | Input source rank | Raw source rank | Raw ms | Actual adapter |
| --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 4 | 1 | 201.0 | ranked |
| mMARCO mMiniLMv2 | 4 | 3 | 317.1 | ranked |
| Jina v2 | 4 | 1 | 1,176.0 | ranked |
| Jina v3.5 | 4 | 1 | 15,409.2 | timeout |

### subject-object-2-de

Wessen Reisekostenabrechnungen werden von Levin geprüft und freigegeben? Required: Levin prüft die Reisekostenabrechnungen von Nora und gibt sie anschließend frei.

| Configuration | Input source rank | Raw source rank | Raw ms | Actual adapter |
| --- | --- | --- | --- | --- |
| MiniLM L6 EN/DE | 4 | 1 | 166.2 | ranked |
| mMARCO mMiniLMv2 | 4 | 2 | 547.7 | ranked |
| Jina v2 | 4 | 1 | 1,074.5 | ranked |
| Jina v3.5 | 4 | 1 | 13,868.0 | timeout |

## Model identity, failures and reproduction

| Configuration | Weight bytes / runtime | Declared weight license |
|---|---|---|
| MiniLM L6 EN/DE | 107,494,476 / INT8 ONNX CPU | Apache-2.0 |
| mMARCO mMiniLMv2 | 118,620,016 / INT8 ONNX CPU | Apache-2.0 |
| Jina v2 | 279,577,152 / INT8 ONNX CPU | CC BY-NC 4.0 |
| Jina v3.5 | 1,193,708,152 BF16 file / official Transformers FP32 CPU | CC BY-NC 4.0 |

The [model manifest](models.json) seals all 29 model/tokenizer/configuration files and immutable repository revisions. [Dependencies](requirements-frozen.txt) describe the isolated model environment, separate from the product environment. Model cards: [L6](https://huggingface.co/cross-encoder/msmarco-MiniLM-L6-en-de-v1), [mMARCO](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1), [v2](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual), [v3.5](https://huggingface.co/jinaai/jina-reranker-v3.5).

The [corpus review](four-model-corpus-review.txt) and [helper review](four-model-harness-review.txt) preceded inference. Startup attempts a/b/c produced no inference, and the first v3.5 weight-copy attempt exhausted the tmpfs user quota. Their exact failures remain in `rejected-a/` through `rejected-d/`. SHA-identical owned old weight copies were deduplicated while retaining paths and contents. A reproduced drain-before-save defect was fixed after two failing regressions; five focused tests pass. The [executed sources](executed-sources/) preserve old/new helper identities; successful timing boundaries stayed unchanged. The real failed drain now retains its request row.

The [v3.5 runtime failure](aborted-e/jina-v3.5-r0/exit.json) occurred after 4,208.788 seconds: first long request timed out at 30,042.7 ms and remained active throughout another 120 seconds. Its process was stopped as prescribed, with no OOM. Its 322 rows contain all primary/reverse, adapter and cross-language checks, one cold request and one failed long request. The 350 unattempted rows are 47 long, 24 formatting, 16 unsupported, 225 performance, 35 load, one bypass and two cold requests. No timeout increase, v3.5 restart or post-result model tuning occurred. Retained Transformers warnings were checked: the Mistral regex warning is a false detection on this Qwen3 config and applies no regex change; `torch_dtype` deprecation preserves FP32.

The [terminal artifact](evaluation/matrix-exit.json) records nine successful units plus the failed unit. All ten measured children stopped, temporary copies were removed and port 8782 refused connections. The [independent review](verification/independent-review.txt) found no open Critical/High/Medium or actionable Low code/evidence finding. Model infeasibility remains a result. Original product sources match the historical 343-file suite and 159-file diagnostic manifests. The earlier 1,735-pass full suite is historical same-source evidence; this supplement has its own model measurements and focused checks.

Reconstruct the summary without model dependencies from this report directory:

```sh
python3 analyze_bounded.py evaluation --output /path/to/new-summary.json
```

The output must equal `summary.json`: 2,338 actual rows, 350 unattempted, explicit original-protocol failure. Run `PYTHONPATH=. .venv/bin/python docs/benchmarks/2026-10-30-multilingual-rerankers/check_failure_persistence.py` from the repository root for the five model-free regressions. Per-unit command arrays, actual exits, envelopes and timestamps are in the terminal artifact. Rerunning inference requires the sealed weight files, isolated model environment, Linux user systemd and four-CPU/eight-GiB envelope; the prescribed v3.5 stop remains expected evidence. The separate embedding comparison is tracked in [Issue #83](https://github.com/phense/agentic-rag/issues/83).

No model service or production configuration was activated. PR #82 remains subject to maintainer merge approval.
