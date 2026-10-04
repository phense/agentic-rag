# Evaluation artifact contract: RAG-5.10

The public optimizer compares ordinary hybrid search with a bounded routing and
ranking candidate. Both use the same application revision, source inputs and
context budget. This is a comparison of existing tool routes, not a comparison
with an invented historical answerer. Original CLI/MCP defaults do not load candidates.

## Inputs and selection

`optimization.run(cfg, output=Path(...), corpus_path=None, context_chars=4000,
repeats=20, progress=None, mining_candidate=None)` accepts only a validated public
synthetic failure corpus. Context is1000–12000 characters; repetitions are1–30.
The corpus has at most256 documents and256 questions. Development and held-out
queries, original source identities, source families, translations, copied source
text and correction histories cannot cross splits. Queries require an explicit
domain, exact synthetic project or global scope, and an explicit timestamp.
Entity and attribute selectors must be supplied together.

Four static profiles combine ordinary search or caller-selected entity resolution
with title weight0 or1. The local ranker only permutes existing candidates. It
cannot create citations, change selection boundaries or consume answer labels.
Entity resolution uses the supplied entity/attribute only. Ordinary search keeps
actual irrelevant candidates visible when no answer is supported. Both routes use
the same answerer: exact accepted values retained in original eligible chunk text
and complete reviewed active user evidence. No first-hit answer heuristic is added.

Development evaluates each profile once in a marker-owned database. Selection
orders boundary/stale safety, exact extractive correctness and evidence recall,
then uses a deterministic simplicity tie-break. Timing noise does not select a
profile. The chosen artifact is serialized and hashed before any held-out query
is evaluated. Held-out sources use a separate owned database. Baseline/candidate
timing order alternates, with identical selectors, maximum10 originals and budget.

## Files and denominators

The output must be a new directory without symlink ancestors. Files are created
exclusively; a retry uses a new output directory and cannot overwrite a sealed run.

| Artifact | Contents |
| --- | --- |
| `candidate.json` | Chosen profile, bounded grid, source/corpus/dev hashes, dev evidence hash, budget and optional public dev-only mining selection metadata |
| `dev-results.json` | Every profile, development outcome, miss and indexing failure |
| `heldout-results.json` | Frozen baseline/candidate outcomes, original citations, all repeated timings and indexing coverage |
| `results.json` | Combined reports, source attribution, CLI summaries and explicit failure counts |
| `report.md` | Compact held-out comparison and measurement limits |

Each question contributes one quality observation, regardless of timing repeats.
Every unsupported extra extracted value makes answer correctness fail. An answer
must match an independently authored value and expected original source identity;
finding an answer string in unrelated context receives no credit. An abstention
after a query/index failure is not a correct negative. Expected source indexing
failures remain quality misses; even irrelevant indexing failures produce a nonzero
CLI failure count. Reports separately expose failed sources and query observations.

Evidence recall uses complete original excerpts that actually fit the returned
context. Raw candidate IDs also remain available, so omitted or irrelevant
candidates are not silently converted into a retrieval gain. Boundary exposure is
checked against actual stored domain/scope. Current/historical selection uses the
original tool's eligibility rules; no optimizer migration or validity policy is added.

Report p50 is the median; p95 is the nearest ranked observation. Context tokens
are `ceil(characters/4)`, explicitly an estimate. Index cost includes elapsed time,
source count, original chunks and missing vectors. Family bootstrap uses fixed
seed73 and1000 family resamples; fewer than five families yields a null interval.
Translations and repeated timings never enlarge the independent-family count.

## Model and recovery limits

`general_model_accuracy` remains null. Exact supported extractive correctness is
not general semantic answer quality. Local embedding inference is real for normal
public runs; PostgreSQL/Ollama/OS caches remain retained. The first query call is
included, and the process remains alive for subsequent repetitions. These are not
cold-service measurements or production ingestion gains.

The configured local model's endpoint hash, tag, dimension and observed immutable
digest are frozen before database creation and recorded in the candidate/report.
Unknown identity aborts before service workload setup. Identity is rechecked before
and after each indexed document and query observation, before sealing and at run
completion. A mismatch or unavailable identity invalidates the comparison; it is
not a successful abstention or ordinary query miss. Query timings exclude identity
checks; indexing timings include them. Endpoint strings and credentials are not
included in public identity metadata.

Optional mining metadata must be a bounded public development-only selection with
exact source/prompt hashes, declared development families and at most8 profiles.
Held-out results or test labels cannot enter the candidate. Its native-provider
calls belong to a separate explicitly invoked public mining stage; optimizer call
counts describe the optimizer itself. Deterministic replay alone cannot establish
prompt effectiveness.

Normal failures close owned connections and verify marker-owned database cleanup.
A process death can leave a marker-owned database for inspection; it does not
authorize cleanup of any unowned database. An interrupted file run remains partial;
rerun in a new output directory. Source/candidate hash drift prevents a final
accepted report. Database/provider integration and public measurements are executed
by the coordinating task; the S02 worker executes only pure no-service tests.
