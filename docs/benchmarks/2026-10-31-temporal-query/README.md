# Temporal search measurement (RAG-064)

Feature off versus on over one frozen synthetic corpus, revision `fd2b894`
(harness committed, product tree clean), PostgreSQL 17.10, schema029, Python
3.13.13. Results: [`results.json`](results.json). Behavior: [temporal search](../../temporal-query.md).

## What was frozen

Cases and labels were written and hashed before any product code existed
(commit `7d6aabf`, 2026-10-31T10:49:38Z; hashes in
[`fixtures/FROZEN.sha256`](fixtures/FROZEN.sha256), re-checked by the harness):

| File | Content | SHA-256 |
|---|---|---|
| `parser-cases.json` | 24 development and 24 held-out parser cases | `9528011b…5613f` |
| `ranking-corpus.json` | 36 synthetic documents: claims with dated sources, assertions, refuted, withdrawn, private, legacy and future-plan rows | `824bdcc2…43050` |
| `ranking-cases.json` | 15 development and 17 held-out search cases with expected and forbidden documents | `7cd9a2c8…8b9f` |

Development cases were used while writing tests; held-out cases only here. All
rows are written through the audited gateways into a disposable database that the
harness creates and drops. Search runs as `rag_reader` with lexical full-text
retrieval only (embeddings and the neural reranker unavailable), `k=5`,
`context=off`. No provider, model or network call is made.

## Results

| Measure | Development | Held-out |
|---|---:|---:|
| Parser cases correct | 24/24 | 24/24 |
| Ranking quality cases | 10 | 11 |
| Top-1, feature off | 0.10 | 0.09 |
| Top-1, feature off, time words removed by hand | 0.30 | 0.27 |
| Top-1, feature on | 0.90 | 1.00 |
| MRR off / words removed / on | 0.10 / 0.49 / 0.90 | 0.09 / 0.51 / 1.00 |
| Recall@5 off / words removed / on | 0.10 / 0.90 / 0.90 | 0.05 / 0.88 / 1.00 |
| Top-1 better / worse than words-removed baseline | 6 / 0 | 8 / 0 |
| Hard filter: exact expected set, precision | 2/2, 1.0 | 3/3, 1.0 |
| Ambiguous period, soft order unchanged | 1/1 | 1/1 |
| Ambiguous period, hard filter failed closed | 1/1 | 1/1 |
| No-period controls with `auto` enabled identical to off | 3/3 | 3/3 |
| Forbidden (ineligible, private, superseded) documents returned, off / on | 0 / 0 | 0 / 0 |

Latency, 15 alternating off/on pairs per case after 3 warm-up pairs, one
in-process reader:

| Paired difference on − off | Development | Held-out |
|---|---:|---:|
| Cases with a period: median / p95 | +27.7 / +54.5 ms (165 pairs) | +27.5 / +55.2 ms (195 pairs) |
| No-period controls: median / p95 | −0.1 / +16.2 ms (45 pairs) | +0.1 / +15.1 ms (45 pairs) |

## How to read the numbers

Removing time expressions improves candidate retrieval because lexical search
requires every search word. The "time words removed by hand" column separates
that effect from event-time ordering. On the held-out cases, Recall@5 rises from
0.05 to 0.88 with word removal and to 1.00 with temporal ordering/filtering. Top-1
rises from 0.09 to 0.27 with word removal and to 1.00 with the complete feature.
Compared with the words-removed arm, 14 of 21 quality cases improve at top-1
across both splits; none get worse.

The feature-off column is slightly too favorable in RD01 and HD01. Document
titles are indexed with the body, and the frozen fixture titles contain the key
names (for example "Synthetic dev-backup-yesterday"), so a plain search for
"yesterday" found exactly that document. This was noticed after freezing and left
unchanged.

Development case RD07 ("mail relay port changed yesterday") has no candidates in
any arm because no document contains *changed*. Temporal search cannot add
candidates; it only reorders or filters what retrieval returned. HD13 and RD11
are "unchanged" because both arms return nothing for the unsupported or ambiguous
query, so they show the fail-safe path, not a ranking comparison.

The added latency is one batched event-time query per search that re-checks
eligibility of up to 150 candidates. It is a synthetic, single-process figure, not
a production estimate.

## Examples

| Query (reference, zone) | Interval (UTC) | Off | On |
|---|---|---|---|
| HD01 "certificate renewal failed yesterday" (2026-03-30 09:00 +02:00, Europe/Berlin) | 2026-03-28 23:00 – 2026-03-29 22:00, a 23-hour DST day | words removed: `feb`, `lastweek`, `nextday` | `boundary` (23:30 local), `yesterday`, then the rest; `nextday` (00:30 local on the 30th, still the 29th in UTC) is not matched |
| HD04 "Druckerwartung nächsten Monat" (same) | 2026-03-31 22:00 – 2026-04-30 22:00 | none; words removed: `jan`, `legacy`, `mar`, `apr` | `apr` (stored future plan) first; legacy note marked `unknown` |
| RD03 "nightly backup job failed gestern", `filter` (2026-10-30 10:00 +01:00, Europe/Berlin) | 2026-10-28 23:00 – 2026-10-29 23:00 | none; words removed: `legacy`, `old`, `lastweek` | only `yesterday`; the assistant span dated yesterday, the refuted and withdrawn reports and the private-project report are not returned |

## Reproduce

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
  .venv/bin/python docs/benchmarks/2026-10-31-temporal-query/measure.py > results.json
```

The harness refuses a non-local database host and cleans up only the database it
created. Database IDs differ per run; quality numbers are deterministic, latency
varies with the machine.

## Compatibility evidence

[`compatibility-evidence.json`](compatibility-evidence.json) comes from
`tests/service/test_temporal_upgrade.py` (`RAG064_EVIDENCE=<file>`): the actual
archived 0.6.16 code (`8772fbd`) wrote the corpus; 0.6.17 legacy and temporal
reads, 0.6.16 local and REST reads with a 0.6.17 configuration, and feature-off
rollback left all 35 non-operational table hashes unchanged (documents, sources,
evidence, assertions, domains, audits, histories, migrations). The 0.6.16 service
answered an unrequested-option payload with 200 and an explicit `temporal` option
with 400 `invalid_arguments`. Hashes are per run because IDs are generated.

## Limits

Synthetic 36-document corpus; lexical retrieval only; candidate-limited ordering
over at most 150 candidates; no embeddings, neural reranker, private corpus or
production measurement.
