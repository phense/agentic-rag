---
id: local-neural-reranker
title: Run a local multilingual reranker
type: how-to
doc_id: standalone
readers: [maintainer, operator]
status: reviewed
version: feature/local-rerank against 342bccf
last_reviewed: 2026-10-03
depends_on: []
assets: []
summary: Deploy an optional pinned loopback model without changing canonical knowledge.
---

# Run a local multilingual reranker

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

The supported source is merged PR #38, `342bccf`, migrations001–014. No schema,
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
