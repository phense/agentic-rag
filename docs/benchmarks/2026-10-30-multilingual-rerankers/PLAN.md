# Four-model local reranker comparison

This protocol is fixed before candidate inference. The primary reader is the
maintainer evaluating optional local model adoption under Issue #62. This is
a measurement supplement to open PR #82, not production deployment or a new
default. The report is one medium standalone reference document.

## Candidates and execution

| Candidate | Pinned revision | Runtime / representation |
|---|---|---|
| cross-encoder/msmarco-MiniLM-L6-en-de-v1 | 9eb610d90d409cfefb7422e13debd405f8465af6 | ONNX Runtime CPU, published unsigned INT8 AVX2 graph; runtime selects kernels on this older AVX-only CPU |
| cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 | 1427fd652930e4ba29e8149678df786c240d8825 | Same ONNX runtime and unsigned INT8 representation |
| jinaai/jina-reranker-v2-base-multilingual | 9cfeff2df7d40d1b78e75e5e9cebec92a99813c9 | ONNX Runtime CPU, published INT8 graph |
| jinaai/jina-reranker-v3.5 | e8a93f33f0b22108f8c2364f8484ce3422552fbc | Official audited modeling.py, Transformers 4.57.3 / CPU PyTorch, loaded FP32 from BF16 weights |

Model artifacts and tokenizer files must match the sealed SHA-256 manifest.
No unpinned remote model code is executed. v3.5 has a distinct listwise
architecture and execution path; this compares deployable local configurations,
not architecture-only speed or precision-equivalent model quality. Its official
GGUF route currently requires a llama.cpp fork and external projector. This run
uses the official Transformers route rather than altering installed llama.cpp.

Each process tree has 4 effective CPUs, affinity 0–3, 8 GiB memory, zero cgroup
swap, no GPU. Source weights remain retained; fresh model copies and inference
are charged inside each measured cgroup. Existing private services and databases
are not used. Host contention, CPU model and cgroup counters are recorded.

The first three classifiers emit raw logits. The lab HTTP bridge explicitly
applies a fixed sigmoid; MiniLM's upstream default activation is Identity. v3.5
emits native cosine scores; the bridge applies the fixed `(cosine+1)/2` mapping.
All native scores are retained. These transport mappings are separate from
production configuration, preserve order apart from numerical ties, and do not
relax the unchanged product's strict finite [0,1] checks. Scores are not shared
confidence probabilities. Check native versus transformed ordering in analysis.

## Quality denominators

- Primary: 96 authored questions, 48 DE and 48 EN, in 24 related families.
  Preserve 32 prior diagnostic cases byte-for-byte at the case-field level;
  report them separately from 64 new questions. Every question has six fixed
  candidates and one or two required source IDs. Primary metrics use only the
  first seeded permutation; reversing the same list tests position sensitivity.
- Metrics: correct first source, macro Recall@3, all-required-source coverage@3,
  MRR, nDCG@3, per-language, per-family and prior/new splits. Report all misses
  and paired model wins/losses. Families are related synthetic controls, not
  independent population samples; no population-accuracy or significance claim.
- Cross-language: 32 prior questions with the paired other-language passages,
  separate from primary monolingual evaluation.
- Long context: the first question of each prior family in each language,
  16 questions × three evidence positions = 48 observations per model.
  Every passage is padded to approximately 6,000 characters with the fixed
  neutral text in benchmark.py. Evidence starts at the beginning, middle or end.
  ONNX truncates each query/document pair to 512 tokens. v3.5 pre-truncates each
  document to 512 tokens, then uses its upstream joint prompt. The exact token
  budgets differ with architecture; this is a bounded input policy, not proof
  of each model's full advertised context capability.
- Robustness: eight prior German questions × whitespace, ASCII umlaut and
  Unicode NFD variants = 24 observations. Report per-variant accuracy and
  changed rankings; some transformations may be no-ops.
- Unsupported requests: eight DE and eight EN unrelated questions against the
  same language's access-control candidate set. Retain top-score distributions
  and margins; do not select a rejection threshold after seeing results or
  claim the reranker alone establishes answerability.

The gold-label/translation review must finish before inference. Additional
cases, queries, padding rules and performance payloads are frozen in the corpus,
generator and benchmark source. Labels never enter the model request.

## Performance and product-contract checks

- Three fresh process starts per model. Rotate order by round: L6/mMARCO/v2/v3.5,
  then mMARCO/v2/v3.5/L6, then v2/v3.5/L6/mMARCO. OS caches are not flushed;
  label starts process-cold. Record model ready time and first request separately.
- Five fixed payload cells: 6 candidates at about 120/600/1200 characters and
  12 candidates at about 600/1200 characters. Fifteen varied requests per cell
  per process = 45 observations/cell/model. Record complete HTTP p50/p95/p99,
  server request-handling time (including preparation, inference, any service
  wait and response write), token preparation subtotals, CPU and peak memory.
  v3.5 reports only its external pre-truncation subtotal; its upstream internal
  retokenization is included in total request handling, so preparation times
  must not be compared directly with complete ONNX input preparation. Performance
  payloads are synthetic load controls, not extra quality observations.
- Actual unchanged `neural_rerank.order` focused policy and its 1.5-second total
  deadline on all 96 primary questions. Preserve original hit objects. Report
  ranked/timeout/invalid/pressure separately, with fallback quality; never
  credit a timeout's original order as successful neural ranking. Drain actual
  in-flight inference after client timeouts before the next serial request.
- Five bursts at 1, 2 and 4 clients using the actual product client in one
  process. Measure response times, makespan, guard pressure, timeout and native
  drain. The lab service allows at most two active calls and rejects excess;
  this is a declared laboratory capacity policy, not installed service capacity.
  v3.5 serializes its complete model/tokenizer call because its upstream fast
  tokenizer mutates padding/truncation state; the second accepted request waits
  inside the bridge and inside the client's deadline. ONNX encoding does not
  mutate shared tokenizer settings after startup.
- Exact-symbol request must bypass inference. No retrieval/database, source
  authorization, citation rendering, answer generation or cross-host benchmark
  is included in this source-ranking experiment.

Raw diagnostic HTTP calls have a 30-second per-operation timeout, followed by
at most 120 seconds of native drain. Stop the owned process on an undrained
call and retain the incomplete run as failed. A completed protocol may contain
30-second censored observations: report their timeout count, unavailable quality
metrics and successful-call denominator explicitly. Never call fallback order
semantic quality, or successful-call latency an uncensored model p95. Product
timeouts stay at 1.5s.
No timeout increase, retuned gold labels, model-specific performance tuning or
best-of-many run selection is permitted. Retain every rejected attempt and
explain any helper correction before repeating affected measurements.

## Recommendation and delivery

Rank candidates on demonstrated DE/EN quality, critical semantic mistakes,
deadline compatibility, memory, performance tails, integration work and license.
No automatic winner: a faster model with role/negation mistakes may remain
unsuitable. Jina v2/v3.5 weight licenses are CC BY-NC; commercial adoption is a
separate requirement. Apache-2.0 MiniLM models remain candidates, not preapproved
production choices. Retain original evidence and product source hashes, actual
exit artifacts, resource counters and independent evidence review. Fix evidenced
C/H/M defects in the measurement/report before PR handoff; deferred Low issues
belong in #75. PR #82 stays unmerged until a new maintainer approval.
