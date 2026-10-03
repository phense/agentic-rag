# Feature 4: Contextual indexing evidence

Source baseline: `499c656d7fcb1cf1d1938f7d2404b4043d9fb0b0` (actual old SQL/store/search). Candidate base is the same Git commit; exact measured candidate app/SQL/script bytes are identified by SHA256 in [results.json](results.json) and committed in the Feature 4 PR. Model: `bge-m3`,1024 dimensions, digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`; existing local Ollama. No hosted inference.

## Three practical comparisons

These are three authored synthetic cases on an owned representative database, with original fact labels in `scripts/verify_contextual_indexing.py`. Each has20 alternating paired repetitions per route, plus a separately reported first call. Both paths have k3 and at most1200 original-source characters (400 per hit). Grounded prefixes affect indexing only and are never substituted into evidence. Reranking/query cache are off to attribute the change. The model was already warm after ingestion; first-call numbers are not cold-model startup measurements.

| Practical case | Original fact in budget, before→after | Auto p50 ms | Auto p95 ms | Mean source characters |
| --- | --- | --- | --- | --- |
| Service/port whose subject is in the earlier title | 0/20→20/20 | 168.498→172.957 | 173.53→189.562 | 549→908 |
| 2025 revenue of 184.2 USD millions | 0/20→20/20 | 162.749→169.285 | 171.656→182.112 | 602→938 |
| Checkpoint restore in a later recovery section | 0/20→20/20 | 163.079→175.752 | 179.424→184.633 | 200→875 |

The previous path returned introductory/background chunks and/or the labeled older distractor; the new path also returns the current original fact within the same maximum budget. All result spans and citation identities were resolved against stored original chunks. The dated numerical label requires the exact original sentence containing both2025 and USD millions. This measures evidence availability, not generated-answer correctness or guaranteed top1 ordering.

## Lexical fallback and indexing cost

| Case | Lexical fact coverage | Lexical p50 ms | Added context indexing ms | Chunks/bounded calls |
| --- | --- | --- | --- | --- |
| service-port | 0/20→20/20 | 9.272→12.114 | 656.974 | 3/3 |
| dated-unit | 0/20→20/20 | 9.588→12.467 | 766.618 | 3/3 |
| late-section | 0/20→20/20 | 9.418→12.198 | 1095.784 | 5/5 |

Context vectors are additional indexing cost, separate from ordinary original-vector ingestion (baseline save durations are in JSON). Index elapsed includes the final idempotent no-op check, connection open and CLI handling, with batch limit1. It is not model throughput. Normal new saves/queued retries add lexical context without an extra embedding request; stored contextual vectors require explicit bounded maintenance. No general speedup is claimed.

## Existing-installation and recovery evidence

The actual014 installation contains11 documents/21 chunks, two writer identities/projects/domains, a pin/checkpoint, queued work, edges, replaced/expired assertions, source-managed claims and a populated project profile. All15 canonical tables are fingerprinted (excluding only schema migration metadata, laboratory ownership and the new derived table). Migration preserves every canonical row; indexing changes only derived rows and appended audits. The old audit subset is independently fingerprinted.

The strict operator backup helper uses a read-only exported snapshot shared by dump/inventory, requires restore exit0 into an empty owned target, compares every public row including migration metadata and application table privileges, and verifies cleanup. The existing maintenance verifier remains a coarse smoke check and cannot satisfy the upgrade backup gate.

The executable rehearsal covers transactional migration interruption/retry/idempotence; new code/save on014; bounded CLI continuation; read-only MCP source retrieval; concurrent actual old/new readers; an actual old writer correction after partial context indexing; source/scope refresh; retained old-reader/code rollback; source014 backup restoration into another owned database and reupgrade. Cleanup checks ownership markers.

An attempted in-place014 restore over015 failed on the new chunk FK. The supported recovery restores to a separate target, preserving the upgraded database. Snapshot recovery cannot recover later writes. See [PB-5.4](../../contextual-indexing.md) and [review/rehearsal record](../../verification/contextual-indexing.md).

## Trading read-only compatibility

The live schema014 store had 10432 documents/11822 chunks. A `rag_reader` repeatable-read transaction compared three routes,20 pairs each. Original citation lists were equal20/20 per route; no production writes or schema changes occurred. This validates missing015 fallback, not production contextual-index performance.

| Route | Equal citation lists | p50 before→after ms | Validated citations before/after |
| --- | --- | --- | --- |
| eligible-document | 20/20 | 7.146→7.048 | 20/20 |
| scoped-lexical | 20/20 | 10.022→9.537 | 0/0 |
| scoped-question | 20/20 | 364.881→364.436 | 160/160 |

The scoped lexical control returns no results on either route; its equality is an empty-result control, not positive source coverage. Numerical differences at this scale are noise, not speedup evidence. Public output includes only aggregates/timings, no live query labels/content/citations. [Raw aggregate live results](trading-reader.json).

## Reproduce and limits

```sh
PYTHONPATH="$PWD" /absolute/path/to/agentic-rag/.venv/bin/python scripts/verify_contextual_indexing.py --output /private/results.json --repeats 20
PYTHONPATH="$PWD" /absolute/path/to/agentic-rag/.venv/bin/python scripts/verify_contextual_indexing.py --trading-readonly --project /absolute/Trading --output /private/trading-reader.json --repeats 20
/absolute/path/to/agentic-rag/.venv/bin/python -m pytest -q
node --test tests/test_opencode_plugin.mjs
```

Full suite: 960 Python tests, 36.85s; Node7 tests. Independent review resolves six blocking findings across code and upgrade guidance; final review is recorded separately. PostgreSQL fixtures use the test database; destructive rehearsals use owned random database names only.

Three questions remain three questions despite repeated timings. No held-out answer evaluation, full Trading-scale derived backfill, cold-model timing, production migration-duration guarantee or production rollout is claimed. Full-body source hashing and contextual ANN/fusion can cost more on large documents/corpora; the original representation remains available for comparison and rollback. The existing benchmark runner explicitly retains context-off for prior experiments; this dedicated script measures Feature 4.
