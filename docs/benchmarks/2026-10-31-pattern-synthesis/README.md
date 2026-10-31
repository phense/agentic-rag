# Pattern synthesis measurement (RAG-065)

Frozen synthetic cases run through the real pattern pipeline: preview, scheduler,
existing worker drain, validation, audited application and guarded reads. Product
revision `7603b7b`, PostgreSQL 17.10, schema030, Python 3.13.13, Intel Xeon
E5-2650. Results: [`results.json`](results.json). Behavior:
[pattern synthesis](../../pattern-synthesis.md); output contract:
[pattern-v1](../../specs/6-7-pattern-synthesis/contracts/pattern-v1.md).

**This is not a model-quality measurement.** The structured-provider boundary is
replaced by frozen scripted answers. The numbers show how the pipeline treats
honest and dishonest model output. No real model was called.

## What was frozen

Cases, scripted answers and labels were written and hashed before any product code
existed (commit `84bce47`, 2026-10-31T17:30:15Z). Hashes are in
[`fixtures/FROZEN.sha256`](fixtures/FROZEN.sha256) and re-checked on every load:

| File | Content | SHA-256 |
|---|---|---|
| `corpus.json` | 35 synthetic rows in 10 cases, one project scope per case | `8b238817…38d8d7081` |
| `responses.json` | 10 scripted answers: `oracle` (honest) and `adversarial` | `4cd4fb6b…190244afb76` |
| `labels.json` | Expected preview counts, outcome, reason, applied count and provider calls | `d7fbcff3…a88901dc4` |

Eleven evaluations are development cases, used while writing tests. Four are
held-out cases (K2, C2 ×2, F5), used only here. Every row is written through the
audited gateways into a disposable database that the harness creates and drops.

The ten cases:

| Case | What it contains | Variants |
|---|---|---|
| K1, K2 | 4 and 3 independent reports of the same problem with a fix | honest; K1 also dishonest |
| I1 | 3 independent reports that a cache reset helped | honest, dishonest |
| C1, C2 | 3 reports that contradict each other | honest, dishonest |
| F1 | 3 memories that quote the same single event | worker, dishonest |
| F2 | 1 user report plus assistant-only and inferred rows | worker |
| F3 | Operator notes without a qualifying user span | worker |
| F4 | Derived summary, partial quote and legacy unmanaged row | worker |
| F5 | 3 memories over only 2 distinct events | worker |

`worker` means the scheduler runs with a provider that fails the test if called.

## Results

Three repetitions, identical outcomes in all three.

| Measure | Value |
|---|---:|
| Evaluations (development / held-out) | 15 (11 / 4) |
| Matching the frozen label | 14, plus 1 recorded label erratum |
| Patterns applied | 4 |
| Supported parts in applied patterns | 8 |
| Rejected suggestions | 3 |
| Non-conclusions | 11 |
| Provider calls | 9 |
| Provider calls below the support floor | 0 |
| Wall time, 3 repetitions | 15.4 s |

Outcome per evaluation:

| Case | Variant | Outcome | Reason | Calls |
|---|---|---|---|---:|
| K1 | honest | applied, 3 parts | | 1 |
| K2 (held-out) | honest | applied, 2 parts | | 1 |
| I1 | honest | applied, 2 parts | | 1 |
| C1 | honest | non-conclusion | `conflicting_sources` | 1 |
| C2 (held-out) | honest | non-conclusion | `conflicting_sources` | 1 |
| K1 | dishonest | non-conclusion | `unknown_citation` | 1 |
| I1 | dishonest | non-conclusion | `invalid_output` | 1 |
| C1 | dishonest | non-conclusion | `conflicting_support` | 1 |
| C2 (held-out) | dishonest | **applied, 1 part** | | 1 |
| F1 | worker | non-conclusion | `insufficient_independent_support` | 0 |
| F1 | dishonest | non-conclusion (validator) | `insufficient_independent_support` | 0 |
| F2, F3, F4 | worker | non-conclusion | `insufficient_independent_support` | 0 |
| F5 (held-out) | worker | non-conclusion | `insufficient_independent_support` | 0 |

Preview exclusions matched every label: F2 excluded 2 rows without a qualifying
span and 1 inferred row; F3 excluded 3; F4 excluded one derived, one legacy
unmanaged and one partial-quote row.

Timings in milliseconds, one in-process connection:

| Step | n | Median | Max |
|---|---:|---:|---:|
| Preview | 45 | 16.2 | 60.1 |
| Schedule | 42 | 19.2 | 45.0 |
| Drain (includes the scripted call) | 42 | 45.2 | 148.9 |
| Inspect an applied pattern | 12 | 15.2 | 33.4 |
| Validate one answer (no database) | 3 | 0.1 | 0.1 |

Finite inputs: each provider prompt carried 1,041 to 1,412 characters. The
generation limits bound every prompt: 12 memories, 8 spans per memory and
8 spans per suggestion.

## Examples, inspected by hand

**K1, honest, applied.** Four users reported that short internal names stopped
resolving after a VPN reconnect. The pattern "VPN reconnect clears the DNS suffix
list" is stored as an unreviewed inference with medium confidence. Its three
parts cite 3, 3 and 1 original memories, each by `ev1` version, source reference
and `src1` source version; the suggestion as a whole rests on 4 events across 4
memories. No raw source path or namespace appears.

**C1, dishonest, rejected.** The scripted model claims that the dedup job causes
the backup overruns and cites the report that says it "was not the dedup job" as
support. The validator finds a supporting and a contradicting quote on one part
and rejects the suggestion with `conflicting_support`. Nothing is written.

**I1, dishonest, rejected.** The scripted model adds fields the output contract
does not allow (`kind: stated`, another domain and project scope) and cites an id
it was never offered. The answer fails the strict output schema, so the run ends
as `invalid_output` without a retry and without a write.

## Label erratum

Label F1-adversarial expects one provider call. Below the support floor the
pipeline never calls a provider, which the accepted contract requires. The harness
therefore checks the frozen over-claiming answer directly with the validator, and
outcome, reason and applied count match. The label stays unchanged and the
mismatch is listed in `LABEL_ERRATA` and in `results.json`.

## Limits

- **C2, dishonest, was applied.** The scripted model marked a report saying
  "8443 is open" as *supporting* "port 8443 is blocked". The validator checks
  citations, spans, support counts and declared stances; it cannot detect a model
  that lies about a stance. The result is still only an unreviewed inference with
  exact citations; each citation leads to the original memory, where the
  contradicting report can be read.
- Synthetic corpus of 35 rows in one domain. No embeddings, no real model, no
  private data, no production measurement.
- Timings come from one process on one machine and include no network or model
  latency. They are not a production estimate.
- The central worker loop is covered by `tests/service/test_runner.py`; the
  harness calls the scheduler directly.

## Reproduce

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE PGPORT=55460 \
  .venv/bin/python docs/benchmarks/2026-10-31-pattern-synthesis/measure.py \
  --repetitions 3 --output docs/benchmarks/2026-10-31-pattern-synthesis/results.json
```

The harness refuses a non-local database host and drops only the database it
created. Exit status is 0 when every mismatch is a recorded erratum and the
repetitions agree. Database IDs and timings differ per run.

## Compatibility evidence

[`compatibility-evidence.json`](compatibility-evidence.json) was written by
`tests/service/test_synthesis_upgrade.py`. The actual 0.6.17 code (`81beaf6`,
schema029) populated a store with 302 rows in 39 tables. The upgrade to schema030
took 2.22 s, preserved every original row and created no synthesis policy, run,
job or pattern. Old 0.6.17 reads were identical afterwards. One pattern generated
after the upgrade cost exactly one provider call. A pre-upgrade restore loses
writes made after the upgrade, as expected.

Old 0.6.17 `memory_get` returns a pattern body if asked for its id directly,
because the old code lacks the new read guard. Old search stays guarded in SQL.
