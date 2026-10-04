# Public confirmed-failure evaluation

Candidate `7852bb74b8597c65dc823f86a3a8ed8bdbc030966ae0b5e67f2e5ed4be527c2b`; source `5b390692e32e07c8816e98091dfa66e15e0c2cb3`.

Selection uses development labels only. Held-out repetitions measure timing; truth denominators count queries and independent families.

| Held-out profile | Extractive correct/queries | Evidence recall | p50/p95 ms | Wrong scope |
| --- | ---: | ---: | ---: | ---: |
| search-title-0 | 30/48 | 0.6666666666666666 | 223.982/246.363 | 0 |
| entity-title-0 | 48/48 | 1.0 | 44.0895/53.179 | 0 |

These are exact supported extractive results, not general semantic answer accuracy. General model accuracy is null.

Fresh owned split databases; retained PostgreSQL/Ollama/OS caches; repeated queries in one process. First call included, not cold-service measurements. Query timings exclude model-identity checks; indexing timings include those checks.

All misses, errors, original citations, raw repeated times, index coverage and family uncertainty are in results.json. No artifact changes live policy.
