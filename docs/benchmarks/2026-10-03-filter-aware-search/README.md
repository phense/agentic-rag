# Filter-aware retrieval: measured source coverage and costs

Source: `99514fe012666e67dff02ae2419e05a6c876d1f9`, populated schema015. Candidate: `feature/filter-aware-search`, additive016; exact tested application/SQL SHA256 identities are in the numerical artifacts. These pre-merge measurements use source015; subsequent live adoption is tracked in canonical [Issue30](https://github.com/phense/agentic-rag/issues/30).

[Synthetic raw evidence](results.json), [private Trading-copy aggregates](trading-reader.json), [upgrade and recovery procedure](../../filter-aware-search.md), [verification and review](../../verification/filter-aware-search.md).

## Three practical controlled examples

Each route has20 alternating paired observations after separate first calls. These are repeated timings of fixed cases, not20 independent questions. Audited synthetic fixtures inject deterministic1024-dimensional vectors at the embedding boundary; no provider inference occurs. Query terms do not match FTS, so the compared candidates isolate vector planning. Original-source reader citations are verified separately.

| Practical case | Eligible chunks | Sources before / after / oracle | Vector-chunk recall before → after | SQL p50 before → after | SQL p95 before → after |
| --- | ---: | --- | --- | --- | --- |
| Second source after one crowded document | 439 | 1 / 2 / 2 | 66.7% → 100.0% | 5.268 → 9.722ms | 5.988 → 10.009ms |
| Rare domain, current (expired assertion excluded) | 2 | 2 / 2 / 2 | 100.0% → 100.0% | 4.457 → 7.936ms | 4.770 → 8.104ms |
| Rare domain, as-of (then-valid assertion retained) | 3 | 3 / 3 / 3 | 100.0% → 100.0% | 4.547 → 8.142ms | 4.651 → 8.603ms |

The crowded project improves document coverage from one of two to both sources on every measured call. Exact eligible-set materialization precedes distance/diversity and prevents the old256-chunk limit from dropping the second source. Rare-domain current/as-of results were already correct and remain correct; they demonstrate preservation, not a quality gain. All cases disclose extra SQL cost.

## Does candidate-pool size matter?

A separate4201-chunk scope contains three documents:1500 closer chunks from one source, one second-source chunk, and2700 more distant chunks from a third source. The independent exact oracle selects five chunks under the existing two-per-document cap. Each pool size has20 warm observations after a separate first call; sizes are measured in ascending blocks. This experiment forces the ANN branch with exact_limit1 so that only the pool size changes; production uses exact ordering for small sets. The default PostgreSQL optimizer may choose a sequential distance sort. The feature test independently proves a retained real HNSW index access on4097 chunks using a disclosed forced-plan diagnostic.

| Candidate pool | Sources / oracle | Vector-chunk recall | SQL p50 | SQL p95 |
| ---: | --- | --- | --- | --- |
| 256 | 1 / 3 | 40.0% | 19.090ms | 19.196ms |
| 512 | 1 / 3 | 40.0% | 19.254ms | 20.461ms |
| 1024 | 1 / 3 | 40.0% | 19.677ms | 19.745ms |
| 4096 | 3 / 3 | 100.0% | 20.506ms | 20.718ms |

The tested4096 pool recovers all three sources;256,512 and1024 do not. This calibrates a bounded ceiling for this adversarial case, not a universal optimum. More than4096 closer chunks from one document can still hide another source. There is no infinite widening or corpus-wide exact-vector fallback.

## Representative Trading copy

An exported repeatable-read production snapshot (10448 documents/11838 chunks) was strictly restored into empty owned databases. Every public row and role/table privilege was checked.016 and ANALYZE ran only on the owned copy; both routes then used the same statistics and immutable copied rows. The three complete searches use actual source995 code versus candidate code, identical private query/project/domain/as-of inputs, unchanged local bge-m3, k3 and the same1200-character original-source budget, with query cache and reranker disabled. No production writes, service/config changes or hosted calls occurred.

| Practical control | Eligible raw chunks | End-to-end p50 before → after | End-to-end p95 before → after | Raw / contextual vector recall, both routes | Identical top3 citation lists |
| --- | ---: | --- | --- | --- | --- |
| trading-project | 2926 | 1887.673 → 1904.027ms | 1905.247 → 1924.292ms | 100% / 100% | 20/20 |
| trading-domain | 1155 | 1048.018 → 1055.713ms | 1056.350 → 1065.746ms | 100% / 100% | 20/20 |
| rare-domain-in-project | 627 | 609.576 → 617.352ms | 617.774 → 624.763ms | 100% / 100% | 20/20 |

Each route validates60 original citations per control. These existing Trading cases have no observed recall or answer-quality gain. The small extra latency is a measured cost; no general speedup is claimed. First-call and individual paired observations are retained in JSON; first call does not mean a cold PostgreSQL cache. Local background services were not stopped.

The measured application bytes match the final implementation. A recorded four-line trailing-whitespace correction reconstructs the tested SQL hash exactly; SQL tokens/statements are unchanged. The later verification-script change only corrects an unused synthetic dataset description from three domains to two populated domains; the tested script hash and independently reconstructable metadata-only delta are retained under script_metadata_only_diff. No Trading sample was rewritten.

## Bounds and compatibility

The helper probes at most4097 eligible rows and reuses that materialization for complete exact ordering when the count is at most4096. Larger sets have at most4096 ANN candidates; both paths retain at most2 chunks/document and50 vector candidates. Installed iterative scan capability is discovered; unsupported metadata/GUC policies are simulated on real0.8.4 SQL, not claimed as an actual extension downgrade. New code works on015, old code on016, and016 changes no canonical or derived rows.

Candidate SQL gets at most2s and preserves a tighter existing nonzero timeout. Scan/memory settings restore on success and failure; external cancellation propagates and caller writes remain intact. Pool/scan caps do not bound all eligibility/hash work; scan limits are approximate. Expensive long-source hashes or broad queries may still reach the cancellation budget. Embedding and reranking retain separate existing deadlines.

Two earlier copy runs reached2s: duplicated source checks were removed, and missing post-restore optimizer statistics were addressed with owned-copy ANALYZE before both routes. The final successful measurements and hashes supersede those failed attempts. All owned targets were cleaned up; private verified dumps remain outside the repository.

## Reproduction and checks

From the isolated candidate checkout, using a new private directory per invocation:

```sh
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/adaptive-search /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_filter_aware_search.py --repeats 20 --private-dir /absolute/new/private-synthetic --output /absolute/private-synthetic-report.json
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/adaptive-search /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_filter_aware_search.py --trading-copy --repeats 20 --private-dir /absolute/new/private-trading --output /absolute/private-trading-report.json
PYTHONPATH=/Users/peter/Agents/agentic-rag/.worktrees/adaptive-search /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
```

987 Python tests pass in127.36s;7 Node tests pass in78.60ms. Populated upgrades, interruption/retry/no-op, actual old/new readers and old writer, caller timeout/external-cancel recovery, role boundaries, strict source backup restoration and every protected row/grant fingerprint pass. Independent complete source review and PB-5.5 content review are Ready; final artifact identity acceptance is recorded in the verification document. Merge and production adoption remain separate gates.
