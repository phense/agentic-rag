# Change Design: Measured local reranker configurations

## Context

`neural_rerank.py` checks the literal loopback origin and model alias before
scoring. `search.py` filters source/time/scope/identifiers before the callback;
`retrieval.rerank` accepts only a complete permutation and restores original
payloads. Existing default bounds are12 passages,1200 characters,512 query
characters,1.5 seconds and two nonqueued in-flight operations per process.

## Interface contracts

| Boundary | Preserved contract | Delta | Failure |
|---|---|---|---|
| Config → ordering | Existing URL/defaults | Fixed legacy-v1/focused-v1 policy; local model alias and pinned revision; optional diagnostics | Reject invalid finite settings before inference |
| Ordering → search | Same original hit permutation | Optional caller-owned diagnostic dictionary | Fixed safe outcome; original order on rejected result |
| Search → existing clients | Same hits/warnings tuple | Operator-opt-in diagnostic warning | No new required wire field or client version |
| Evaluation → ordering | Public synthetic inputs only | Dev-selected sealed configuration then held-out paired observations | Failed calls stay in denominators; drift invalidates run |

## Decisions

- Legacy-v1 exactly retains the existing selection and12×1200 limits. Focused-v1
  tests a smaller6×600 context with the same query/deadline/concurrency bounds;
  it reduces work rather than introducing an unmeasured larger model. Add a preregistered focused Jina tiny33M Q8 local challenger because
  the actual four-CPU smoke takes about4seconds for Qwen, beyond the1.5s budget.
  The Jina model is English-trained; bilingual regressions remain visible. Both use
  the same stable-score sort. Candidate choice is explicit, never auto-adopted.
- Configured alias/revision is a local operator assertion. Discovery can verify
  alias consistency, not remote weights. The lab verifies the pinned639153184-byte
  GGUF SHA256 and records executable/version and process constraints separately.
- Public fixtures reuse two original development families from#35 with exact
  prior failed query IDs/report SHA256 and freeze fresh baseline reproductions.
  New representative held-out families use invented source text; they are not
  private exports or newly confirmed real failures.
  Development and held-out families use different subjects/source identities.
  Reused synthetic templates limit generalization and must be disclosed.
- Evaluate actual ordinary auto search with dead isolated embedding origin and
  real local reranking. This measures ordering of lexical candidates, not embedding
  quality. Use audited writes in marker-owned random PostgreSQL databases only.
- Pre-register both configurations. Development selection prefers a challenger
  only with no per-case nDCG/recall regression, no additional failures and at least
  10% lower median stage/search latency. Seal choice before held-out calls.
  Held-out reports may compare both preregistered configurations, but cannot retune.
- Each unique query contributes once to quality; repeated calls are timing only.
  Precision counts actual returned sources, recall counts expected identities;
  nDCG uses binary fixture relevance. Empty retrieval is reported separately from
  answer abstention; no language-model answer quality claim is made.
- New-process runtime startup/first request and repeated warm requests are distinct.
  Run owned PG, model runtimes and evaluator/children together in an effective
  cgroup with verified process affinity0-3, quota400%, MemoryMax8GiB and MemorySwapMax0. Record
  membership, peak memory, CPU/throttling/OOM counters and actual shared host;
  this constrained service envelope is not a dedicated VM or fleet-capacity proof.

## Dependencies and tests

No new dependency or SQL. Test-first configuration bounds/model selection/
diagnostics and sealed-corpus validation/metrics. Existing malformed/deadline/
concurrency/neural-scope tests remain authoritative. Add real PostgreSQL central
and local integration with source withdrawal, identical citations and rollback.
Run `.venv/bin/python -m pytest -q` to actual completion and inspect exit artifact.

## Risks and rollback

Passage truncation can miss useful evidence; the report preserves those misses.
Model aliases are not weight attestation. Diagnostics are opt-in and fixed-schema.
An unsupported runtime, short query or timeout retains prior ordering. No policy
is globally enabled from a benchmark score. Code/config rollback retains all data.

## Playbook obligations

PB062-OPS is the only required system playbook; see proposal. Development:
reuse the marker-owned benchmark database lifecycle and prior isolated PG cluster
procedure. All destructive/recovery work remains synthetic and owner-checked;
no production cutover or multi-actor development operation is required. Record
actual startup/stop ownership and rerun limits before model measurements.

## Primary model references and lab gate

Jina tiny is an explicit local challenger, not a multilingual capability claim.
[Original model card](https://huggingface.co/jinaai/jina-reranker-v1-tiny-en),
[GGUF conversion](https://huggingface.co/gpustack/jina-reranker-v1-tiny-en-GGUF/tree/34fdafe5a08b64246bcbfdbf0b8a23f818baf8e3),
Q8 file SHA256 `0defc1f8a1f4dd22183124a2a25a97765603e5a9e42258046c9b2c8a26d1f553`,
36676960bytes. Metadata and checksum are verified before native loading; no remote
model code executes. Both actual model probes/results and rejected attempts remain
part of measurement evidence. Freeze the three-model/config grid before held-out
outputs. No live/default selection follows from the winner.
