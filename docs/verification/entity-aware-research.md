---
id: RAG-069-VERIFICATION
title: Entity-aware research verification
type: reference
doc_id: standalone
readers: [repository-maintainers]
depends_on: []
assets: []
last_reviewed: unreviewed
summary: Original-evidence coverage, limits and compatibility evidence for Issue69.
audience: repository maintainers
version: 0.6.24
last_verified: 2026-11-02
status: implementation verified; independent review and full suite pending
---

# Entity-aware research verification

The Issue69 extension reaches original passages through confirmed entity aliases
and a bounded graph frontier. It preserves the existing citation, source-quorum,
authority and local-abstention rules. The operating procedure is
[PB-5.6](../bounded-research.md); the acceptance contract is the
[RAG-069 specification](../specs/RAG-069-entity-aware-research/spec.md).

## Revisions and reproducibility

The baseline is0.6.23 at `c33e11fd5ccc4fa1e11c92fbcd16e9fee0cbdcd9`.
Its research engine is preserved byte-for-byte in
`tests/fixtures/research69/research-0.6.23.py.txt` (SHA256
`4c72d9b173629f6596830202c443e7a4806517c1f42f837c5883796937ffc1f6`).
The candidate is the0.6.24 research implementation in this change. Measurement
input hashes, command, exit status and log hash are retained in the ignored
RAG-069 run directory; the public synthetic measurements are
[results.json](../benchmarks/2026-11-02-entity-research/results.json), SHA256
`18b6c9a77ac40caa53da778a86ae358621b2ce2765ae35cae5f79a29f3907e3b`.

Run from the candidate checkout against a disposable test installation:

```sh
PGPORT=55460 PGUSER=administrator .venv/bin/python -m pytest -q \
  tests/test_research_exploration.py tests/test_research.py \
  tests/benchmark/test_entity_research_comparison.py \
  tests/service/test_research_exploration_upgrade.py \
  tests/test_entities.py tests/test_graph.py \
  tests/service/test_api.py::test_scoped_research_subprocess_and_audited_write \
  tests/service/test_upgrade.py::test_current_release_is_supported_for_operator_backups \
  tests/test_docs_continuity.py
```

Observed: **154 passed**, one existing Starlette deprecation warning, exit0,
83.43s pytest time (85.12s including runner overhead). All392 recorded Python/SQL
inputs were unchanged during the run. This is focused verification, not a full
suite result. No production store or inference provider was used.

## Held-out comparison

Five synthetic families use names and facts different from the implementation
regressions: single-hop, three-hop, confirmed alias, ambiguous alias and conflicting
originals. Each engine runs each family three times in alternating order. Retrieval
uses real lexical SQL and audited fixture gateways. An independent original-span
oracle verifies every retained citation; qualifying source counts are checked
against the original source bindings. No structured provider or embedding call runs.

| Measure |0.6.23 baseline |0.6.24 candidate |
|---|---:|---:|
| Runs |15 |15 |
| Relevant originals retained / expected |9/15 |15/15 |
| Unsupported supported statements |0 |0 |
| Original-span errors |0 |0 |
| Serial engine p50 |0.0698s |0.1337s |
| Serial engine p95, nearest rank |0.1003s |0.1713s |
| Total Python process CPU |0.1959s |0.4450s |

Candidate work reaches at most48 metered SQL statements and5 logical calls in
this corpus. The shared test-process peak RSS is90,804KiB; it is cumulative across
both engines and cannot establish an incremental memory cost. Process CPU/RSS
exclude PostgreSQL and worker startup. These serial engine times do not measure
CLI/API end-to-end latency or a multi-client workload. The extension adds work;
it makes no throughput or general model-quality improvement claim.

Three inspected examples from the recorded originals:

| Question family | Before | After and original passage |
|---|---|---|
| Single-hop LyraBeacon | Relevant original3/3 | Preserved3/3: `LyraBeacon final resolution replaces the socket.` |
| Multi-hop VelaBeacon | Final original0/3 | Final original3/3 after three eligible edges: `VelaBeacon final resolution replaces the socket.` |
| Confirmed alias lyra-retired | Original fact0/3 | Original fact3/3: `# lyra: port` followed by `8766`; alias provenance remains separate from fact support. |

The ambiguous alias is never expanded and conflicting originals do not produce a
resolved answer in either engine. Local mode always abstains semantically, including
the successful alias lookup: locating a passage is not evidence that it answers the
question. Two distinct source keys establish the engine's literal quorum, not
independent human authorship. This small synthetic corpus supports the stated
retrieval differences only; it is not a production or live-provider evaluation.

## Authority, limits and failure behavior

The focused checks exercise a real reader subprocess and central API authority,
hidden domain/project/source bridges, cycles, fourth-hop exclusion, degree overflow,
ambiguous confirmed aliases, SQL-work exhaustion, shorter caller timeouts and safe
optional-component failure. Retained spans are rehydrated from eligible originals.
Route-only passages cannot supply literal facet support. Existing tests cover
CLI/MCP contracts, provider opt-in, cancellation and process cleanup.

The first four regression tests were committed before runtime changes. Two initial
fixture assumptions were wrong (lexical UUID lookup and an absent domain), and a
later ambiguous-alias fixture attempted an assertion the gateway correctly sent to
review. Those fixtures were corrected without weakening the expected behavior.
The corrected four cases fail against the archived baseline and pass on the
candidate. An earlier dynamic-import attempt and a misspelled pytest node selector
are retained as invalid runs and do not count as test passes.

## Populated adoption and recovery

`test_research_exploration_upgrade.py` archives the genuine0.6.23 executable and
creates an owned multi-domain schema035 store through its gateways: original
claims, confirmed alias, assertion, pin and pending mining job. A source-version
backup is independently restored before the candidate reads the store. Candidate
alias research returns the original fact, excludes the foreign scope and makes
zero provider calls. Complete table inventories remain unchanged. The old reader
then produces its original result against the same store. A0.6.24 target backup
is independently restored and its inventory verified as well.

No migration, configuration change, write-side change or new dependency is required.
Already running processes retain their loaded code until restarted or reconnected;
code rollback selects0.6.23 and needs no data rewrite. This rehearsal does not
constitute production adoption or permission to interrupt active clients.

## Delivery gates

The complete independent review, architect-derived success/recovery probes, final
full Python suite and package/lock checks remain pending at this writing. This
record does not close Issue68/92 or relax their physical performance gate. Issue69
is ready for merge approval only after its own remaining gates have passed.
