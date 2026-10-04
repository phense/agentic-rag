# Design: Local neural ordering at the existing callback

The verified prototype uses Qwen3-Reranker-0.6B Q8_0, ggml-org revision
`a02f48bb4f057028298c21fa033da2b30d7742d5`, SHA-256
`22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48`.
llama.cpp b9840 (`8c146a836`) native /v1/rerank yields differentiated positive
and negative multilingual pair scores. An earlier community GGUF through Ollama
/api/generate returned uniform punctuation logits; it was rejected, never shipped.

Only literal 127.0.0.1 / ::1 URLs are accepted, with no credentials, path,
query or fragment. Disable proxies and redirects. Verify the configured runtime
advertises the pinned model alias before sending source passages. A missing
endpoint/model silently preserves old ordering; failures after matching identity
produce the existing generic fallback warning, without request text/exceptions.

Policy: auto only, no exact shortcut or strong symbols, at least three query
terms and three candidate documents, top two distinct-document RRF scores within 20 percent.
Keep at most twelve candidate passages of 1200 characters, query at most512
characters, with a total 1500ms deadline for discovery and scoring. At most two
requests may run in one client process; pressure falls back, without a local queue.
Fork resets the semaphore. Oversized/short queries bypass instead of truncating
meaning. The model only sees already SQL-eligible candidates, no graph additions.
Accept finite scores in [0,1] for each input index exactly once and matching model
identity; stable sort by score then original index. Retain original score/payloads,
append untouched tail and pass complete permutation to existing validation.
Uncalibrated model scores never enter the result payload or become confidence.

No new schema, dependency, model-store writes or hooks/jobs/adapters are involved.
The previous Python callback takes precedence; explicit hybrid and benchmark
baseline remain previous behavior. Config adds only [rerank] url; one optional
CLI/MCP mode disables the adapter. Total timeout uses cancellable asynchronous
HTTP in the synchronous search adapter; a caller already owning an event loop
uses safe old ordering rather than nesting event loops.
