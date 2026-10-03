# Feature6: measured bounded research

Compound questions recover their separate source passages in this controlled
workload, with extra retrieval and worker-startup cost. These are source and
literal-excerpt measurements, not a claim about production answer accuracy.

## Revisions and method

Source is `19ed09c1b3c46d907254f63a1370586ea3213966`, schema001–016.
The candidate was measured from the uncommitted Feature6 checkout; exact
implementation and driver SHA-256 values are in [results.json](results.json).
The driver verified that those hashes matched after measurement. The committed
candidate can be matched to these hashes; a base HEAD alone does not identify
uncommitted implementation bytes.

Each of three public synthetic cases has20 warm, alternating before/after
pairs plus a separately reported first observation. Caches were not flushed;
the first observation is not a hardware-cold measurement. Inputs, project,
domain, lexical strategy, `k=6` retrieval calls and12000-character evidence cap
are matched. Ordinary search remains byte-identical to the source revision.
Its before route is a direct library call on a warm reader connection;
research's after route includes a fresh isolated worker and reader connection.
The difference includes that startup cost and is not an isolated algorithm
latency estimate.

The questions deliberately combine terms whose conjunction misses documents
containing only one facet. Separate manual searches already find those sources;
the feature performs that decomposition, graph lookup and evidence accounting
within one bounded operation. The baseline supplies snippets, not a semantic
answer or an abstention verdict. `abstained=null` denotes that unavailable
baseline field. Source coverage counts expected fixture documents; fact coverage
counts exact expected strings in retained original excerpts. Neither metric
is a generated-answer judge.

## Three practical before/after examples

| Matched question | Expected sources and literal facts, before → after | Local outcome after | Median latency before → after | p95 before → after |
|---|---|---|---|---|
| Aurora storage decision and present constraints | Sources0/2→2/2; facts0/2→2/2 in20/20 pairs | Two qualified excerpts; semantic answer abstained |16.691→210.965ms |18.248→215.960ms |
| Beacon incident cause and recovery probe | Sources0/2→2/2; facts0/2→2/2 in20/20 pairs | Cause plus `OK` proof from a late handbook chunk reached through a source link; semantic answer abstained |16.831→223.825ms |17.531→249.726ms |
| Cinder retention and absent approved replica count | Sources0/2→2/2; facts0/2→2/2 in20/20 pairs | One explicit disagreement, zero supported statements, two unresolved facets; abstained |13.163→246.786ms |17.178→266.743ms |

The first two cases use3 logical operations and1 round; the third uses6
operations and2 rounds. Their retained contexts are1617,2820 and1483 characters.
All60 after observations stay below their declared budgets; all retained
citations reproduce original chunk substrings with zero errors. Controlled
provider calls are0. Each qualifying fixture quote has two separate upstream
source IDs; this synthetic construction does not establish human independence.

Local missing facets intentionally remain unresolved even when both literal
excerpts are present: the feature does not equate token overlap with proof of
semantic coverage. It never writes an inferred answer back to the store.

## Configured-provider integration probe

Three additional public synthetic requests used the existing configured Codex
CLI, `gpt-6.1-sol`, with an explicit120-second budget. There was one observation
per case and7 provider operations in total. No Trading content was sent.

| Case | Exact supported statements | Disagreements | Missing facets | Abstained | Observed time |
|---|---:|---:|---:|---|---:|
| Architecture |1 |0 |1 |true |20.656s |
| Incident |2 |0 |0 |false |20.542s |
| Contradictory/missing |0 |2 |2 |true |32.748s |

All returned citations passed the original-span check. The architecture probe
missed one facet after provider planning, showing why the local controlled
coverage result must not be presented as guaranteed provider performance.
The contradictory case includes both explicit graph and provider disagreement
entries; these are two reports, not two independently established conflicts.
One observation per case verifies integration, not model accuracy, repeatability
or a latency distribution. The configured provider can rephrase a query into
one that finds fewer sources; missing evidence remains visible.

## Existing installation and recovery

A randomly owned, populated schema016 database holds10 documents,149 chunks,
18 source records,18 evidence records,9 reviewed claims,2 edges,4 domains,
a pin, a checkpoint, queued work and52 audit rows. Every fixture write uses
the audited gateways. The actual archived source code, candidate and old-code
rollback are exercised on that same installation through CLI and stdio MCP.

All16 application-table full-row fingerprints and table privileges are
preserved. Old CLI citations match candidate and rollback; actual old MCP
servers expose7 read/13 total tools, candidate8 read/14 total, and rollback
returns to7/13. The six write tools remain the same. Schema remains016 and
application knowledge writes during acceptance are0.

A verified consistent-snapshot `pg_dump -Fc` is restored with strict,
single-transaction, exit-on-error semantics into a fresh isolated database.
All17 public tables, including migration history, and application privileges
match. Temporary databases and dump resources are cleaned up. Some tables
remain empty in this fixture; temporal/assertion behavior and concurrent
clients have separate gateway-based regression tests. This is a code-only
upgrade and rollback rehearsal, not a production migration or deployment.

Deadline, async cancellation, real stdio MCP cancellation, descendant cleanup,
nested provider-temp cleanup and clean retry are covered in
[the regression suite](../../../tests/test_research.py). The0.3-second stalled
worker deadline test asserts return plus cleanup under2 seconds; OS scheduling
and already-dispatched service work are outside a strict instantaneous-stop
claim. No existing service is terminated.

## Trading read-only controls

Three canonical Trading controls have5 observations each against4093 eligible
chunks. They use local embeddings and the reader role:0 provider calls,
0 application writes,0 citation errors, all15 abstained with0 supported
statements under the conservative qualification rules. Median times are
2266.067,2264.765 and2239.660ms; p95 values2880.134,2322.659 and2300.776ms.
Maximum retained context in the reported samples is7538 characters. Only
aggregate metrics are public; no private source text, citations or result
payloads are included. These are safety/latency controls, not a production
before/after quality evaluation.

## Reproduce

First change the working directory with `cd /path/to/candidate`. Run the
following command from that candidate root using the existing canonical
environment and explicit PYTHONPATH. Running `python -m` from an old checkout
would shadow PYTHONPATH with that checkout's code; the measurement driver
sets each actual CLI/MCP subprocess's working directory explicitly.

```sh
PYTHONPATH=/path/to/candidate /path/to/canonical/.venv/bin/python \
  scripts/verify_bounded_research.py --repeats 20 \
  --output /tmp/bounded-research-results.json
```

`--provider-smoke` opts into configured-provider calls using public fixtures.
`--trading` adds the authorized canonical reader controls. Omit both for an
isolated local reproduction. Database create/drop access is required for the
driver's owned disposable databases; never substitute the live database as
its fixture target. See [verification](../../verification/bounded-research.md)
and [operation](../../bounded-research.md).
