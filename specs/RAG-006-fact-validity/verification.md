# RAG-006 verification

Verified 2026-09-06 in the isolated feature worktree; base f592dd6.

- Full command: `PYTHONPATH=. /Users/peter/Agents/agentic-rag/.venv/bin/python -m pytest -q`
  — **703 passed in 17.33s** after all implementation fixes.
- `uv build --wheel --out-dir /private/tmp/rag-issue6-wheel` passed. Archive inspection
  confirmed migration011, validity gateway and temporal fixture are included.
- Independent review inspected the core and benchmark changes, then rechecked fixes.
  Final verdict: ready; no remaining Critical/Important findings. Reviewer made no
  database/provider calls and did not implement the reviewed code.
- Fixed findings with regressions: questions/proposals cannot authorize replacement;
  clipped source prefixes are review-only; reactivation epoch is revalidated after
  model response under locks; duplicate assertions retain independent source evidence.
  Unselected graph history compatibility is preserved.
- Architecture-derived integration: source -> accepted mining batch -> assertion
  gateway -> separate reader -> current/as-of search and startup; scoped graph excludes
  expired intermediate assertions. More than 50 expired candidates cannot consume
  the search limit. Pins and independent attributes remain intact.
- Recovery integration: injected failure after replacement effects preserves the
  old current assertion and original document/edge/evidence/audit counts except the
  deliberately durable acceptance audit. Replay uses accepted output, commits once,
  and a second replay changes no counts. Concurrent same-key writers are serialized.
- Existing additive migration and reader privilege checks pass; no temporal backfill
  is inferred for legacy documents. Source windows remain cursor-lossless.
- [Versioned comparison](../../docs/benchmarks/2026-09-06-fact-validity/README.md):
  six synthetic sources/eight questions, equal corpus/source hashes and search budget.
  Two total Luna answer calls; no private data. Stale-result rate 5/8 -> 0/8;
  stale-answer rate 1/8 -> 0/8; current/historical recall both1.0. All16 answers inspected.
  Small controlled fixture only; citation quality and date-language parsing unmeasured.

Convergence: all application acceptance criteria and architecture findings are covered;
no additional implementation tasks. Remaining operational gate: fresh backup, additive
migration/code activation, invariant readback, publication and CI/issue synchronization.
