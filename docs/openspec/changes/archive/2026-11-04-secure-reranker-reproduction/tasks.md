# Change Tasks: Secure maintained reranker reproduction

## Stable work ID

- Change ID: `secure-reranker-reproduction`
- Issue: #89

## Tests

- [x] C001 Observe regression tests fail before implementation: unsupported
  custom-code profile, corrupted artifacts, deadline and retained failures.

## Implementation

- [x] C002 Add separate pinned ONNX profile manifest and bounded offline driver;
  reuse the application loader and preserve historical files; depends C001.
- [x] C003 Export hashed wheel dependencies and verify a fresh isolated rebuild
  with real synthetic ONNX scoring and no forbidden packages; depends C002.
- [x] C004 Write/rehearse the medium reproduction guide, advisory reachability
  and environment inventory; record historic and new evidence separately.
- [x] C005 Apply patch release metadata and run focused affected checks;
  independently review the complete bounded diff and fix C/H/M findings.

## Completion evidence

- [x] C006 All implementation tests, compatibility checks and history hashes pass;
  publish exact commands, terminal results, limits and accepted review. Prepare
  the accepted delta for the normal PR delivery gate.

Delivery remains tracked in canonical Issue89: merge the verified PR, then
close bot PR85/86 as superseded without changing archived manifests. A checked
implementation task does not claim that merge or production rollout occurred.

## Dependencies

C001 → C002 → C003 → C004 → C005 → C006. One executor owns implementation.
The independent reviewer reads a frozen complete diff after verification.

## Playbook obligations

C004 covers the benchmark operator procedure and safe failure/rebuild path.
No production rollout or production playbook is part of this change.
