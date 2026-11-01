# Memory lifecycle measurement (RAG-066)

This measurement checks the deterministic rules of lifecycle decisions and the
tightened automatic curation on a small, hand-labelled synthetic corpus. It runs
the real gateways, preview, apply and correct, the SQL view predicate, lexical
search and both curation versions on owned PostgreSQL databases that the script
creates and drops. No model or provider is called (`provider_calls: 0`), so the
figures say nothing about semantic accuracy or any model's quality.

- Source: `0b3ca4e` (clean tree), package 0.6.19, migration031. Later commits
  change only the `rag review` output, tests, documents and the version number.
- Comparison: the automatic curation of the actual 0.6.18 code (`git archive` of
  `d4d2372`), run in a subprocess on the same ingested corpus.
- Environment: Python 3.13.13, PostgreSQL 17.10 with pgvector, one shared host.
- Repetitions: 3. All deterministic outcomes were identical in every repetition
  (`deterministic_outcomes_identical: true`); only timings vary.
- Raw output: [results.json](results.json). Script: [measure.py](measure.py).

## What was frozen

[fixtures/corpus.json](fixtures/corpus.json) holds 46 entries in 22 cases
(45 stored documents: the two E2 claims resolve to one record by design).
[fixtures/labels.json](fixtures/labels.json) holds the author's expectation per
case: the human judgement of the pair, the expected preview, the expected
documents per view after each operation and the expected curation result of both
versions. Both files were committed (`b0f3bf5`) before any product change; their
SHA-256 values are checked on every load (`FROZEN.sha256`). No label was changed
afterwards.

## Results

| Question | 0.6.19 | 0.6.18 |
|---|---|---|
| Copies archived by automatic curation (budget 50) | 5: D1, E1 and three M1 copies | 8: the same five plus T1-beta, T2-lesson, T3-b |
| False merges (archived although the label says different knowledge) | **0** | **1** (T1-beta: "Build server beta port" archived in favour of "alpha port") |
| Same-knowledge pairs not merged automatically | 2 (T2: same text, different type; T3: same text, different title) | 0 |
| Matches the frozen curation label | yes | yes |

The two pairs 0.6.19 leaves alone are the deliberate price of the title and type
rule: an operator can still merge them with a reviewed `semantic_duplicate`.

| Check (per repetition) | Result |
|---|---|
| Preview classification, proof and refusal codes against labels | 31 of 31 |
| Views after applying E1, R1, P1, P2, C1, X1, D1, G1 and two M1 copies (incl. as-of, chain attempts) | 32 of 32 |
| Transitions: source withdrawn and reinstated (X1), content edit and revert (D1), target archived (R1), target refuted and purged (G1), correction (P1) | 8 of 8 |
| Original rows of 11 source tables unchanged by all decisions | yes |
| `ev1` of every document unchanged by all decisions | yes |
| Decisions / events / audit rows after the run | 10 / 11 / 11 (one correction) |
| k=1 search for "flush the DNS cache" | E1-keep in every view |
| Provider calls | 0 |

Retrieval, top eight lexical hits for one query per case. "Members" are the
documents a decision hides:

| Case and query | Members in top 8 before | after, current | after, `include_merged` |
|---|---|---|---|
| E1 "flush the DNS cache" | E1-copy | none | E1-copy |
| M1 "release wheel changelog" | M1-copy1, M1-copy2 | none | both |
| R1 "printer toner" | R1-short | none | R1-short |
| P1 "wiki backups" (replacement) | P1-old | none | none |
| P2 "mail relay" (replacement) | P2-older-late | none | none |
| D1 "plotter paper" | D1-copy | none | D1-copy |
| X1 "disk alerts ops channel" | X1-short | none | X1-short |

Concurrency, replay and failure (labels in `labels.json` → `concurrency`):

| Situation | Outcome |
|---|---|
| Two writers apply opposite decisions for one pair at the same moment | one `ok`, one `stale_version`; 1 active decision, 1 event, 1 audit row |
| Same decision again with a new request key | same decision, `replayed: true`; still 1 decision and 1 event |
| Known request key with another reason | `replay_mismatch` |
| Member edited after the preview (same text, new update time) | `stale_version` |
| Old inspected versions replayed after a correction | returns the corrected decision; the member stays current |
| Injected audit-write failure | 0 decisions, 0 events, 0 audit rows added |
| Apply with the reader role | `InsufficientPrivilege`; nothing added |

Timings, median of the three repetitions' medians (shared host, so treat them as
an order of magnitude):

| Operation | Median |
|---|---|
| Preview (14 pairs, own reader connection each) | 182 ms |
| Apply (10 decisions, preview plus apply, own connection each) | 452 ms |
| Lexical search on the fixture corpus, before / after decisions | 48 ms / 56 ms |
| New automatic curation pass | 86 ms (first repetition 258 ms) |
| 0.6.18 curation pass, including the Python subprocess start | 1.34 s |
| Worst case: broad query whose 300 matches are all merged members, before / after | 270 ms / 654 ms |
| Same store, unrelated query, before / after | 26 ms / 25 ms |

The worst-case row comes from an extra section of the script (300 identical pairs
plus 300 decisions). It led to a fix before this measurement: the first version
re-planned two nested SQL functions per hidden hit, and the same query took
2.7 s (commit `ce1c8bf`).

## Examples, inspected by hand

The `examples` section of `results.json` keeps the full `memory_lifecycle` detail
of three documents from the first repetition, with ids replaced by fixture keys.

1. **E1-copy, exact duplicate.** `current: false`; one decision as member with
   `operation: exact_duplicate`, `proof: exact`, `relationship: hiding`,
   canonical "VPN reconnect procedure" (E1-keep), `revision: 1`. The document
   itself is still `status: active` with its own slug: nothing was archived.
2. **P1-old, replacement.** `proof: event_order`, `effective_at:
   2026-06-01T08:00:00+00:00` (the target's source time), `relationship:
   replaced`, canonical "Wiki backup target moved". An as-of search for
   2026-04-01 still returns P1-old, which matches the label: before the event
   the old target was current.
3. **C1-a, contradiction.** `state: contested`, `relationship: contested`,
   `current: true`: neither DNS server statement is hidden, and both appear in
   `rag review`.

Each detail carries the fixed statement that only identical title, body, type and
claim identity or the order of source events are proven, and that semantic
equivalence, extension and contradiction are operator judgement.

## Limits

- 45 synthetic documents in one domain pair and two projects; not a private or
  production corpus, and too small for statistical claims.
- The human labels are one author's judgement. Semantic decisions in the
  measurement are applied with `reviewed` exactly as labelled; nothing here
  measures whether an operator or a model would judge correctly.
- Lexical retrieval only; embeddings, rerankers and context indexing are off.
- The worst-case section is constructed, not a usage profile. Its cost grows
  with the number of merged members among a query's matches.
- Sustained use with real models (#21) is not covered and stays open.

## Reproduce

Run against an owned local PostgreSQL only; the script refuses `PGHOST`,
`PGHOSTADDR`, `PGSERVICE` and `PGSERVICEFILE` and drops every database it creates.

```bash
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
  .venv/bin/python docs/benchmarks/2026-10-31-memory-lifecycle/measure.py \
  --repetitions 3 --output docs/benchmarks/2026-10-31-memory-lifecycle/results.json
```

One repetition takes about 75 s; the 300-pair section takes most of it.
