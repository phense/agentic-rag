---
title: German suitability diagnostic for the pinned Jina tiny reranker
type: reference
doc_id: standalone
readers: [maintainer, operator]
version: 0.6.15
status: measured
last_edited: 2026-10-30
summary: Paired public German/English semantic probes, separate from the original held-out selection.
---

# German suitability of the pinned Jina tiny reranker

The pinned Jina tiny processes German inputs, but this diagnostic rejects a
blanket adoption for our German RAG use: six of sixteen first-ranked sources
miss the question, including permission/negation and subject/object cases.
All sixteen German adapter calls rank successfully; speed and parseability
do not establish semantic correctness.

Writing depth: medium standalone reference. This diagnostic answers the
maintainer's request to check German before adopting the measured English-model
challenger. It supplements [Issue62 measurements](../2026-10-30-measured-reranker/README.md)
and does not change the original held-out corpus, candidate selection or runtime.

## Upstream scope and concrete artifact

The [official Jina model card](https://huggingface.co/jinaai/jina-reranker-v1-tiny-en)
places tiny v1 in the English reranker family. The upstream metadata tags it
`en`; the card does not provide a German-specific quality guarantee. Its published
parameter count is 33 million. These facts do not imply that German input is
technically rejected. The relevant question is whether ranking preserves German
meaning reliably enough for our use.

This tests the same pinned local Q8 GGUF and native runtime as the original lab,
not every Jina model, latest full-precision weights or hosted APIs. Model SHA256:
`0defc1f8a1f4dd22183124a2a25a97765603e5a9e42258046c9b2c8a26d1f553`.
Runtime SHA256:
`dbfeea380cdc1de9bbfe32399befbcd8381a3c5ac83e573d79d0fa41bdc40037`.
Live upstream metadata/revisions are recorded in [metadata](upstream-metadata.json).
The [Qwen card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) explicitly describes
multilingual support; no new complete Qwen quality comparison is claimed here.

## Frozen questions and decision rule

[Corpus](corpus.json): 16 German questions and 16 faithful English controls over
eight authored topic families: permission/negation, compounds/inflection,
amount thresholds, approved dates, recovery paraphrases, subject/object roles,
two-document requirements and domain ambiguity. Each language has 17 expected
source occurrences because one question needs two passages. Every question has
six short candidate passages, at most 138 characters each, and all pass the
existing neural-route eligibility check. No private content is used.

Each paired question uses the same seeded candidate permutation in both
languages. Its reverse is the second permutation. The first permutation alone
supplies primary quality denominators; the reverse measures position sensitivity.
The 16 questions are related within eight families. Repeated permutations do not
make 32 independent questions, and no population confidence interval is claimed.

The preregistered rule rejects a blanket German recommendation after two or more
German first-permutation top-one misses, any such miss in the permission/negation
or subject/object families, or a German top-one result more than ten percentage
points below its paired English result. Passing this small authored diagnostic
would only support a larger representative local acceptance trial.

A premeasurement independent review found one ambiguous multi-source distractor
that itself named both required documents. That clause was removed in both
languages before any inference. No labels or questions changed after scoring.

## Measurement boundary

The raw semantic probe uses a 30-second **per-operation HTTP timeout** solely to
observe model ranking. It is not a strict 30-second wall deadline or a production
configuration. A separate probe in both languages calls the unchanged actual focused adapter
with its total 1.5-second deadline, six-passage/600-character ceiling and original
object-preserving fallback. These adapter calls immediately follow raw scoring
for the same case: they are warm repeated-case probes on short texts, not evidence
for cold starts, representative 600-character passages or production capacity.

Only candidate ordering is measured. There is no PostgreSQL, retrieval recall
from a corpus, embedding call, generated answer, citation/source-eligibility test
or deployment change in this supplement. Labels enter only the scorer. Top-one
means the first ranked passage is an annotated required source. Recall@3 and
nDCG@3 use those binary source identities, not a probability that an answer is true.

The helper copies the pinned model inside an owned combined four-CPU/eight-GiB,
zero-swap cgroup and verifies actual affinity, runtime/libraries and source hashes.
The shared host and OS caches remain outside a dedicated-machine guarantee.
Model quality misses are retained as observations rather than dropped.

## Retained incomplete Qwen attempt

The original two-model plan is retained in [rejected-a](rejected-a/exit.json),
including the exact old helper, seal, partial observations and cleanup. A Qwen
raw call took 28.250 seconds and a later one hit ReadTimeout at 30.033 seconds.
The owned main process was interrupted to avoid a lengthy incomplete comparison.
Its helper exit is **1**, all processes stopped and no cleanup error remained.
Systemd labels SIGINT as success; that does not turn the partial experiment into
a passing result. No Qwen or partial tiny quality denominator comes from this run.

The unchanged corpus and decision rule were subsequently used in Tiny-only
attempts b/c. All 80 observations were produced, but their helper exit is 1:
the diagnostic initially applied the production zero-to-one guard to raw
semantic scores. Captured native responses demonstrate finite negative values
in six English cases. These exact helpers, observations, exits and raw replies
remain in [attempt b](rejected-b/exit.json) and [attempt c](rejected-c/exit.json).
No failed attempt is credited as an accepted complete experiment.

The accepted helper ranks any complete set of finite native scalar scores for
semantic diagnosis, preserving every score without normalization. The actual
product adapter still enforces its original zero-to-one guard. Explicit
`production_score_range_compatible` flags and both-language adapter probes make
the distinction auditable. No fixture, relevance label, language question or
German decision criterion changed.

## Accepted results

The [complete run](evaluation/results.json), [summary](evaluation/summary.json),
[raw observation stream](evaluation/observations.jsonl) and [exit](evaluation/exit.json)
contain **96 observations**: 64 raw (32 questions × two permutations) and 32
actual adapter probes (16 questions per language). Source corpus SHA256:
`2f018b5b7b4bd03a128942fa7aadaf1139f55d41702dc0fd95f4b06e3331aa84`.
The [pre-inference seal](evaluation/seal.json) binds corpus, helper, runtime and
159 original engine/wrapper/metadata hashes. The measured source installation
is PR82 head `8e823f8238f14554d9af1484185f20961518efe6`; the supplemental
helper has its own sealed hash. No product code changed.

Primary quality uses only the first permutation, 16 questions and 17 expected
source occurrences per language:

| Raw semantic ranking | German | Paired English |
|---|---|---|
| Required source at rank one | 10/16 (62.5%) | 12/16 (75.0%) |
| Every required source in top three | 15/16 | 16/16 |
| Macro source recall@3 | 0.9375 | 1.0000 |
| nDCG@3 | 0.805799 | 0.907732 |
| Reverse-permutation rank-one matches | 10/16 | 12/16 |
| Changed first source after reversal | 0/16 | 0/16 |

The paired gap is 12.5 percentage points in this authored sample. Eight related
families do not establish population language accuracy or a general causal
German-vs-English difference. The primary German failures themselves reject the
preregistered adoption rule: six misses, two in critical question families,
and the observed paired gap all exceed their declared bounds.

All six German rank-one misses remain visible:

| Case | First selected source | Required source |
|---|---|---|
| `access-negation-2-de` | Nora's pending photo-archive request | Levin's explicitly denied invoice-archive access |
| `amount-threshold-2-de` | Invoice for 490.10 euros | Invoice for exactly 500.00 euros |
| `temporal-approval-2-de` | Approved November maintenance on Tuesday | Approval exclusively for October on Monday |
| `subject-object-2-de` | Mara reviews Levin's expenses | Levin reviews Nora's expenses |
| `multi-condition-2-de` | Written approval for key handover | Viewing appointment available to the incoming tenant |
| `domain-ambiguity-1-de` | Password recovery through identity checking | Database restoration log consistency check |

The database-restoration case misses its required source in the first three
positions too (rank five). The English first-source misses are
`temporal-approval-1-en`, `paraphrase-recovery-2-en`, `subject-object-1-en` and
`multi-condition-2-en`. Exact texts, orders and every native score are retained.

## Actual adapter compatibility and measured resources

German: all 16 actual adapter calls return `ranked`, with 10/16 matching first
sources and 15/16 complete top-three sets. Warm repeated-case p50/p95 is
354.482/853.927 ms. Those short-text timings do not replace the original
representative-budget latency evidence.

English: ten adapter calls return `ranked`; six return `invalid` and the caller
retains original order. Their native scores include negatives, outside the
product adapter's required range. Actual first-source matches are 11/16 and
complete top-three sets 13/16. These are separately reported fallback outcomes,
not successful production reranking. The generic adoption of this pinned tiny/
native-runtime combination is therefore **not fully contract-compatible**.
Resolving that boundary requires separately reviewed runtime/adapter work and
fresh representative acceptance; no production guard was weakened here.

The accepted unit exits 0 after 37.656 seconds, using 123.264 CPU seconds,
131.2 MiB peak memory and zero swap. Actual evaluator/model affinity is 0–3
with four-CPU quota, eight-GiB limit and no OOM/max events.
[External cleanup](evaluation/external-cleanup.json) confirms inactive unit,
absent cgroup and refused owned ports. All owned processes stopped; copied model
files remain. This is a shared-host diagnostic, not capacity evidence.

## Reproduction and review

Use the same inspected runtime/model paths and combined resource limits from
[PB062-OPS](../../local-reranker.md). Run `evaluate.py` with `--models tiny`,
`--corpus` pointing to this corpus and new `--output`/`--work-dir` paths; other
arguments match the original resource helper. Supply the pinned `--qwen` path
for CLI compatibility; it is neither copied nor started with `--models tiny`.
Require exit 0 and external cleanup, then run
`python analyze.py /absolute/path/to/output` to reconstruct the summary.
The finite-only raw-score rule is confined to this diagnostic.

Independent [design](german-design-review.txt), [scope](german-scope-review.txt)
and [final evidence reviews](german-evidence-review.txt) passed with no open
C/H/M or actionable Low finding in the diagnostic. The final reviewer independently
reconstructed every metric and original response, confirmed both adapter outcomes
and accepted cleanup. Blanket model adoption remains blocked by the exposed
quality and integration limits. Original whole-suite
evidence remains unchanged: all 343 frozen test files and 159 measured files
match their earlier passing snapshot. No PostgreSQL or private corpus was used.

The recommendation is to keep Jina tiny as an explicitly experimental local
option and withhold a blanket German production recommendation. A future
adoption needs a contract-compatible runtime and representative German
acceptance, including the exposed negation, roles, amount and temporal cases.
