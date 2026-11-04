---
id: RAG089-REPRODUCTION
title: Rebuild the maintained offline reranker benchmark
type: task
readers: [repository-maintainer]
status: reviewed
version: 0.6.32 / schema039
last_reviewed: 2026-11-04
summary: Build a separate wheel-only ONNX environment while preserving historical measurement identities.
---

# Rebuild the maintained offline reranker benchmark

Use this path for future offline loader and source-ranking checks. It runs the
three pinned ONNX candidates from the historical comparison: MiniLM L6, mMARCO
and Jina v2. It reuses the installed `OnnxRanker` and accepts only existing local
model/tokenizer files. It does not fetch models or execute Python from a model
repository. The current production catalogue's **Jina tiny is a different
model**; this command does not change that catalogue.

This is a medium standalone operator procedure for [Issue #89](https://github.com/phense/agentic-rag/issues/89).
The protocol `maintained-onnx-smoke-v1` records one fresh child and the supplied
corpus per invocation. Its timing is descriptive; it does not repeat the old
performance matrix or establish production capacity.

## Terms

| Term | Meaning here |
|---|---|
| Profile | A pinned benchmark model identity; it does not enable a production model. |
| Wheel | A built Python distribution installed with its verified file hash. |
| ONNX | A model graph executed by the native CPU runtime. |
| Staging | A private, verified copy removed after inference. |
| Unattempted | A case for which no inference observation exists; it is not a zero score. |
| Source identity | Hashes of the runner, loader, corpus, model manifest and dependency specification. |

## Preserve the historical record

Leave every file in `../2026-10-30-multilingual-rerankers/` unchanged. Its frozen
requirements file has SHA256
`4723b5be90e437d65fce338aa842728599591fed61ecda52703c381f86d5e163`.
It describes an old measured environment and is **not approved for a fresh
installation**. The original prescribed 2,688-observation experiment failed:
2,338 observations were collected and 350 v3.5 observations were unattempted.
The new runner supplies no new v3.5 evidence. That custom-code profile is
refused before model access; do not replace it with a text model or an ONNX
candidate and retain its name.

## Build an isolated environment

Prerequisites: a trusted checkout of this release, CPython 3.13, `uv`, Linux,
and enough disk space for the wheels plus a second copy of the selected model.
Only use a public or explicitly approved corpus. Jina v2's noncommercial weight
license still requires a separate commercial adoption decision. Installing
Python wheels is separate from downloading model artifacts; #89 authorizes no
model download or production change.

1. From the repository root, check the lock and build the application wheel:

   ```bash
   uv lock --check --offline
   uv build --wheel --out-dir "$HOME/Claude/.scratch/rag089-wheel-032"
   sha256sum "$HOME/Claude/.scratch/rag089-wheel-032/agentic_rag-0.6.32-py3-none-any.whl"
   ```

2. Create a new environment and install the hashed wheels. A missing wheel or
   hash mismatch must stop this step; do not enable source builds as a fallback.

   ```bash
   uv venv --python 3.13 "$HOME/Claude/.scratch/rag089-runtime-032"
   uv pip install --python "$HOME/Claude/.scratch/rag089-runtime-032/bin/python" \
     --require-hashes --only-binary :all: \
     -r docs/benchmarks/maintained-rerankers/requirements.txt
   uv pip install --python "$HOME/Claude/.scratch/rag089-runtime-032/bin/python" \
     --no-deps "$HOME/Claude/.scratch/rag089-wheel-032/agentic_rag-0.6.32-py3-none-any.whl"
   uv pip check --python "$HOME/Claude/.scratch/rag089-runtime-032/bin/python"
   ```

3. Check the installed runtime before using models:

   ```bash
   "$HOME/Claude/.scratch/rag089-runtime-032/bin/python" -I -c \
     'from importlib.metadata import version,packages_distributions; print(version("agentic-rag")); print(version("onnxruntime")); assert not {"transformers","setuptools","torch"} & packages_distributions().keys()'
   ```

Validation: the application reports 0.6.32, dependency checking exits 0, and the
forbidden-package assertion passes. The runner additionally compares installed
versions with the applicable pinned requirements. On another platform without
a matching wheel, stop and record the unsupported environment; Linux was
rehearsed. No macOS or Windows runtime claim follows from the lock markers.

## Run an existing pinned model

1. Identify the previously approved local model directory. It must contain
   `<profile>/model.onnx` and `<profile>/tokenizer.json`, matching
   `scripts/reranker_benchmark_models.json`. Set an absolute path:

   ```bash
   MODEL_ROOT=/absolute/path/to/already-approved-models
   ```

2. Choose a **new** output directory and run one candidate:

   ```bash
   "$HOME/Claude/.scratch/rag089-runtime-032/bin/python" -I \
     scripts/benchmark_reranker_offline.py \
     --profile mmarco --models-dir "$MODEL_ROOT" \
     --output-dir "$HOME/Claude/.scratch/rag089-mmarco-attempt-001" \
     --threads 4 --timeout 300
   ```

3. Read `result.json`, `manifest.json`, `observations.jsonl` and `worker.log` in
   the output directory. Require exit0, `status=completed`, all requested cases
   scored, zero failed and zero unattempted. Inspect the recorded model hashes,
   package versions, source hashes and corpus identity before comparing runs.

The other allowed profiles are `minilm-l6` and `jina-v2`. Each needs its own
output directory. The default corpus contains 96 public synthetic DE/EN cases;
`--corpus` accepts another bounded JSON corpus with the same case/passages/
expected-ID shape. Bounds are 128 cases, 12 passages per case, 512 query
characters, 1,200 characters per passage and a 2 MB corpus file. ONNX input is
truncated at 512 tokens per query/passage pair. Scores are sigmoid-transformed
logits, not truth probabilities or calibrated values across models.

The child has a 6 GiB address-space limit, a 600 CPU-second ceiling, up to 4 ONNX
threads and the selected wall deadline (0.1–600 seconds). CPU execution is
explicit. It receives no inherited credentials and uses private cache paths.
HF offline flags are set; the loader calls only the local tokenizer and ONNX
APIs. This is **not an arbitrary-model sandbox**: pinned artifacts and trusted
native runtime wheels remain required. Verified files are copied into the
owned output directory before inference and removed after the child exits.

## Handle a failure or dependency upgrade

Retain the failed output. A timeout kills the owned child; completed observations
remain, and missing cases are listed as unattempted. A corrupt artifact, invalid
graph, installed forbidden package or lock mismatch exits nonzero. Read the recorded
`stage`, error class and worker log, correct the cause, then use a new output path.
Existing output is never overwritten. Do not count a failed invocation as a
quality result or replace missing values with zero.

For dependency upgrades, edit the current project constraints/lock in a new PR,
then regenerate this maintained file with:

```bash
uv export --frozen --extra reranker --no-dev --no-emit-project \
  --format requirements-txt \
  --output-file docs/benchmarks/maintained-rerankers/requirements.txt
```

Rebuild a new environment and repeat the synthetic loader, corruption, deadline
and retained-failure tests before new measurements. Keep old environments out
of PATH; code rollback selects the prior application environment and preserves
all benchmark output. No schema/data rollback is needed. Never update the
historical frozen requirements or relabel old measurements with new versions.

## Advisory dispositions and inventory

The eight primary advisories were read on 2026-11-04. Their packages are absent
from the maintained wheel environment. The historical bridge's v3.5 branch
does invoke AutoModel with explicit custom-code trust; offline flags and pinned
files do not justify dismissing package-level advisories. Its upstream custom
Python was not exhaustively re-audited here.

| Advisory | Historical reachability and maintained disposition |
|---|---|
| [GHSA-5rjg-fvgr-3xxf](https://github.com/advisories/GHSA-5rjg-fvgr-3xxf) | setuptools `PackageIndex.download` traversal; no such call in the bridge. Historical installation is not approved. Maintained path omits setuptools and installs hashed wheels only. |
| [GHSA-69w3-r845-3855](https://github.com/advisories/GHSA-69w3-r845-3855) | `Trainer` RNG checkpoint loading, conditional on older PyTorch. Bridge has no Trainer call; frozen torch 2.15 is newer than the described <2.6 condition. Maintained path omits Transformers and Torch. |
| [GHSA-29pf-2h5f-8g72](https://github.com/advisories/GHSA-29pf-2h5f-8g72) | Model-config-driven code loading is relevant to the old AutoModel entry point; no claim of complete historical non-exploitability. Maintained path has no AutoModel or Python model loader. |
| [GHSA-fgcw-684q-jj6r](https://github.com/advisories/GHSA-fgcw-684q-jj6r) | LightGlue nested trust override is not the requested old model architecture, but the old general loader remains unsupported. Maintained path omits Transformers. |
| [GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c) | setuptools sdist exclusion bypass on normalization-preserving filesystems; old measurement was Linux inference, not a macOS sdist build. Maintained reproduction omits setuptools and source builds. |
| [GHSA-xrqw-3rrv-vx5w](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w) | No `save_pretrained` call in our bridge; arbitrary upstream custom-code behavior is not proven absent. Maintained loader reads local tokenizer JSON and never saves a Transformers tokenizer/processor. |
| [GHSA-x9r9-c232-4q39](https://github.com/advisories/GHSA-x9r9-c232-4q39) | Pre-consent custom-generation download; advisory lists no patched version. A blind version bump is not accepted remediation. Maintained path has no Transformers/custom-generation API and refuses v3.5 before loading. |
| [GHSA-xmj3-9gf7-h52w](https://github.com/advisories/GHSA-xmj3-9gf7-h52w) | Windows legacy wheel namespace traversal; old measurement was Linux. Maintained reproduction omits setuptools and its legacy installer. |

The documented local `.scratch/rag62-three-models-20261030/venv` is absent.
A bounded inventory found no `pyvenv.cfg` below local `.scratch` paths containing
`rag62` (depth ≤5), and no `*rag62*` roots directly under Hetzner `/home/admin`
or `/var/lib`. This does not inventory arbitrary renamed copies or offline
archives. None were deleted as part of #89. Production environments were not
changed. Automated alerts attached to the frozen file may remain visible;
these dispositions preserve its historical meaning.

## Recorded verification

The [fresh-wheel rehearsal](verification/rebuild-verification.json) installed
44 hash-verified runtime wheels plus the noneditable 0.6.32 application wheel;
`uv pip check` exited 0. Its model was an **own synthetic ReduceSum graph**,
with two cases, not pretrained mMARCO weights. The [raw result](verification/synthetic-result.json)
and [two observations](verification/synthetic-observations.jsonl) retain actual
runtime/source/model identities, literal score ordering and cleanup status.
This proves the loader path, not the quality or speed of a public model.

The [targeted check result](verification/targeted-result.json) and
[log](verification/targeted.log) record 118 passed tests with one existing
Starlette deprecation warning. They cover loader failures and partial
accounting, unsupported profiles, timeout cleanup, unchanged runtime HTTP
capacity/cancellation, and the existing evaluation contracts. No full-suite
or production acceptance is claimed by this bounded benchmark change.

The [compatibility result](verification/compatibility-result.json) records 54
additional passed release/upgrade tests, including populated archived 029
upgrades and independently restored backups with an owner without superuser
rights. The [independent review](verification/code-review.json) accepted the
complete 30-file implementation diff with zero Critical/High/Medium/Low
findings; its [procedure review](verification/procedure-review.json) found
zero Important/Minor issues. Final evidence, glossary/status and lifecycle
updates after that reviewed commit change no executable code.
