---
title: Measured local reranker configurations
type: reference
doc_id: standalone
readers: [maintainer, operator]
version: 0.6.15
status: measured
last_edited: 2026-10-30
summary: Sealed public EN/DE comparison of local Qwen budgets and Jina tiny under a combined 4 CPU / 8 GiB envelope.
---

# Measured local reranker configurations

The development-selected local Jina tiny configuration improves source coverage
and finishes within the inference budget in this public fixture. Qwen exceeds
the 1500 ms inference deadline in every eligible held-out observation; the smaller
Qwen passage budget alone does not help. Defaults remain unchanged. Explicit
operator selection still needs representative local acceptance through
[PB062-OPS](../../local-reranker.md).

Writing depth: medium standalone reference for maintainers/operators. These are
source-ranking measurements on invented sources, with disabled embeddings and
three held-out families. They do not measure general answer accuracy, calibrated
truth probabilities, German model training or production/fleet capacity.

## Revisions, data and selection

- Before: exact 0.6.14 `neural_rerank.py` from
  `7a61955446119df522a34967273d8dacae56108b` is loaded and executed.
- Measured source: `4ac82cdf2aca20b54d7071eb59ac0437cfdcd550`, 0.6.15/schema027.
  All three policies use the same current authorized lexical candidates; this is
  a before/after ordering comparison, not a full historical-engine speed test.
- [Corpus-v2](../../../agentic_rag/benchmark/corpus-reranker-v2.json): 70 sources,
 43 development/27 held-out; 23/21 unique requests, 3 families per split.
  Source/corpus hashes and complete definitions are in the
  [exclusive candidate seal](evaluation/candidate.json), canonical `seal_sha256`
  `fb917330a54737f72ec168300644a3e75a8925bb4ab8e47d6b5676e6e47a12fa`.
- Six queries are attributed to actual misses in the public Issue35 development
  report at 5b39069, whose exact SHA256 is in the corpus. Fresh baseline execution
  reproduces 4/6; two independent-domain cases are already fixed. All six outcomes
  are retained. The four current-status misses remain with Jina: an ordering
  callback cannot recover a source absent from its eligible candidate list.
- New controls use separate EN/DE operational keyword questions and bilingual
  source text for delivery, recovery, exact identifiers, accepted replacements
  and unsupported requests. Related translations/source identities share one
  split. Templates are shared across distinct subjects and limit generalization.
- Development permits selection only with no per-case recall/nDCG regression,
  no additional failed inference observations, an actual successful rank and
  at least 10% lower median paired search latency. It chose `tiny-focused-v1`
  before held-out calls. Development macro recall is 0.3611→0.5556; nDCG 0.3469→0.5145.
  Held-out results never retune selection. Labels enter only the scorer.

## Source metrics and failures

Each unique request contributes one first observation to quality. Repetitions
contribute timing and all error counts. Recall@3 is the fraction of expected
source IDs retrieved; precision@3 divides correct distinct IDs by actual returned
hits. nDCG@3 discounts binary fixture relevance by position, with the ideal based
on up to three expected sources. Duplicate hits cannot earn repeated credit.
The table is the mean over 18 answerable requests, not over repeated timings.
There are 24 expected source occurrences across these requests.

| Configuration | Macro recall@3 | Macro precision@3 | nDCG@3 | Ranked/timeout observations |
|---|---|---|---|---|
| Qwen legacy 12×1200 | 0.3333 | 0.2500 | 0.2718 | 0/36 |
| Qwen focused 6×600 | 0.3333 | 0.2500 | 0.2718 | 0/36 |
| Jina tiny focused 6×600 | 0.6944 | 0.4352 | 0.5989 | 36/0 |

Qwen retrieves 6/24 expected source occurrences; Jina 16/24. Every policy has 27
bypass observations. All 27 held-out sources indexed; all 3 unsupported requests
return empty, with zero false-empty answerable requests. This measures retrieval
emptiness, not a language-model answerer's abstention. All 63 observations per
policy have zero query/trial errors and original citation parity. A retained
inference timeout is a successful deterministic-fallback observation, counted
above, rather than a discarded query.

EN answerable requests: 12; macro recall 0.5000→0.5417. DE answerable requests: 6;
macro recall 0.0000→1.0000 on these short authored controls. The English-trained
model's DE result cannot establish general German capability. Jina still misses
one or more required sources in all six English delivery/multi-source cases:
`test-spruce-delivery-en`, `test-spruce-multi-en`, `test-amber-delivery-en`,
`test-amber-multi-en`, `test-falcon-delivery-en`, `test-falcon-multi-en`.
The amber multi-source case improves only to 1/2; spruce/falcon remain 0/2.
All raw rows, misses and outputs are in [held-out results](evaluation/heldout-results.json).
Development also retains 8 answerable misses and 4 unsupported requests with
nonempty irrelevant retrieval; no improved general abstention claim is made.
Three independent held-out families are too few for a credible family confidence
interval, which is explicitly unavailable. No query-based interval substitutes
for independent-family uncertainty.

## Search latency and throughput

Held-out timings include ordinary scoped search and 1500 ms bounded inference,
with contextual retrieval off and embedding origin disabled. Each policy has 21
first observations on the shared phase connection and 42 warm repeats, 63 total. First observations
retain warm model/OS pages; model-process startup is recorded separately below.
Numbers are milliseconds, nearest-rank p95. Every sample and native drain remains
in the raw JSON, including all Qwen timeouts.

| Configuration | First p50 | First p95 | Warm p50 | Warm p95 | All p50 | All p95 | Serial q/s including drain |
|---|---|---|---|---|---|---|---|
| Qwen legacy 12×1200 | 1553.424 | 1591.813 | 1551.606 | 1559.193 | 1551.835 | 1585.791 | 0.276 |
| Qwen focused 6×600 | 1552.662 | 1579.688 | 1552.602 | 1587.747 | 1552.658 | 1586.630 | 0.269 |
| Jina tiny focused 6×600 | 406.236 | 450.015 | 411.068 | 473.436 | 409.577 | 470.492 | 3.460 |

The last column divides 63 by the sum of that policy's search and subsequent
verified native-idle drain. It is attributed serial occupancy in this paired
experiment, not sustained multi-client service capacity. Summing client latency
alone would hide ongoing work after cancellation. Actual mixed-policy held-out
wall time is 489.089 s for 189 calls,
0.386 calls/s, including source setup,
reads, drains and owned-database removal. Drain totals are
197.740s in development and
349.314s held-out. Native `/slots` must prove
idle before the next policy; busy endpoint read timeouts retry within 30 seconds.
The Python deadline limits discovery/scoring waiting, not total SQL/search time
or daemon execution. It has not been raised to make Qwen pass.

## Three practical before/after cases

Each row is one unique held-out request with three timing observations per
policy. Values show expected sources returned in the three-hit context, then
median complete-search latency. Before is Qwen legacy; after is the sealed Jina
focused configuration. Full source IDs, citations and all three samples are in
[the raw record](evaluation/results.json).

| Case | Before | After |
|---|---|---|
| DE receipt verification: `test-spruce-delivery-de` | 0/1; 1553.424ms | 1/1; 436.447ms |
| DE delivery + recovery: `test-spruce-multi-de` | 0/2; 1555.190ms | 2/2; 449.331ms |
| Exact restore identifier: `test-spruce-identifier` | 1/1; 12.107ms | 1/1; 11.718ms |

The receipt source reaches position 3 in the first example (nDCG 0→0.5); both
sources reach positions 1–2 in the second (nDCG 0→1). Exact identifiers bypass
inference in both versions; the small timing difference is not a speedup claim.
The unchanged 0/2 English spruce multi-source result is also retained:
1555.907→416.063ms median. Faster execution does not itself establish correctness.

## Reference envelope, runtime and recovery

Linux x86_64, Python 3.13.13, PostgreSQL 17.10/pgvector 0.8.4. The actual shared host
has 8 CPUs and 15,754,080 KiB RAM. One systemd user cgroup enforces 4 CPU quota,
8 GiB memory and zero swap for evaluator, native models, PG and children together.
The user controller does not delegate cpuset; actual evaluator/PG/model affinity
is verified 0–3 through `CPUAffinity=0-3`. Model pages are newly copied inside the
limited cgroup. This is an effective reference service envelope, not a dedicated
4 CPU / 8 GiB VM or a competing-client load test.

Runtime: `version:1(cb295bf59)`, launcher SHA256
`dbfeea380cdc1de9bbfe32399befbcd8381a3c5ac83e573d79d0fa41bdc40037`. All native library hashes,
model weights, membership and child affinity are retained in
[the runtime manifest](evaluation/runtime-manifest.json).
Qwen Q8: 639,153,184 bytes, SHA256 22c9979c…3429a48. Jina tiny Q8: 36,676,960 bytes,
SHA256 0defc1f8…d1f553. Full hashes/revisions and primary model links are in the
[design](../../openspec/changes/archive/2026-10-30-measured-reranker/design.md) and operator procedure.

| Model-process measurement | Qwen | Jina tiny |
|---|---|---|
| New process ready, ms (one) | 3785.762 | 3522.515 |
| First synthetic discrimination request, ms (one) | 7779.712 | 84.743 |
| Warm discrimination request1/2, ms | 7187.177/8209.515 | 75.877/75.978 |

The primary paired run has n=1 start per model, so it does not supply cold-process quantiles;
the two warm smoke samples are functional checks, not the 21/42 query distribution.
The separate smoke uses a 30-second measurement deadline; production inference
remains 1.5 seconds. The complete unit ran 819.502 s and consumed 3097.934 CPU seconds,
peak 1,633,099,776 bytes (1.521 GiB),
zero swap and zero OOM/kill/max events. CPU throttling: 2713 periods,
3.664097 aggregate throttled seconds. The JSON also retains Python-only CPU/RSS;
those figures exclude native processes, whereas the cgroup peak/CPU includes them.

Both phases verify every public canonical table before/after read-only queries,
then verify marker-owned database cleanup. Code/config recovery separately uses
actual 0.6.14local and authenticated ASGI server engines on a populated store;
[verification](../../verification/issue62-reranker.md). The lab
[exit record](evaluation/exit.json) is0, cleanup errors/remaining members empty,
all owned processes stopped. [External inspection](evaluation/external-cleanup.json) confirms the collected unit
inactive and its cgroup absent. Retained PG/model files remain owned test artifacts.
Production deployment, private source inference, external TLS and server restart
are separate acceptance; no model or default was automatically adopted.

## Supplemental process-cold quantiles

A separate, fixed-payload experiment starts three fresh processes per model,
then makes one first and two warm scoring requests per process. The executable,
weights and 4 CPU / 8 GiB zero-swap limits match the main run. It has no database,
held-out labels, policy tuning or candidate selection. Filesystem/OS caches
remain warm and the shared host runs separate verification tests during this
supplement. These are model-process functional timings, not cold full-search
latency. With n=3 cold starts, nearest-rank p95 is simply the maximum; n=6 warm
requests also gives a small-sample maximum. No population confidence is implied.

| Measurement | n/model | Qwen p50/p95 ms | Jina tiny p50/p95 ms |
|---|---|---|---|
| Process start → ready | 3 | 4189.127/5102.599 | 2911.241/4385.463 |
| First scoring request after ready | 3 | 7886.408/8087.013 | 76.246/103.476 |
| Start through first scoring result | 3 | 12276.140/12507.830 | 3014.717/4461.709 |
| Repeated scoring request | 6 | 6917.549/8220.312 | 77.235/96.670 |

The [raw record](process-cold/results.json) contains all six fresh-start observations,
18 requests, native peak RSS, child affinity, library/weight hashes and the
[helper](measure_process_cold.py) SHA256. [Exit0](process-cold/exit.json) and
[external cleanup](process-cold/external-cleanup.json) prove owned processes
stopped and the collected cgroup absent. This supplement ran 107.259 s, 307.529 CPU
seconds and about 1.2 GiB peak, zero swap. Each HTTP smoke allows 30 s solely for
measurement; application inference remains 1.5 s.

Reproduce under the same systemd limits with `measure_process_cold.py` instead of
`scripts/rehearse_reranker.py`, the same `--runtime`, `--qwen`, `--tiny` arguments,
and new `--output`/`--work-dir` paths. Omit `--repeats`; this helper fixes three
starts and two warm repeats. Ports 8770/8771 must be unused. Require exit 0 and no
remaining cgroup members before interpreting the separate cold distribution.

## Retained invalid and preflight attempts

- Initial Qwen functional probe with a 3 s measurement timeout failed. A separate
 30 s probe succeeded with roughly 3.94–4.10 s warm requests; [raw preflight](probes/qwen.json).
  Jina's separate preflight also passed: [raw data](probes/tiny.json). These are
  different standalone/shared-host conditions and are not the paired results.
- Attempt a aborted before PG/model startup because cpuset was not delegated.
  [Retained journal](rejected-a-journal.txt); actual affinity/quota/memory proof
  replaced the incorrect filesystem assumption.
- Attempt b at b16ee74 is [invalid, exit 1](rejected-b/exit.json):39/40 development
  and 15/18 held-out sources indexed, incorrect replacement fixture, nonexercising
  lexical questions and busy `/slots` read timeouts. All raw
  [outputs](rejected-b/results.json) remain. Its quality scores are invalid.
  Cleanup stopped the full owned cgroup; peak 1,643,061,248 bytes, no OOM.
- Rejected corpus-v1 is preserved byte-identically in
  [the rejected fixture](../../../agentic_rag/benchmark/corpus-reranker-rejected-v1.json)
  and b16ee74. Active v2 validates routes on dev-orbit only, removes duplicated
  temporal request contracts, and uses fresh spruce/amber/falcon test families
  instead of the already observed meadow/cobalt/harbor. No accepted test result
  was used for candidate selection or retroactive parameter tuning.

Reproduce with the exact wrapper/resource command in PB062-OPS, using new owned
paths and the pinned executable/weights. Preserve failed runs and their exit
artifacts. Full suite, independent publication review and release consistency
are recorded separately in the verification report; this measured record alone
does not waive those gates.
