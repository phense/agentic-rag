# Feature7: Thematic summaries, costs and compatibility

Measurements started2026-10-03 and completed across the2026-10-04 local session.
Source `bd01d97b1188e6bb0cf71e838c7c35e3449d8f3b`, schema016; candidate017.
[Raw results](results.json) record exact implementation/driver SHA-256 hashes,
revision, all20 paired repetitions, first observations, quality counts and refresh
usage. The measured candidate bytes match committed implementation `d4d286c`;
all eight frozen file hashes were compared with that commit. The source HEAD at
measurement start is recorded separately; raw values remain unchanged.

## Original-corpus examples on the recovered private snapshot

The already verified source016 production dump was SHA-checked and strictly
restored into an empty owned disposable database. All17 public-table fingerprints
matched the private inventory. After017 and local gateway refreshes, all15 original
protected tables remained identical, including10466 documents,571 assertions,
995 accepted batches,1400 queued jobs,25 checkpoints and22 pins. All37147 historical
audit IDs survived. Private content never enters this report or a provider call.

Both routes use the same lexical query, project/domain and4800-character context
budget, and return exact original chunk citations. Baseline uses the original
search module (k24, lexical, rerank off); candidate reads the refreshed thematic
view. Search dependencies are verified byte-identical to source. The independent
denominator is all currently eligible documents matching the selected lexical
expression, not human-rated relevance or answer correctness. There are20 alternating
warm paired API calls per route/case; connections/imports are outside query timing.

| Practical example | Eligible documents visible before → after | Context chars before → after | Query p50 before → after (ms) | Query p95 before → after (ms) |
| --- | --- | --- | --- | --- |
| Past provider outages |8/12 →12/12 |4748 →3526 |53.531 →69.609 |54.391 →70.991 |
| Deployment architecture references |7/8 →8/8 |4236 →2297 |44.436 →57.139 |45.219 →57.687 |
| Recurring operational lessons |8/15 →15/15 |4783 →4310 |61.701 →216.397 |76.398 →229.286 |

Context falls25.74%,45.77% and9.89% while more eligible documents fit. Query
latency increases in all three real-snapshot examples, especially the all-domain
lessons case. No production speedup or semantic quality improvement is claimed.
Every retained citation and selected filter passes the structural oracle in all
20 repetitions. The deployment snapshot example uses current references;
superseded historical evolution is verified separately by temporal tests.

| Theme | First creation (ms; entries rebuilt) | No-change refresh p50 / p95 (ms) | Rebuilt / reused per no-change refresh |
| --- | --- | --- | --- |
| Provider outages |196.380;12 |62.067 /140.413 |0 /12 |
| Deployment architecture |127.319;8 |114.907 /123.616 |0 /8 |
| Operational lessons |446.820;15 |65.987 /464.319 |0 /15 |

Creation is one observation per case, not a latency distribution. Refresh has
20 observations. First query calls are recorded separately; OS/database caches
were not flushed, so they are not cold-cache results. SQL candidate/version scans
remain corpus-dependent. Extract reuse does not remove that cost.

## Public controlled examples

Three public synthetic scenarios each contain eight source-backed records plus
foreign-project/domain controls. Expected fact strings and IDs are established
before running either route. Every measured input and4800-character budget is
the same across routes. These controls demonstrate extraction, source coverage
and compression rather than production answer accuracy.

| Scenario | Source/fact coverage before → after | Context before → after | Query p50 before → after (ms) | First creation (ms) |
| --- | --- | --- | --- | --- |
| Provider outage history |7/8 →8/8 |4234 →1708 |20.764 →12.202 |38.531 |
| Deployment stage records |7/8 →8/8 |4234 →1836 |20.127 →11.771 |47.901 |
| Cross-session recovery lessons |7/8 →8/8 |4234 →1856 |23.505 →12.776 |46.048 |

Each result repeats20 times with zero citation errors. Synthetic deployment
stages retain one PostgreSQL/pgvector architecture; this is not a semantic
assessment of a changing architecture. A separate one-source correction per
case withdraws its upstream source and adds a corrected source through gateways:
refresh rebuilds1 entry and reuses7, costing34.166 /30.429 /29.864ms respectively.
Twenty no-change refreshes rebuild0/reuse8 and retain cache generation/audit count.
The raw JSON contains p95, first calls and every result, not just medians.

## Reproduction and safety

Run from the candidate checkout using the canonical interpreter:

```sh
PYTHONPATH="$PWD" /Users/peter/Agents/agentic-rag/.venv/bin/python \
  scripts/verify_thematic_summaries.py --repeats 20 --trading \
  --output /private/operator-selected/thematic-results.json
```

To repeat the private recovery evidence, add `--private-recovery-dump` and
`--private-recovery-report` with the previously verified dump and matching private
inventory. The driver validates SHA before restore, chooses its own marker-owned
destination, checks all inventories and cleans up. The published output contains
only aggregate original-corpus data. Without these flags, only the synthetic
rehearsal and optional canonical Trading reader controls run.

The synthetic rehearsal verifies transactional017 interruption/rollback,
retry/idempotence,16 original application-table fingerprints/grants, source/
candidate/code-rollback search citation parity, actual MCP8/14 →9/15 →8/14, and
strict source016/candidate017 backups restored into separate empty targets. The
private recovery makes assertion/edge/batch/queue preservation non-vacuous.
Trading's live016 store has no summary table: three reader-only controls report
explicit unavailable fallback,0 writes and0 providers. No private body, prompt,
title or ID is published. See [verification](../../verification/thematic-summaries.md).

The additional `scripts/verify_thematic_activation.py` rehearsal executes the exact
PB activation/rollback snippets on an owned local Git clone, populated017 database
and private flock path. It verifies busy-lock refusal, fast-forward activation,
detached source rollback, prior branch-tip retention, original CLI citation parity,
preserved rows/schema and released lock. [Activation results](activation-results.json)
bind that execution to the exact reviewed PB SHA. It makes no canonical Git,
database or worker-lock change; backup/MCP checks are the separate summaries driver.
