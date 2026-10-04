# Confirmed-failure evaluation

A plausible search result may not answer a question. This benchmark separates the
candidate list, the original evidence that fits the context budget, and the exact
supported value returned by an extractive answerer. Every expected source and failed
case remains in the report. These metrics do not establish general language-model
answer accuracy.

`rag benchmark optimize` compares four finite offline profiles: ordinary hybrid search
or exact entity/attribute routing, each with title-overlap weight0 or1. Both routes use
the same original-source answer checks. Entity routing requires literal caller selectors;
labels never enter retrieval. Existing scope/domain/time/claim eligibility stays in force.
The public comparison requires exact-boundary originals: a project query whose corpus
contains visible global/ancestor sources is rejected before services. Evaluate those
sources with separate literal global/ancestor queries; production search visibility is unchanged.
The command selects on development cases, seals candidate.json, then evaluates held-out
cases. It does not load the candidate into live retrieval or modify configuration.

The public failure corpus has204 sources and96 queries, split into six independent
families on each side. Families retain translations, aliases, history and related sources.
Copied evidence and family/source identity leakage are rejected before storage or provider
access. Development runs once per profile; held-out timing repetitions do not increase the
truth denominator. Reports show family uncertainty or null when there are too few families,
misses, original citations, indexing/vector coverage, latency, context and token estimates.

All indexing uses existing audited gateways in randomly owned local databases. Public
embedding comparisons require the existing local model's exact observed digest, endpoint
hash, tag and dimension. Identity guards reject drift throughout indexing/evaluation;
query timers exclude the guard requests. Database/Ollama/OS caches are retained. These
are controlled measurements, not a claim of cold-service or production workload gains.

## Confirmed correction labels

`rag benchmark export-corrections` reads one exact project/domain or explicit global scope
in a consistent read-only snapshot. A label requires an accepted current replacement,
stated/confirmed claim and its original complete reviewed active user span retained in
assertion_sources. Assistant suggestions, unrelated later attachments, expired/withdrawn
support, ambiguous or over-bound histories cannot create truth. A later unsupported
replacement cannot revive an earlier value. A zero-case export is valid.

Exports retain source/content/row versions and correction history. Secret-bearing or
already redacted labels are withheld. The distinct private format stays in new0600 files
under0700 directories outside every repository/worktree. It cannot enter the public
optimizer or native model stage. Local evaluation uses reader privileges and no embedding,
reranker or language-model calls; it rechecks original support and counts changed/withdrawn
sources as misses. Private details remain private, and the CLI prints aggregate counts. When independent dev/test families exist, local FTS/entity profiles select on dev and seal a private candidate before held-out evaluation; otherwise optimization is explicitly unavailable.

## Public mining prompt comparison

`rag benchmark optimize-mining --mine-model` explicitly compares the unchanged mining
prompt with one static correction prefix using the existing configured native provider.
Only built-in public transcripts are accepted; each candidate gets a fresh owned database
and session. Two development families choose the prompt before two independent held-out
families are measured. Each transcript contrasts an explicit user correction with an
assistant suggestion and a hypothetical user statement. All source-role, exact quote,
time and accepted-batch grounding gates remain authoritative.

The command seals its public development candidate before held-out calls. Prompt bytes,
application sources and local embedding identity are frozen and checked. Replay of an
accepted extraction must avoid the model and preserve its original JSON result/documents,
even if the comparison prefix changes. Provider failures remain misses. The maximum is
eight native calls; billing/token costs are unavailable, so prompt characters and resulting
chunks are reported. Two families cannot support a statistical prompt-gain claim.

Original `benchmark run`/`compare`, CLI/MCP privileges, hooks, jobs, provider configuration
and client adapters retain their existing behavior. Feature10 adds no SQL migration.
Source019 code-only adoption/recovery and combined live018→019 are rehearsed on owned
copies. See [PB-5.10](playbooks/failure-evaluation.md) and [verification](verification/failure-evaluation.md).
