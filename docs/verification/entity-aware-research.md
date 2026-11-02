---
id: RAG-069-VERIFICATION
title: Entity-aware research verification
type: reference
doc_id: standalone
readers: [repository-maintainers]
depends_on: []
assets: []
last_reviewed: 2026-11-02
summary: Original-evidence coverage, limits and compatibility evidence for Issue69.
audience: repository maintainers
version: 0.6.24
last_verified: 2026-11-02
status: verified; specific PR merge approval pending
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
`c24fda2f289a89bfdd00eebc52d7239aa14ce3b75277d9e3eb28def02dc3375b`.
This corrected measurement records candidate revision `1036e1041b242ebf14a996616994a261680fa321`,
all392 Python/SQL input hashes before execution, and an unchanged-input check
afterwards. The source aggregate is `410ac1003855c9ce964d00a000f4ed4ccce049120730b2683044d1ccc88d9b2c`.
It runs the unchanged benchmark test body directly on its own disposable database;
the full suite was concurrently running on a different database. Serial timings
are observational. The earlier unbound numeric results are superseded.

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

## Final full-suite verification

The complete Python suite passed on `e8169ccb3463752508dad05f63cdb51feea17450`:
**2623 passed,1 skipped,1 known Starlette deprecation warning**, exit0,3061.68s
pytest time (3064.16s including runner overhead). All392 Python/SQL input hashes
are unchanged and match the reviewed runtime. The aggregate equals the measurement
source aggregate above. Later changes only reconcile documentation and evidence.

```sh
LD_LIBRARY_PATH=/path/to/browser-libs/usr/lib/x86_64-linux-gnu \
PGPORT=55460 PGUSER=administrator .venv/bin/python -m pytest -q \
  -p no:cacheprovider --tb=short --durations=20
```

The [verification record](../benchmarks/2026-11-02-entity-research/verification.json)
contains the exact command, times, source aggregate and log SHA256
`d5590b2814a762e50f2afe833d789c514c77958ca6f7d8010ecfb81fdacca933`.
The first interactive full run was externally terminated with143 near its end;
it has no terminal test result and is not counted. The replacement ran in a
persistent user service with a two-hour limit. No product, test or SQL correction
occurred between those runs. The slowest test was the4096-chunk vector boundary
case (471.01s); several vector recall fixture setups required30–61s each.

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
| Serial engine p50 |0.0535s |0.0960s |
| Serial engine p95, nearest rank |0.0770s |0.1698s |
| Total Python process CPU |0.1463s |0.4369s |

Candidate work reaches at most48 metered SQL statements and5 logical calls in
this corpus. The measurement-process peak RSS is505,120KiB; it includes database/fixture
initialization and is cumulative across both engines. It cannot establish an
incremental reader memory cost. Process CPU/RSS
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
Versioned runtime paths require switching/reconnecting the affected process. An
editable in-place replacement affects the next freshly spawned research worker;
avoid replacing it during requests. Code rollback selects0.6.23 and needs no data rewrite. This rehearsal does not
constitute production adoption or permission to interrupt active clients.

## Delivery gates

The complete independent review found C0/H0/M1/L5, with no Important playbook
findings. Its sole Medium was measurement provenance; the corrected source-bound
measurement above resolves it without changing runtime code. Five Low findings
are [follow-up work in Issue75](https://github.com/phense/agentic-rag/issues/75#issuecomment-6580996256). The independent architect exercised alias and
three-hop success, a hidden RLS bridge, source withdrawal/restoration and a
budget-exhaustion retry through the actual reader subprocess. Pure read phases
preserved table hashes. A faulty probe expectation incorrectly disallowed literal
support during semantic abstention; the report explicitly corrects that expectation.
Both playbook Minor findings (editable code adoption and named worker termination
values) are corrected. The final full Python suite, package build,35SQL/3module
wheel parity,7Node tests and lock checks have passed. The AC/IC/as-built evidence
is reconciled with no remaining blocking gap. [PR97](https://github.com/phense/agentic-rag/pull/97)
is ready for specific merge approval. This record does not close Issue68/92, relax
their physical performance gate, or authorize production adoption.
