# Feature Specification: Confirmed-failure evaluation and offline optimization

## Stable work ID

RAG-5.10, Feature10/10, [Issue35](https://github.com/phense/agentic-rag/issues/35).
Implementation/publication are authorized. Request specific merges only after both
Feature9 and10 pass their gates. Production adoption is separately authorized.

## User scenarios

### US-001: Evaluate realistic retrieval failures (P1)

Measure unanswerable questions with plausible irrelevant evidence, same names in
independent projects/domains, and historical corrections. Compare identical inputs,
selectors and context budgets. Independent test: original source citations and every
miss/failure remain visible in baseline/candidate reports.

### US-002: Convert confirmed corrections into labels (P1)

An operator exports only explicitly confirmed, original complete active user corrections
from one exact project/domain. Independent test: assistant suggestions, withdrawn support,
expired/superseded/conflicting replacements and secrets never become labels. Export is
private, read-only, local and may legitimately contain zero cases.

### US-003: Produce a reviewable offline candidate (P1)

Optimize a finite routing/ranking/prompt grid on development cases; seal the chosen
candidate before held-out evaluation. Independent test: changing held-out labels cannot
change selection, split leakage is rejected before storage/provider access, and artifacts
never alter live configuration. Mining prompt effects require actual configured-provider
public-fixture measurements; deterministic replay establishes grounding contracts only.

## Acceptance criteria

- AC-001: Separate query families, source families, translations, copied evidence and
  correction histories across development/held-out splits. Record corpus/source/code
  revisions, every denominator/miss and family-based uncertainty or explicit unavailable.
- AC-002: Report supported extractive answer correctness, evidence recall, abstention,
  stale/wrong-scope exposure, p50/p95, context characters/token estimate and indexing cost.
  Extractive answers must be exact eligible original quoted values; do not claim general
  semantic model accuracy without an actual model stage.
- AC-003: Export requires accepted replacement, stated+confirmed claim and the exact
  retained complete reviewed active user source span, with original source versions and
  exact domain/scope. Later unsupported/expired replacements cannot revive old labels.
  Every string is secret-checked; private data never reaches public/provider paths.
- AC-004: Bound profiles to8, repetitions to30, contexts to1000–12000, exported cases to32.
  Preserve literal scope/domain/time selectors and source eligibility across profiles.
  Seal candidate hash/config/dev evidence before evaluating held-out cases once.
- AC-005: Actual public mining prompt comparisons preserve default extraction and durable
  accepted-batch/grounding contracts. Clicks and assistant confidence never label truth.
  Optional native provider stages are explicit and reject private correction inputs.
- AC-006: Preserve original benchmark run/compare, CLI/MCP privileges, writer gateways,
  old/new clients, configuration/hooks/jobs and the shared store. No new schema migration.
  Rehearse populated source compatibility, interruption/retry and code recovery on owned copies.
- AC-007: Publish three measured examples with revisions, raw paired repeats/quality
  denominators, unchanged inputs/budgets and warm/cold limits. Trading stays read-only.
- AC-008: Full Python/Node suites and independent complete reviews leave no C/H/M bugs;
  fix or link remaining Low bugs. Both PRs remain unmerged until explicit approval.

## Functional requirements

FR-001: Extend the benchmark with local owned-database optimization/evaluation commands.
FR-002: Produce immutable reviewable candidate/report files; production has no artifact loader.
FR-003: Use independent authored public labels or explicitly confirmed original correction
labels; diagnostic source hit, similarity, interaction and confidence are not truth.

## Compatibility boundaries

Source Feature9 reviewed branch476e42b/schema019; live1294d6c/schema018.
Feature10 is additive code-only and supports018/019. Combined adoption still requires019
and separate authority using Feature9's tested migration/recovery contract. Private export
must use reader privileges in a consistent read-only snapshot. Application/index writes
occur only via audited gateways in owned databases. No client/provider/config change.

## Interface contracts

| Contract | Boundary | Inputs | Outputs | Invariant |
| --- | --- | --- | --- | --- |
| IC-001 | Public optimizer | Synthetic strict failure corpus, bounded grid/budgets | Sealed candidate + separate dev/held-out reports | No live profile mutation or held-out tuning |
| IC-002 | Correction exporter | Exact domain/project or explicit global, limit/output | New0600 private artifact + counts | Exact original user truth, no overwrite/network |
| IC-003 | Private evaluation | Distinct private correction format | Local aggregate metrics + private detail | No provider/embedding/reranker network calls |
| IC-004 | Mining benchmark seam | Optional static prompt prefix, public owned session | Existing grounded extraction/application | Default prompt and accepted replay unchanged |

## Edge cases

Reject missing/duplicated labels, unsafe budgets, split/source leakage, malformed candidate,
secret/redacted labels, symlinks/overwrite/public export paths and provider use with private
inputs. Keep failed indexing/query/model cases in denominators. Empty correction export is
valid; insufficient independent families has null uncertainty. Conservative conflict/time
withholding may reduce recall, and a bounded public corpus cannot prove general quality.

## Assumptions and unresolved decisions

No unresolved scope decision. Use existing local embeddings and explicitly invoked existing
configured native provider for public mining comparisons only. Public labels are independently
authored synthetic fixtures; no private corpus is relabeled synthetic. No new provider/library.

## Success measures

SC-001: Reproducible candidate selection depends only on dev cases and fixed finite profiles.
SC-002: All original source/boundary/recovery oracles pass; every quality miss remains reported.
SC-003: Three public examples show measured before/after behavior, including unchanged safety
outcomes where the baseline already meets them. No improvement is preclaimed.

## Playbook obligations

PB-5.10: Evaluate a confirmed-failure corpus, inspect a sealed candidate and retry/recover
code-only adoption; maintainer/operator audience. Must be independently reviewed and rehearsed.
Feature9 PB-5.9 remains the combined schema upgrade path. No production operation is authorized.
