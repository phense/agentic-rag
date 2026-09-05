# Inspection of the authorized real-model smoke run

Run from published revision `d121ab8`. User explicitly approved publication and
this eight-question model evaluation. The configured Codex adapter used
`gpt-5.6-luna` with high reasoning and local bge-m3 embeddings. Ten synthetic
sources were ingested through actual mining. Thirteen model commands were
attempted (including windowed extraction, answer generation and separate judging).
Elapsed time: 100.70 seconds; all ten sources indexed; no operational failures.
Billing and token usage remain unknown because the CLI interface does not expose them.

The coordinator inspected **all eight** saved questions, corpus labels, retrieved
contexts, exact answers and judge explanations after the run. This is an additional
inspection of the results, not a separate human annotation study or a second model run.

| Query | Observed answer | Source check and verdict |
|---|---|---|
| atlas-port-en | 7712 | Atlas service port is explicit; 9913 is metrics and 7724 belongs to Boreal. Correct. |
| update-de | Cobalt | The source states the change from Amber on August 20 and current value as of September 1. Correct. |
| expiry-en | closed | The source explicitly ends the Oak window on August 31. Correct. |
| tail-de | POPLAR_TAIL_817 | The original source ends with this marker; mining retained it in its own memory and retrieval included it. Correct. |
| multi-hop-de | Noor | Hawthorn uses Kestrel; the second source names Noor as Kestrel owner. Both sources are in context. Correct. |
| multi-session-en | harbor-export-key | Alder selected Harbor; the later session assigns this key to Harbor exports. Both sources are in context. Correct. |
| negative-0-en | empty, abstained | No source supplies Atlas travel-budget information. Correct abstention. |
| negative-5-de | empty, abstained | No source supplies an owner for Zephyr. Correct abstention. |

All eight agree with deterministic scoring and separately recorded model judging.
Recall@5/10 and MRR are 1.0 on the six answerable questions; answer accuracy is
8/8, including 2/2 correct abstentions. Stale-answer rate is 0/8. These are small
smoke-test denominators, not evidence of general model quality. The corpus is
synthetic, reduced and easy enough that retrieval already reaches a ceiling.
Temporal cases test reading explicit dated facts, not a temporal database engine.
The same provider also judges answers, so model-judge bias remains possible.

The source/corpus hashes and aggregate metrics were recomputed from saved evidence.
The actual PostgreSQL catalog was checked after the run: no owned benchmark database
remained. No private transcript or canonical knowledge-store document was used.

Reproduce with the existing configuration (requires an authorized model budget):

```bash
rag benchmark run --corpus docs/benchmarks/2026-09-05-memory-model-smoke/corpus.json \
  --mode end-to-end --smoke --answers --judge --output /tmp/rag-model-smoke-new
```

Extraction/model outputs can vary on a future run; the dataset bytes and configuration
are versioned. See [report](report.md) and [raw results](results.json).
