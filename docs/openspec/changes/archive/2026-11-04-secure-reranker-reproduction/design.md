# Change Design: Secure maintained reranker reproduction

## Context

The archived ONNX bridge loads tokenizer JSON and ONNX graphs. Its v3.5 branch
uses `AutoModel.from_pretrained(trust_remote_code=True)`. The current application
class `OnnxRanker` validates model/tokenizer hashes before loading and needs only
NumPy, tokenizers and ONNX Runtime. The production catalogue contains Jina tiny;
the historical comparison used Jina v2. Do not substitute these models.

## Interface contracts

| Boundary | Delta | Failure behavior |
|---|---|---|
| Historical evidence | Read-only source of corpus/model identities | Never rewrite |
| New script | Explicit local models, profile, exclusive output directory | Nonzero result with retained journal |
| Runtime | Reuse `OnnxRanker`, staged verified files, bounded child | Kill owned child on deadline; retain failures |
| Dependencies | Hash-pinned wheel export; reject installed Transformers/setuptools | Refuse before inference |
| Identity | Record package versions, script/runtime/manifest/corpus hashes, model bytes | Source or artifact drift fails |

## Dependencies

Use the project's `reranker` extra exported from `uv.lock`, excluding the
editable project. Install the separately built application wheel. No loader
calls `prepare`, Hub APIs, AutoModel, Trainer or `save_pretrained`.

## Tests

Write CLI regression tests first: unsupported v3.5 must not create output;
tampered artifacts fail and retain a result; a deadline retains unattempted
cases; a real synthetic graph/tokenizer produces literal expected order.
Exercise existing runtime cancellation/capacity contracts unchanged.
Verify requirements rebuild, wheel identity, historical hashes, and focused
release/upgrades. Run a broad suite once near PR only if justified by scope.

## Decisions

| Decision | Evidence | Alternative rejected |
|---|---|---|
| ONNX-only maintained path | Three historical profiles already have pinned ONNX files | Blind Transformers major update cannot prove v3.5 compatibility or consent |
| New smaller protocol | Loader/security acceptance needs no model download | Rerun 2,688-observation quality/performance experiment |
| Own child per profile | Native inference cannot be cancelled safely in a thread | Reuse process after timeout |
| Own staged artifacts | Same loaded bytes as verified manifest | Concurrent edits of input paths during inference |

## Risks and rollback

ONNX graphs still execute native code; artifact hashes and a trusted runtime
are required, and this is not an arbitrary-model sandbox. Memory/CPU limits
and wall deadlines bound the owned child. New output directories are exclusive;
an incomplete run is never overwritten. Keep old and new measurements separate.

## Playbook obligations

The standalone guide is the benchmark operator procedure. Validation uses a
fresh isolated wheel environment and synthetic artifacts, with no production
database, provider, model download or service interruption.
