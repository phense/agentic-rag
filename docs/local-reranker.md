---
id: local-neural-reranker
title: Run a local multilingual reranker
type: how-to
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: 0.6.15 / schema027
last_reviewed: 2026-10-30
depends_on: []
assets: []
summary: Deploy an optional pinned loopback model without changing canonical knowledge.
---

# PB062-OPS: Run and recover a measured local reranker

Use this procedure after separately authorizing local model-service adoption.
The implementation uses an existing local HTTP ordering seam. It does not install
or start a model daemon, download weights during search, or change your database.
With no matching runtime, existing clients retain their previous ordering.

## Prerequisites

Keep a tested executable built from llama.cpp b9840 (`8c146a836`), or validate a
replacement independently against the same model and smoke test. The feature lab
used the native executable bundled with Ollama 0.31.1; its package-private location
is not a portable installation contract. Keep the executable and its libraries
outside the production agentic-rag Python environment. Do not upgrade Ollama or
its loaded embedding model as part of this procedure.

The validated model is Qwen3-Reranker-0.6B, quantized Q8_0 by ggml-org, Apache 2.0,
revision `a02f48bb4f057028298c21fa033da2b30d7742d5`. The file is 639,153,184 bytes.
It is a learned query/passage ranker; scores are not answer-confidence values.
See the [original model](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B),
[conversion](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF) and
[versioned runtime API](https://github.com/ggml-org/llama.cpp/blob/8c146a836/tools/server/README.md).

## Download and verify the public weights

1. Set a separate model directory and create it:

   ```sh
   RERANK_MODEL_DIR="$HOME/.cache/agentic-rag/reranker"
   mkdir -p "$RERANK_MODEL_DIR"
   ```

2. Download the exact revision into a staging file:

   ```sh
   curl -fL --retry 2 'https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/resolve/a02f48bb4f057028298c21fa033da2b30d7742d5/qwen3-reranker-0.6b-q8_0.gguf' \
     -o "$RERANK_MODEL_DIR/model.download"
   ```

3. Verify the staging file before activating it:

   ```sh
   shasum -a 256 "$RERANK_MODEL_DIR/model.download"
   ```

   Required SHA-256: `22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48`.
   Stop on mismatch; leave the previous model and retrieval configuration in place.

4. Move the verified file to its local name:

   ```sh
   mv "$RERANK_MODEL_DIR/model.download" "$RERANK_MODEL_DIR/qwen3-reranker-0.6b-q8_0.gguf"
   ```

The public download contains no stored knowledge. Search itself has no download
path and sends no query/source text to Hugging Face or another hosted service.

## Start and check the isolated runtime

1. Set `RERANK_BIN` to your verified executable and check its version:

   ```sh
   "$RERANK_BIN" --version
   ```

2. Launch it on literal loopback, with offline mode and request logging disabled:

   ```sh
   "$RERANK_BIN" --model "$RERANK_MODEL_DIR/qwen3-reranker-0.6b-q8_0.gguf" \
     --host 127.0.0.1 --port 8766 --rerank --pooling rank --ctx-size 4096 \
     --parallel 1 --alias agentic-rag-qwen3-reranker-0.6b-q8 \
     --offline --no-webui --log-disable
   ```

   Keep it under your existing process supervisor if desired. The lab used a
   foreground process and a different isolated port; no production service was installed.

3. Verify the advertised model before any real sources reach inference:

   ```sh
   curl -fsS http://127.0.0.1:8766/v1/models
   ```

   Require the exact alias `agentic-rag-qwen3-reranker-0.6b-q8`. The adapter checks
   this on every eligible request. An alias is an operator assertion: the checksum
   check above establishes which weights the trusted local runtime actually loads.

4. Run a synthetic multilingual positive/negative smoke test:

   ```sh
   curl -fsS http://127.0.0.1:8766/v1/rerank -H 'Content-Type: application/json' \
     -d '{"model":"agentic-rag-qwen3-reranker-0.6b-q8","query":"Was ist die Hauptstadt von China?","documents":["Beijing is the capital of China.","Paris is the capital of France."],"top_n":2}'
   ```

   Require one finite score per index, with Beijing above Paris. Reject a runtime
   with uniform/invalid outputs. The previously tested community conversion using
   Ollama generation logits failed this check; it is not the supported backend.

## Adopt and recover without knowledge migration

The supported source for this update is0.6.14, `7a61955`, schema027. No schema,
embedding, configuration-file rewrite, hook/job or client-adapter migration is
needed. Existing `[db]`, `[embed]` and `[ollama]` sections remain valid. The default
optional origin is `http://127.0.0.1:8766`; another literal loopback origin can be
added as `[rerank] url = "http://127.0.0.1:PORT"`. Hostnames, remote addresses,
credentials, URL paths, queries, redirects and environment proxies are rejected.

1. Stage the approved code checkout and keep the prior checkout available.
   Follow existing backup policy before any independently authorized deployment;
   this feature performs no persisted migration or destructive operation.
2. Restart only the CLI/MCP processes adopting the approved code. Old clients may
   continue against the same PostgreSQL store; no maintenance window or database
   restart is required. Claude/Codex/OpenCode configuration is untouched.
3. Compare a known question with `rag search QUERY --rerank off --json` and the
   default auto search. Verify original chunk spans, scope and expected sources.
   The MCP equivalent is `memory_search(..., rerank="off")` versus omitted mode.
4. Stop the optional runtime if verification fails, or restart affected MCP clients
   from the previous checkout. Old ordering works immediately with all persisted
   knowledge, pins, checkpoints, queue and audit history intact. Interrupted
   activation needs no repair: repeat the model checksum/smoke check and restart.

The adapter automatically considers only ordinary ambiguous auto searches with
three query terms and three documents, and a top-two distinct-document RRF gap
of at most 20 percent. Exact identifiers/error symbols, short/oversized queries,
explicit hybrid/lexical strategies and legacy benchmarks bypass neural inference.
At most 12 passages of 1200 characters and512 query characters enter one request;
a total 1500ms deadline covers discovery and scoring. It allows two concurrent
requests per client process with no local queue; model-runtime capacity remains
an operator responsibility across multiple clients. Invalid/timed-out responses
keep the original ordering with a generic warning. An absent endpoint/unrelated
model silently retains old ordering. Direct async callers of synchronous search
also retain old ordering. Neural scores never replace returned RRF scores.

The populated synthetic rehearsal compares every public table before/after
concurrent old/new readers and rollback. Trading measurements use a read-only
role and fixed snapshot. See [measured quality and latency limits](benchmarks/2026-10-03-neural-rerank/README.md).
No production rollout or acceptance is implied by these isolated checks.


## Identity and scope for 0.6.15

This system playbook is owned by the deployment administrator. Its origin is
Issue #62 and [AC062-003–007](openspec/changes/archive/2026-10-30-measured-reranker/proposal.md).
It must be reviewed and rehearsed before adopting 0.6.15. Last edited 2026-10-30;
[review and rehearsal evidence](playbooks/evidence/measured-reranker.md).
The operator is expected to know the existing CLI and private TOML configuration.
Production activation requires its own authorization. The measurement procedure
below uses only invented public sources and owned processes.

### Terms

| Term | Meaning |
|---|---|
| policy | Fixed input budget: `legacy-v1` or `focused-v1` |
| alias | Model name advertised by the trusted loopback runtime |
| revision | Operator-verified SHA-256 of the loaded model file |
| candidate | An already authorized original search hit eligible for reordering |
| held-out | Test families excluded from development selection |
| drain | Wait for an owned native runtime to become idle after cancellation |
| cgroup | Linux process group with jointly enforced CPU and memory limits |
| citation | Original chunk identifier and byte-independent character span |

### Inspect and choose a configuration

Keep the old checkout and a private copy of your configuration. All new fields
are optional; omitting them preserves the Qwen alias, `legacy-v1` and 1500 ms.
No provider migration, re-embedding or canonical write accompanies a policy change.
A configured revision labels an operator assertion; model discovery cannot prove
which weights are loaded. Check the model checksum independently before activation.

1. Inspect the staged configuration without sending a query:

   ```sh
   .venv/bin/python -c 'from agentic_rag.config import load_config; from agentic_rag.neural_rerank import inspect; print(inspect(load_config()))'
   ```

2. Choose a policy from the [measurement report](benchmarks/2026-10-30-measured-reranker/README.md).
   Retain `legacy-v1` unless your representative local acceptance supports a change.
   The smaller Jina tiny challenger is English-trained; its timing cannot establish
   German retrieval quality. Scores from different models are not comparable confidence.
3. Add only the approved options to the existing private `[rerank]` section:

   ```toml
   [rerank]
   url = "http://127.0.0.1:8766"
   policy = "focused-v1"
   model = "agentic-rag-qwen3-reranker-0.6b-q8"
   revision = "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48"
   timeout_seconds = 1.5
   diagnostics = true
   ```

4. Repeat the offline inspection. Require the approved route, alias and revision;
   `outcome=bypass` here describes inspection, not a live inference observation.
   Invalid aliases, non-hex revisions, unknown policies, nonboolean diagnostics,
   nonfinite deadlines and deadlines outside 0.01–1.5 seconds are rejected.

The [supplemental German diagnostic](benchmarks/2026-10-30-german-reranker/README.md)
rejects a blanket German recommendation for this pinned tiny/native combination:
six of sixteen German first sources are wrong, and six English probes produce
finite negative scores that trigger the adapter's unchanged range guard. General
production adoption remains blocked on semantic and contract acceptance.

The [four-model multilingual comparison](benchmarks/2026-10-30-multilingual-rerankers/README.md)
measures MiniLM L6 EN/DE, mMARCO, Jina v2 and Jina v3.5. On its fixed 48 German
and 48 English questions, mMARCO ranks 41/48 first sources correctly per language
with all 96 primary adapter calls accepted. L6 ranks 38/48 per language and has
more headroom in the concurrent load controls. mMARCO's padded two-client bursts
all time out, so its single-client result does not establish concurrent capacity.
Jina v2 improves German raw ranking but exceeds the deadline on longer inputs;
v3.5 times out on all 96 actual adapter calls and fails the prescribed long-text
runtime bound. The report retains that failure and all unattempted cells.
These lab bridges apply explicit score mappings and have not been activated
as production services. Jina weight licensing requires a separate adoption decision.

For a separately authorized Jina tiny lab test, use the pinned tiny file from the
rehearsal prerequisites with the same startup command, replacing `--model` with
that file and `--alias` with `agentic-rag-jina-tiny-en-q8`. In the private TOML
select `policy = "focused-v1"`, that same `model` alias, and
`revision = "0defc1f8a1f4dd22183124a2a25a97765603e5a9e42258046c9b2c8a26d1f553"`.
Repeat checksum, discovery, smoke and scoped acceptance before activation.
The Qwen example above shows the configuration syntax; it does not recommend
Qwen on hardware where the measured deadline fails.

The focused policy sends at most 6 passages of 600 characters. The legacy policy
sends 12 of 1200; both retain 512 query characters, 32 KiB responses and two nonqueued
requests per Python process. The tail is retained, ties preserve input order,
and original retrieval scores remain unchanged. Multi-client runtime capacity
requires separate sizing; the semaphore is not a global daemon queue.

### Validate adoption and recovery

1. Restart only the separately approved Python/MCP client processes from the new
   checkout. Existing 0.6.14 clients continue on the same schema027 database.
2. Compare an authorized representative query using
   `rag search 'YOUR APPROVED QUERY' --json` and the same command with
   `--rerank off`. Inspect original citations, domain/project and current sources.
   On central clients the server chooses the policy; configure/restart the approved
   server separately and use the existing authenticated `memory_search` contract.
3. Inspect the optional `rerank diagnostic:` warning. It contains only route,
   alias, revision, candidate/passage counts and a fixed outcome. It omits the
   endpoint, query, passages, response and exception. Exact-identifier/custom/off
   routes can bypass the neural stage before this warning is created.
4. Restore the saved configuration and 0.6.14 code if acceptance fails, then restart
   the affected local Python/MCP processes. If the central server adopted the
   change, restore its saved configuration and 0.6.14 server code under that same
   deployment authorization and restart that server. Recheck the same
   authenticated `memory_search` path and source/citation selections. Reverting
   client code alone does not change the central policy. No database downgrade
   or data restoration is needed.

Validation succeeds when clients preserve source eligibility and citations and
retain original ordering on unavailable/invalid/timeout inference. A timeout
bounds client waiting; it does not prove the daemon canceled native work.
Preserve private config/checksum and sanitized outcomes before escalating to
the deployment administrator. Do not increase the deadline or broaden source
permissions to make a failed model pass.

| Outcome | Operator decision |
|---|---|
| `ranked` | Validate retrieval quality locally; score is not proof of truth |
| `unavailable` | Inspect the intended loopback process and advertised alias; original ordering remains |
| `timeout` / `invalid` | Retain fallback; inspect the owned runtime and checksum before retry |
| `pressure` | Retain fallback; size runtime capacity before accepting concurrent clients |
| `bypass` / `async_bypass` | Check documented routing/query bounds; no inference was used |

### Reproduce the public resource rehearsal

Use Linux/systemd user services, PostgreSQL 17/pgvector, the project environment,
and independently verified native runtime/libraries and both pinned GGUF files.
The Jina Q8 conversion is pinned to
[34fdafe5a08b64246bcbfdbf0b8a23f818baf8e3](https://huggingface.co/gpustack/jina-reranker-v1-tiny-en-GGUF/tree/34fdafe5a08b64246bcbfdbf0b8a23f818baf8e3),
SHA-256 `0defc1f8a1f4dd22183124a2a25a97765603e5a9e42258046c9b2c8a26d1f553`.
This is an intentional local challenger, with no hosted reranking integration.

1. Set `RERANK_OUTPUT` and `RERANK_WORK` to new absolute output/work directories,
   and set `RERANK_BIN`,
   `QWEN_FILE` and `TINY_FILE` to inspected local files. Keep at least 2 GiB free
   working space. Ports 55463/8768/8769 must be unused. Existing production
   PostgreSQL and model daemons are outside this operation.
2. Run from the project checkout, substituting those inspected paths:

   ```sh
   systemd-run --user --wait --collect --unit=rag62-reference \
     -p MemoryMax=8G -p MemorySwapMax=0 -p CPUAffinity=0-3 -p CPUQuota=400% \
     -p "WorkingDirectory=$PWD" \
     "$PWD/.venv/bin/python" scripts/rehearse_reranker.py \
     --runtime "$RERANK_BIN" --qwen "$QWEN_FILE" --tiny "$TINY_FILE" \
     --output "$RERANK_OUTPUT" --work-dir "$RERANK_WORK" --repeats 2
   ```

3. Require successful systemd completion and `exit.json` with `exit:0`,
   `owned_processes_stopped:true`, no cleanup errors or remaining group members.
   Inspect `comparison/candidate.json` and `comparison/results.json`; require
   unchanged canonical rows, no indexing/query/citation failures and zero OOMs.
4. Preserve all output and retained PG data. Verify the unit is inactive and its
   cgroup empty externally. A missing exit artifact, forced shutdown or failed
   run is evidence of an incomplete rehearsal; inspect the unit journal and use
   a new output/work directory for a corrected run.

The wrapper creates marker-owned random databases and removes only those after
successful ownership checks. It copies weights inside the limited cgroup, records
all model/PG membership, verifies `/slots` idle between observations, and retains
all failure observations. An interrupted run is not resumable as the same sealed
experiment; retain artifacts and use fresh paths. Stop only the inspected owned
unit if it remains active. Revalidate this playbook after runtime/model API,
configuration, routing, resource envelope or schema changes.
