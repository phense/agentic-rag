# Change Proposal: Secure maintained reranker reproduction

## Stable work ID

- Change ID: `secure-reranker-reproduction`
- Issue: [#89](https://github.com/phense/agentic-rag/issues/89)
- Status: Approved for implementation by the maintainer's continuation request

## Why

Eight advisories affect Transformers/setuptools in the archived 2026-10-30
benchmark manifest. Editing that manifest would falsify historical provenance.
The application already has a checksum-verifying ONNX inference class that
does not use either package. Reuse it in a separate benchmark-only entry point.

## Changed requirements

Add maintained offline reproduction requirements under
`specs/reranker-reproduction/spec.md`. Preserve the archived protocol's failed
status (2,338 actual observations, 350 unattempted, 2,688 prescribed).

## Acceptance criteria

- AC-001: Historical files remain byte-identical; new commands and outputs have
  separate dependency, corpus, model and source identities.
- AC-002: The maintained environment contains neither Transformers nor
  setuptools. It accepts only the three pinned historical ONNX profiles;
  v3.5 is refused before loading or downloading anything.
- AC-003: Real synthetic ONNX/tokenizer artifacts exercise loading and scoring;
  corruption, unsupported profiles, timeouts and errors fail with retained
  artifacts and explicit attempted/unattempted counts.
- AC-004: The documented fresh-wheel environment is rebuilt and checked, all
  eight advisories receive evidenced dispositions, and the complete change is
  independently reviewed with no Critical/High/Medium findings.

## Compatibility boundaries

Production APIs, catalogue, SQL, models and stored data remain unchanged.
This adds an opt-in benchmark script, not an alternate production ranker.
The normal patch release includes existing-installation version-label checks.
Rollback uses the prior application environment; benchmark output remains.

## Scope

In scope: a hashed wheel-only environment, bounded offline ONNX reproduction,
synthetic verification, advisory dispositions and reproducible commands.
Out of scope: production rollout, model downloads, repeating the original
four-model performance matrix, or claiming a repair to v3.5 inference.

## Escalation check

New subsystem: No. Tightly coupled components: No. Risky migration: No.
Material architecture uncertainty: No; reuse `OnnxRanker` without changing it.

## Playbook obligations

One medium standalone reproduction guide documents setup, failure retention and
rebuild/rollback. It is reviewed with the script and rehearsed using synthetic
artifacts. No production operation or separate production playbook is added.
