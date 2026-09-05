# Synthetic evidence semantics

Command: `PYTHONPATH=. python docs/benchmarks/2026-09-06-claim-evidence/evaluate.py`
with the project environment. This deliberately calls the configured model once.
Eight content-free synthetic EN/DE source/claim pairs; no private corpus. Provider:
Codex / GPT-5.6 Luna. Elapsed 13.79 seconds; billing/token usage not exposed.

Semantic support matched all 8 labels. Speech-act classification matched 7/8. The
rejected quoted proposal was labeled inference rather than proposal; importantly the
model correctly rejected its support for the claimed action. All eight reasons and
labels were inspected and retained, including the discrepancy. No relabeling/tuning.

This evaluates semantic entailment separately from source-span membership. It does
not turn the production structural check into a truth verifier. Production conservatively
keeps paraphrases/translations unreviewed until explicit review, even when this semantic
evaluation finds them entailed. This small fixture establishes no general accuracy.
