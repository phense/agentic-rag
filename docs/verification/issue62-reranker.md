---
title: Measured local reranker verification
type: reference
doc_id: standalone
readers: [maintainer, operator]
version: 0.6.15
status: verified
last_edited: 2026-10-30
summary: Independent bounded review, populated old/new client recovery and resource evidence for Issue #62.
---

# Measured local reranker verification

Issue #62 extends the existing optional ordering seam with explicit bounded local
configuration and safe diagnostics. The source installation is 0.6.14/schema027
at `7a61955446119df522a34967273d8dacae56108b`; target 0.6.15 retains schema027.
No SQL migration, embedding rebuild, authority change or client-config rewrite
is required. Old and new clients continue against one audited PostgreSQL store.

Writing depth: medium standalone reference. The operator is the deployment
administrator; [PB062-OPS](../local-reranker.md) defines activation and recovery.
The [measurement report](../benchmarks/2026-10-30-measured-reranker/README.md)
separates public synthetic results from production acceptance.

## Runtime and recovery boundary

Defaults retain Qwen, 12 passages of 1200 characters and a 1500 ms deadline. Focused
configuration sends at most 6 passages of 600 characters. Model alias/revision and
diagnostics are optional. The same 512-character query, 32 KiB response and two
nonqueued in-flight Python calls apply. Runtime work may continue after HTTP
cancellation; daemon capacity must be sized across clients separately.

Original authorized/current source selection precedes inference. A complete
permutation restores the original hit objects, source diversity and citation
payloads. Unavailable, malformed, timeout, pressure, short/exact and unsupported
async cases retain deterministic ordering. No score becomes a truth probability.
Model alias discovery verifies a local assertion; only an independent checksum
check establishes the operator's loaded weights.

The populated compatibility test uses five evidenced claims, a foreign-project
source and existing authenticated user/machine policy. It verifies local/HTTP
ranking and payload parity, exact-selector bypass, source withdrawal before
inference and after server restart. It then extracts the complete actual 0.6.14
engine with `git archive`, starts it in a fresh interpreter, restores the old
configuration and checks both direct reads and its actual ASGI authenticated
`memory_search` payload against current rollback results. Original public-table
hashes remain unchanged, excluding bounded read admission/tracing/presence rows.
This proves application-level central routing; external TLS, deployed services,
fleet capacity and private queries require separate production acceptance.

## Independent review

The native reviewer `/root/reranker_contract_review` did not implement product
files or execute provider/database calls. It reviewed the complete bounded diff
at `4ac82cdf2aca20b54d7071eb59ac0437cfdcd550` against 7a61955, all 25 changed files,
after contract and implementation reviews. No C/H/M or actionable Low finding
remained in that static snapshot. Independent review also reconstructed the
primary and supplemental measurements, all sealed source hashes, numeric examples
and cleanup evidence. The [final acceptance artifact review](issue62/reviews/final-delivery-review.txt)
independently confirms the completed suite, frozen source, package contents,
release metadata and local links. No unresolved C/H/M or actionable Low remains.

| Finding | Resolution and evidence |
|---|---|
| Reference-class and confirmed-failure origin gaps | Effective combined 4 CPU / 8 GiBzero-swap lab; exact prior public dev report hash plus fresh six-case baseline reproduction |
| Later repeat failures hidden | Aggregate every failed trial and affected query without multiplying unique quality cases; RED regression |
| Extra inference failures permitted by selection | Count fixed failure outcomes per paired trial; reject additional failures and all-failed faster candidates; RED regressions |
| Incomplete execution seal | Bind full per-profile settings, source/corpus, wrapper and executable/library manifest; reject drift/unsupported baseline |
| Partial PG startup/crash cleanup | Track direct child before readiness; independent cleanup and explicit failure artifact; real partial/crashed-child regression |
| Citation error lost its fixed tag | Actual `_one`→summary test reproduces error; preserve only two known safe codes |
| Forced parent stop could hide descendants | Force-stop is a failed run; require no remaining cgroup members; external unit cleanup check |
| Duplicate request under EN/DE IDs | Reject duplicate real request contracts regardless ID/label; remove duplicated temporal control; RED regression |
| Central rollback procedure ambiguous | Restore server code/config and restart approved server; actual archived-server ASGI recovery test |

The [complete code review](issue62/reviews/final-code-review.txt) and
[measurement/publication review](issue62/reviews/final-evidence-review.txt) retain
the independent scope, findings and exact hashes. Earlier reports and every
resolved finding are also preserved in the adjacent review directory. The final
[documentation delta review](issue62/reviews/final-documentation-review.txt)
checks configuration, procedures and publication fidelity. Complete-suite
evidence is linked below.
No new Low finding has been identified for Issue75 in this slice.

## Verification commands and observed status

- `pytest -q tests/test_neural_rerank.py tests/test_measured_rerank.py tests/benchmark/test_rerank_evaluation.py tests/benchmark/test_runner.py tests/service/test_rerank_compat.py --tb=short`:
 108 passed, one upstream Starlette deprecation warning, 44.68 s, exit 0 at 4ac82cd.
- `node --test tests/test_opencode_plugin.mjs`: 7 passed, 0 failed, 236.91 ms.
- `uv lock --check --offline`: 45 packages, exit 0.
- `uv build --wheel --offline`: built 0.6.15 wheel, then installed without dependencies
  into an owned target outside the checkout. Actual imported package path,
  default offline inspection, corpus-v2 and packaged SQL were checked. Wheel SHA256
  `6a081b14fb7d11eb471ee570b58998bd46423761eec8e7771c648bda15a2831e`.
- The combined native-model run and supplemental process-cold run completed with
  exit 0; independent review found no open C/H/M issue in their evidence.
- Final complete command: `.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider`.
  1735 passed, 1 skipped, 1 warning in 1565.23s (0:26:05). Actual exit 0; all 343 before/after
  file hashes match, including README.md and CHANGELOG.md. The
  [complete output](issue62/full-green.log) and
  [exit/source manifest](issue62/full-green-exit.json) retain the result. The skipped
  launchd test is macOS-only; the warning is upstream Starlette/httpx deprecation.

All PostgreSQL testing uses owned nonproduction ports 55460/55463 and public
synthetic inputs. Real local model measurements use copied checksum-verified
GGUF weights in one limited cgroup. No private hosted inference, production
migration/restart or automatic model adoption is included.

## Retained verification attempts

The [first complete attempt](issue62/full-v2.log) stopped with exit 2 after
five browser launch failures and 190 passing tests. Missing system libraries
were supplied from an existing owned test directory through LD_LIBRARY_PATH;
no system package installation was needed. All five browser tests then passed.
The exact browser and library hashes are in the
[browser runtime record](issue62/browser-runtime.json).

The [next complete run](issue62/full-final.log) ended with exit 1:
1734 passed, one skipped and one release-heading failure, in 1519.17 seconds.
The changelog lacked the required dated bracketed version heading. The actual
regression was reproduced, the heading corrected, and all 17 documentation
checks passed. Its [exit manifest](issue62/full-final-exit.json) confirms unchanged files in
that 342-file manifest, which did not include CHANGELOG.md. The fresh complete run
also freezes CHANGELOG.md. These failed attempts do not count as passing gates.

## Delivery checks

The [release/package record](issue62/release-package-check.json) records all four
0.6.15 metadata references, the installed wheel and its 27 SQL files. PB062-OPS
and the measurement report were rendered as local HTML and visually inspected.
The [owned test PostgreSQL cleanup](issue62/test-postgres-cleanup.json) proves the
55460 identity check, successful stop, refused port and retained data. The model
rehearsals retain their own independent cleanup records.

The four accepted requirements are synchronized into the main retrieval-ordering
spec. The [archive record](issue62/archive.json) verifies byte-identical movement
of all four change files. The [final mechanical checks](issue62/final-checks.json)
cover link integrity, current frozen hashes and the final playbook hash. After
archival, all 17 documentation checks passed again in 0.85 seconds.
