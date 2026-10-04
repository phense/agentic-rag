# Incremental ingestion:20 paired public measurements

Baseline `1294d6c44fd02b66715692f12791bfa2fd4c8856` (018); measured candidate `88c1c36f2fe6f3145d290a6de141e65914acc403` (019). Local `bge-m3`, immutable digest `7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`. Actual embedding HTTP inputs are counted independently of application diagnostics.

| Scenario | Baseline p50/p95 ms | Candidate p50/p95 ms | HTTP inputs, before→after (20 pairs) | Whole child peak RSS MiB, before→after |
| --- | ---: | ---: | ---: | ---: |
| small-edit | 845.923/854.848 | 311.768/316.917 | 240→20 | 83.281→81.906 |
| interrupted-retry | 1299.945/1311.802 | 100.007/103.544 | 160→0 | 79.75→79.922 |
| independent-backlog | 19240.824/19959.255 | 15851.89/16074.981 | 1920→1920 | 82.031→83.625 |

## Inputs, outcomes and measurement limits

Each pair uses identical before/after inputs. Twenty distinct fixture variants prevent accidental cross-pair cache hits; route order alternates. Each observation starts a fresh child process. PostgreSQL, Ollama and OS caches remain retained; these are not cold-service or process-warm measurements. p50 is the median and p95 the nearest ranked observation. Raw observations and all quality denominators are in [results.json](results.json).

The small edit changes1 of12 exact chunk inputs. Both routes validate all12 ordered original chunks, finite1024-dimensional vectors and scope in every pair:240/240 chunks per route, zero missing vectors/foreign scope. Initial12-input ingestion is outside the edit timer. Canonical saves still regenerate chunk IDs.

The interrupted retry begins after a real process death following accepted application commit and before queue acknowledgement. Both routes retain8/8 documents, one applied batch, no re-extraction/duplicate application and the exact completed EOF cursor. The timed workload additionally invokes8 explicit auxiliary reembeddings. The160→0 input reduction belongs to those auxiliary reembeddings; worker replay itself already avoids embedding. A separate real process death during uncommitted application verifies retained extraction, zero visible partial documents and complete8-document recovery.

The backlog contains3 independent jobs and24 final documents per pair. Both routes embed96 inputs per pair (72 canonical raw chunk inputs plus24 unchanged dedup representations). Ordered job claims, all480 documents and1440 canonical chunks per route are checked; zero missing vectors or wrong scope. Real extractor inference is replaced by a controlled fixture; HTTP embeddings are real. Candidate peak simultaneous requests is2 versus1. No speculative queue claims occur.

| Backlog statistic | Baseline | Candidate |
| --- | ---: | ---: |
| Median documents/s | 1.248 | 1.514 |
| Queue delay p50 ms (60 claims/route) | 6400.280 | 5313.037 |
| Queue delay p95 ms (60 claims/route) | 13203.871 | 10689.178 |

Peak RSS includes interpreter/client startup in the entire fresh child, and excludes PostgreSQL/Ollama server memory. Timers exclude child startup and post-run content/vector oracles. Context/canonical representation is unchanged. No general speedup or production ingestion gain is inferred.

## Existing-installation compatibility

The unified driver executed populated018→019 rollback/retry/no-op, strict consistent source/target restores, original row/grant preservation, old/new CLI and fresh10-reader/18-main MCP contracts. Persistent source/candidate writers each held an uncommitted audited transaction before either could commit on018 and019. The guarded operational script performed actual owned Git activation, schema-committed retry and detached source recovery retaining019 and branch references. Eight unsafe activation/recovery conditions were actually rejected.

A fresh private production018 backup was restored with strict row/grant checks on an owned copy, then interrupted019 DDL, retry and no-op were executed there. All original rows and grants survived; canonical application writes and hosted provider calls are0. Private dumps/content stay outside Git. The aggregate original inventory includes10614 documents,12004 chunks,7 domains,22 pins,32 checkpoints,1414 queued rows,1025 batches and39009 audit rows at that snapshot. Normal ongoing production writes may later change those counts.

Trading on live018:3 public lexical queries, first call recorded separately plus20 repetitions each, all480 repeated citations verified against original eligible chunks. No private snippets are published, no providers or application writes. Reader timings measure source controls, not candidate ingestion improvement.

## Reproduce

```bash
PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python scripts/verify_incremental_ingestion.py \
  --output docs/benchmarks/2026-10-04-incremental-ingestion/results.json \
  --private-dir /absolute/private/new-directory --repeats 20 --production-copy --trading
```

