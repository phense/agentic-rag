---
title: Provider and embedding-generation verification
type: reference
doc_id: standalone
readers: [maintainers, installation-operators]
version: 0.6.14
last_edited: 2026-10-30
summary: Synthetic provider/index comparisons, existing-install preservation and recovery evidence for Issue61.
---

# Provider and embedding-generation verification

Issue61 adds independent extraction/embedding settings and opt-in, source-bound
embedding generations. The original knowledge and legacy index remain in the
same PostgreSQL store. This record describes isolated synthetic verification;
it does not establish production deployment or real-model accuracy.

Writing depth: medium standalone reference. The operator procedure is
[PB061-OPS](../provider-indexes.md); requirements and architecture are in
[RAG-061](../specs/6-3-provider-indexes/spec.md) and the
[as-built model](../uml/provider-indexes.md).

## Revisions and environment

- Base: `8e521a7c32bfe64909373e54a13f3d9b4b068f73`,0.6.13/schema026.
- Runtime implementation: `5c4abceb8f3653d3d88fd4381a67a93d3969b60c`.
- Measured commit: `e6cf92be41f7d5c587de0c90f84ae9f2f4da8b85`,0.6.14/schema027.
  The second commit changes only the measurement fixture's handling/counting of
  the fixed synthetic selection probe. The measurement began and ended clean.
- Linux x86_64,8 visible CPUs, Python3.13.13, PostgreSQL17.10, pgvector0.8.4.
  This is a shared verification host, not a dedicated4-vCPU/8-GiB target.
- Owned PostgreSQL ports55460–55462, generated public fixtures and MockTransport
  at the HTTP boundary. No private corpus, real model request or production
  database migration/restart was used.

## Terms and measurement method

| Term | Meaning in this record |
|---|---|
| Before/after | Different configured routes on the same measured runtime and identical canonical source snapshot within each pair; not timings from an older release. |
| Cold connection | First8 searches on a fresh connection; process, OS and PostgreSQL caches were not reset. |
| Warm | Three additional passes of the same8 queries on that connection,24 samples per route. Neither route uses a query inference cache. |
| Correct@1 | Top result belongs to the generated topic's3 accepted document IDs; a plumbing assertion, not real-model quality. |
| CPU/RSS | Python process user+system CPU delta and sampled resident memory; PostgreSQL/model CPU and memory are excluded. |
| Coverage | Current source-matching chunks in a named generation. New writes require catch-up. |

The fixture has 24 documents/chunks,8 topics and8 query strings absent from the
stored text. Search runs through the normal scoped API with reranking and
contextual retrieval off. Each route has 8 cold and24 warm samples. p95 uses
nearest rank `ceil(0.95*n)`, so the8-sample cold p95 is the maximum.

The [machine-readable record](issue61-providers.json) contains all raw latency
samples, per-query results, request/input/resource counts, source snapshots,
individual vector index sizes and before/after SHA256 manifests. Only repeated
table/index size rows for unrelated relations are omitted from that projection. The
complete run's SHA256 is
`c355fd0a463bb4250aa505cee1e47c58b36176062d4dcb295d48350d286fa094`.
It ran 2026-10-30T13:59:03Z–13:59:28Z, exit0, `valid=true`, with zero runtime
manifest drift and checked removal of its owned database.

## Three measured cases

| Case | Cold median/p95 before → after, ms (8 each) | Warm median/p95 before → after, ms (24 each) | Correct@1 |
|---|---|---|---|
| Legacy1024 → managed3 | 38.698/63.285 → 140.959/190.564 | 64.024/88.785 → 121.493/145.434 | 32/32 on both routes |
| Managed3 revisionA → revisionB | 137.705/194.799 → 149.041/213.798 | 111.267/146.187 → 111.285/143.537 | 32/32 on both routes |
| Managed3 → managed5, interrupted rebuild | 62.409/91.110 → 134.545/201.821 | 84.566/125.767 → 114.130/131.966 | 32/32 on both routes |

These 192 searches all pass the generated fixture assertion. The first and third
cases are slower after switching in this run. No speed or accuracy improvement
is claimed. Shared-host scheduling, small samples, additional identity requests
and different SQL paths limit timing comparisons.

1. **Change dimensions without relabeling old vectors.** The first case rebuilds
   all 24 sources in 5 bounded corpus POSTs. Creation adds 1 discovery GET;
   activation adds 3 GETs and1 fixed synthetic POST. The whole lifecycle phase uses
   20 requests,6 POSTs and25 inputs. The canonical source hash stays identical.
2. **Change revision, preserve compatible configuration.** RevisionB has the
   same3 dimensions but a different identity and gets24 fresh corpus vectors.
   Subsequent credential-reference/timeout changes retain the same generation:
   1 discovery GET,0 POSTs,0 inputs and0 rewritten vectors.
3. **Resume and retain new knowledge on rollback.** A5-input batch commits;
   a fresh connection observes19 missing inputs and processes exactly those19.
   Partial activation refuses. After cutover, a25th canonical document is saved.
   Stale rollback refuses; catch-up processes1 corpus input in each relevant
   generation, then rollback succeeds with all 25 document IDs retained.

For32 search inputs, legacy uses 32 POSTs and0 discovery GETs. Each managed
route uses 32 POSTs and64 GETs: identity is checked before and after inference.
Across ingestion, all comparisons and lifecycle attempts, the run intercepts
691 requests:451 GETs and240 POSTs;297 inputs comprise 192 queries,99 corpus
inputs and6 fixed lifecycle probes, totaling 20,175 characters. These are mock
adapter counts, not billed requests or measured currency cost.

| Case | Warm Python CPU before → after, seconds (24 searches) | Sampled RSS before-route → after-route, MiB | Database bytes before → after |
|---|---|---|---|
| Legacy1024 → managed3 | 0.288 → 0.718 | 51.05 → 51.28 | 10,704,563 → 10,794,675 |
| Managed3 revisionA → revisionB | 0.685 → 0.688 | 51.43 → 51.56 | 10,794,675 → 10,843,827 |
| Managed3 → managed5 | 0.503 → 0.708 | 51.66 → 51.88 | 10,843,827 → 10,901,171 |

RSS values are samples after each warm route in one process, not independent
peaks or leak/plateau evidence. Database bytes include normal PostgreSQL
allocation overhead and retained generations. The managed vector relation's
total bytes grow16,384→49,152→65,536→114,688 across these stages; the original
1024-dimensional vectors remain retained. This24-source workload cannot establish
populated production planner performance or long-running client capacity.

## Reproduce safely

Use an owned disposable PostgreSQL17 cluster on port55460 with pgvector available,
the measured revision and the project's frozen environment. The script refuses
port5432 and invalid repeat counts. The command creates/removes only its owned
synthetic database:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE \
  PGPORT=55460 TMPDIR=/dev/shm/agentic-rag-issue61-20261030/test-artifacts \
  .venv/bin/python scripts/measure_provider_indexes.py \
  --output /owned/evidence/issue61.json --repeats 3
```

The output records exact revisions, environment, adapter counts and manifests.
Do not interpret an invalid/drifted run as evidence. An initial run after adding
the lifecycle probe correctly failed its fixture-topic assertion; the measured
commit adds explicit handling of that one fixed public probe. Arbitrary unknown
fixture input is still rejected.

## Existing-install and integration evidence

All commands below unset inherited PostgreSQL host/service overrides, select an
owned test port, and use the same tmpfs artifact directory. The local and central
upgrade fixtures begin at populated026, use strict backup/restore, compare
original row hashes and ACLs, retain document IDs/queued work and exercise retry.
They reuse the existing PB061-DEV verifier rather than excluding old rows or
inventing a new preservation exception.

| Command after `.venv/bin/python -m pytest -q` | Actual result |
|---|---|
| `tests/service/test_provider_schema.py tests/service/test_provider_upgrade.py tests/service/test_upgrade.py tests/service/test_tracing_upgrade.py` | 26 passed,68.32s, exit0; one upstream Starlette deprecation warning |
| `tests/test_provider_indexes.py tests/test_provider_search.py tests/test_provider_cli.py tests/test_providers.py` | 94 passed,61.92s, exit0 |
| `tests/test_provider_search.py` after same-dimension ranking assertions | 6 passed,4.39s, exit0 |
| `tests/test_provider_search.py` after research-egress characterization | 7 passed,3.31s, exit0 |
| `tests/test_docs_continuity.py` after disclosure/contract corrections | 17 passed,1.14s, exit0 |
| `tests/test_provider_integration.py` independent coordinator rerun | 1 passed,5.65s, exit0 |
| `tests/service/test_provider_receipts.py tests/service/test_provider_worker.py tests/service/test_source_worker.py tests/service/test_tracing.py` | 24 passed,31.35s, exit0; one upstream warning |
| `tests/benchmark/test_corrections.py` | 49 passed,11.31s, exit0 |

The architecture-derived success path uses audited save→actual adapter with
MockTransport→SQL generation→scoped search/dedup. Same-dimension and different-
dimension tests assert ranking changes only on explicit selection, including
cutover during an in-flight query. Managed reads never call legacy embeddings
or the untagged query cache. Contextual full-text recall remains source-checked.

The derived recovery path crosses actual CLI/TOML/connection boundaries:
committed batch→provider503→resume→A/B cutover→new audited save→stale rollback
refusal→catch-up→rollback. It compares complete table hashes and sequence states
on failure, preserves original IDs/evidence/audits and proves the new source is
searchable after rollback. It injects an HTTP failure between committed commands,
not an OS kill.

The added research characterization uses the actual selected provider/SQL/search
path with MockTransport at an external-shaped destination. With structured
assessment disabled, automatic retrieval still embeds queries; `provider_calls=0`
counts assessment only. Lexical research without assessment makes zero provider
requests. This makes the documented opt-in generation's privacy effect explicit.

## Review and final verification

Independent architecture review found two Medium issues: HTTP source receipts
lost classified provider failures, and the no-mixing guarantee needed an explicit
managed/new-binary scope. Actual HTTP401/429/503 source→worker→receipt/trace
regressions failed before the classification fix and pass afterward. Legacy
historical vectors remain explicitly unverified. An additional empty-store
regression first accepted wrong-dimension/unsupported providers; selection now
checks one fixed synthetic embedding even with zero stored chunks.

PB061-OPS has an independent content review of its commands, upgrade source,
capability/egress bounds and recovery branches. The separate executed CLI and
populated upgrade tests above provide rehearsal evidence. Independent complete
bounded review covered all53 changed files plus the measurement/publication
supplements, inspected the actual success/recovery tests and recomputed192 query
assertions,691 request counts and153 unchanged runtime/SQL/script hashes.
It reports no open Critical/High/Medium/Low findings, conditional on the actual
full-suite gate. Corrected documentation findings remain tracked as
[LOW-018](https://github.com/phense/agentic-rag/issues/75#issuecomment-6524729830).
The [first complete suite](issue61-full-first.txt) finished with 1 failed,
1696 passed,1 expected macOS skip and1 upstream Starlette warning in1415.15s,
exit1. Runtime/test/SQL/dependency
hashes were unchanged throughout. The only failure was an older documentation
selector requiring the obsolete universal local-embedding sentence. Its repair
retains all existing privacy/pin/secret assertions and adds explicit HTTP/query/
corpus/probe/research disclosure guards. A focused independent recheck also
found and corrected stale universal local-/CLI-only prose across current
introductions; historical release documents remain unchanged. The actual
updated documentation tests and fresh complete-suite gate are recorded below.
The failed first run is not represented as a pass. Its raw-log
SHA256 is `0ffdeff94b0962c79c1e83d65909e72057dce48763e54db7c40b987f7b73947e`.
Independent focused recheck through078ad29 confirms the Medium disclosure fix
and retains all22 original privacy assertions. The selector correction remains
tracked separately as [LOW-019](https://github.com/phense/agentic-rag/issues/75#issuecomment-6525128808).

The fresh [complete-suite output](issue61-full-final.txt) on
`078ad290ce5decf16c431a3c470291af66fb43b6` is **1700 passed,1 skipped,1 warning
in1245.42s, exit0**. The skip is the macOS-only launchd installer test on Linux;
the warning is the upstream Starlette TestClient/httpx deprecation. Neither
test budgets nor runtime guards were relaxed. Command:

```sh
env -u PGHOST -u PGHOSTADDR -u PGSERVICE -u PGSERVICEFILE \
  PGPORT=55461 TMPDIR=/dev/shm/agentic-rag-issue61-20261030/test-artifacts \
  LD_LIBRARY_PATH=/home/administrator/Claude/.scratch/agentic-rag-issue59-20261030/browser-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python -m pytest -q --tb=short
```

The library path supplies this host's isolated Chromium runtime dependencies.
All304 runtime/test/SQL/dependency file hashes stayed identical before/after;
the canonical sorted JSON manifest SHA256 is
`9085448e8b1f1913226dd013a3604dc1d42fbfa0da233f851e115b8bf8b84cd1`.
The raw final log SHA256 is
`c91cb121cb1f36cd697feef475a7a171243c207429861b8ea89a81a5a5697e4e`.
All153 measured runtime/SQL/script hashes also still match the clean measured
e6cf92b revision; later fixes change documentation and characterization tests.

Offline `uv lock --check --offline` and `uv build --offline --wheel` passed.
The wheel contains exact current provider/index modules and SQL027, with the
direct JSON-schema dependency in its metadata. Relative links and Pandoc HTML
rendering pass; a local Chromium check renders the tables without horizontal
overflow. Final acceptance maps AC001–009 to source preservation, as-built
authority/locking, independently derived success/recovery, operator rehearsal,
resolved review findings and this unchanged-source full-suite exit.
PR publication/maintainer merge remain separate workflow actions.

No live hosted credentials, real-model quality, production migration, fleet
upgrade, service restart, cross-host TLS or target-hardware capacity is proven.
Old binaries continue reading the legacy index; coordinate reader upgrades for
consistent managed selection. Managed coverage after new writes requires an
explicit bounded catch-up. Approximate retrieval above 4096 eligible vectors has
no global exact-recall guarantee. These boundaries remain operational decisions,
not implied deployment approval.
