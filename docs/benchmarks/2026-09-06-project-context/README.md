# Synthetic project-context comparison — 2026-09-06

Seven fictional documents, twelve labeled prompts (six relevant, six unrelated),
three repetitions per prompt/variant. The baseline executes the preserved error
recall helper; the new variant executes the real prompt hook and replays the same
turn. A temporary database is created and its cleanup verified. No private corpus,
embedding endpoint or hosted model is called.

| Metric, all 12 prompts | Before | After |
|---|---:|---:|
| Useful context / relevant prompts | 1/6 | 6/6 |
| Useful results / fired prompts | 1/1 | 6/6 |
| Unrelated injections | 0/6 | 0/6 |
| Mean context characters | 21.42 | 183.67 |
| Mean repeated same-turn characters | 21.42 | 0 |
| Repeated tokens, characters / 4 estimate | 5.35 | 0 |
| Duplicate expected substrings | 0 | 0 |
| Hook path p95 | 19.68 ms | 51.65 ms |

The nine test-labeled prompts improve from 1/5 to 5/5 relevant hits, with 0/4
unrelated injections. Their p95 is 50.62 ms after the change. Three dev-labeled
prompts are reported separately in `results.json`. These are implementation-time
fixtures, not a blind held-out study or evidence of broad semantic accuracy.

Useful means the labeled expected substring appears in emitted evidence, not a
model-judged answer score. Precision uses useful results over fired prompts. Larger
mean output is expected because ordinary questions now receive evidence. Zero replay
output applies only to the same real turn and unchanged revision; regression tests
separately verify later turns, source corrections and failed emission. Tokens are
estimates, not tokenizer measurements. Startup preserves the exact synthetic
multiline pin while adding source-backed conventions. All prompt output stays
within 4,800 characters and excludes the foreign-project marker.

The tiny corpus does not establish latency at production scale, multilingual
coverage beyond these cases, semantic paraphrase recall or real-world precision.
The old-path baseline includes a reader connection even when its error gate does
not fire; sub-millisecond negative-path latency differences are not meaningful.

Reproduce from repository root with local test-database create privileges:

```sh
PYTHONPATH=. python docs/benchmarks/2026-09-06-project-context/evaluate.py
```

`cases.json`, `evaluate.py` and `results.json` retain the corpus, exact outputs,
per-run timings, dev/test aggregates, corpus hash and implementation source hash.
